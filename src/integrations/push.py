"""Web Push (Tier 3) — subscription storage + send helpers.

VAPID-signed Web Push lets the PWA receive push notifications even when the
browser isn't open, with rich features ntfy.sh can't match: action buttons,
custom click URLs, app-like styling on iOS 16.4+.

Three pieces live here:

1. :class:`SubscriptionStore` — pluggable JSON storage for browser
   subscription records (one per device). File-backed in dev, S3 in Lambda.
2. :func:`send_push` — fire one push to one subscription. Handles VAPID
   signing via ``pywebpush`` and surfaces ``410 Gone`` so callers can prune
   expired subscriptions.
3. :class:`PushSubscription` — Pydantic model for the subscription payload
   the browser hands the PWA via ``pushManager.subscribe()``.

Designed so the nag worker can iterate active subscriptions and send the
same message body to each, falling back to ntfy if pushing fails.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings, get_settings
from ..utils.logging import get_logger

log = get_logger(__name__)


# --- Pydantic models -------------------------------------------------------


class _Keys(BaseModel):
    """The ECDH key material the browser emits with the subscription."""

    p256dh: str
    auth: str

    model_config = ConfigDict(extra="ignore")


class PushSubscription(BaseModel):
    """One device's Web Push subscription.

    Matches the JSON the browser's ``PushSubscription.toJSON()`` produces
    so the PWA can POST it verbatim.
    """

    endpoint: str
    keys: _Keys
    # Optional metadata we add server-side so we can debug + prune.
    label: str | None = None  # free-text device label ("my iphone")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    model_config = ConfigDict(extra="ignore")

    def cache_key(self) -> str:
        """Stable identifier for dedup. The endpoint URL is unique per device."""
        return self.endpoint

    def to_pywebpush(self) -> dict[str, Any]:
        """Format expected by ``pywebpush.webpush(subscription_info=...)``."""
        return {
            "endpoint": self.endpoint,
            "keys": {"p256dh": self.keys.p256dh, "auth": self.keys.auth},
        }


# --- Storage ----------------------------------------------------------------


class SubscriptionStore(Protocol):
    def load(self) -> list[PushSubscription]: ...
    def save(self, subs: list[PushSubscription]) -> None: ...


class FileSubscriptionStore:
    """JSON-list file backend. Used in dev."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[PushSubscription]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        out: list[PushSubscription] = []
        for entry in raw:
            try:
                out.append(PushSubscription.model_validate(entry))
            except Exception:
                continue
        return out

    def save(self, subs: list[PushSubscription]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [s.model_dump() for s in subs]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class S3SubscriptionStore:
    """S3 object backend. Used in Lambda."""

    def __init__(self, bucket: str, key: str) -> None:
        import boto3  # noqa: PLC0415

        self.bucket = bucket
        self.key = key
        self._s3 = boto3.client("s3")

    def load(self) -> list[PushSubscription]:
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=self.key)
        except self._s3.exceptions.NoSuchKey:
            return []
        except Exception as e:
            log.warning("push.s3_load_failed", error=str(e))
            return []
        try:
            raw = json.loads(resp["Body"].read())
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        out: list[PushSubscription] = []
        for entry in raw:
            try:
                out.append(PushSubscription.model_validate(entry))
            except Exception:
                continue
        return out

    def save(self, subs: list[PushSubscription]) -> None:
        body = json.dumps([s.model_dump() for s in subs], indent=2).encode("utf-8")
        self._s3.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=body,
            ContentType="application/json",
        )


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_subscription_store() -> SubscriptionStore:
    """Choose backend by env: S3 in Lambda, file in dev.

    Reuses the existing ``NAG_STATE_BUCKET`` so we don't add new infra; the
    key is fixed as ``push_subscriptions.json``.
    """
    bucket = os.environ.get("NAG_STATE_BUCKET")
    if bucket:
        return S3SubscriptionStore(
            bucket=bucket,
            key=os.environ.get("PUSH_SUBS_KEY", "push_subscriptions.json"),
        )
    return FileSubscriptionStore(_PROJECT_ROOT / "state" / "push_subscriptions.json")


# --- High-level subscription ops -------------------------------------------


def upsert_subscription(sub: PushSubscription) -> None:
    """Add or replace a subscription, deduping on endpoint."""
    store = get_subscription_store()
    subs = store.load()
    subs = [s for s in subs if s.endpoint != sub.endpoint]
    subs.append(sub)
    store.save(subs)
    log.info("push.subscribed", endpoint_host=_endpoint_host(sub.endpoint))


def remove_subscription(endpoint: str) -> bool:
    """Drop any subscription with the given endpoint. True if anything removed."""
    store = get_subscription_store()
    subs = store.load()
    new = [s for s in subs if s.endpoint != endpoint]
    if len(new) == len(subs):
        return False
    store.save(new)
    log.info("push.unsubscribed", endpoint_host=_endpoint_host(endpoint))
    return True


def list_subscriptions() -> list[PushSubscription]:
    return get_subscription_store().load()


# --- Send -----------------------------------------------------------------


class PushSendError(RuntimeError):
    """Raised on transient send failures (network, push service 5xx)."""


class PushSubscriptionExpired(RuntimeError):
    """Raised when the push service returns 404/410 — subscription is dead."""


def send_push(
    sub: PushSubscription,
    payload: dict[str, Any],
    *,
    ttl_seconds: int = 60 * 60,
    settings: Settings | None = None,
) -> None:
    """Send one push. Returns None on success.

    Raises :class:`PushSubscriptionExpired` so the caller can prune the dead
    subscription, or :class:`PushSendError` for transient problems.
    """
    s = settings or get_settings()
    private = s.vapid_private_key.get_secret_value()
    if not private:
        raise PushSendError("VAPID_PRIVATE_KEY is not configured")

    from pywebpush import WebPushException, webpush  # noqa: PLC0415

    body = json.dumps(payload)
    try:
        webpush(
            subscription_info=sub.to_pywebpush(),
            data=body,
            vapid_private_key=private,
            vapid_claims={"sub": s.vapid_subject},
            ttl=ttl_seconds,
        )
    except WebPushException as e:
        resp = getattr(e, "response", None)
        status = getattr(resp, "status_code", None)
        if status in (404, 410):
            log.info(
                "push.expired",
                endpoint_host=_endpoint_host(sub.endpoint),
                status=status,
            )
            raise PushSubscriptionExpired(str(e)) from e
        log.warning(
            "push.send_failed",
            endpoint_host=_endpoint_host(sub.endpoint),
            status=status,
            error=str(e),
        )
        raise PushSendError(str(e)) from e


def broadcast(payload: dict[str, Any]) -> dict[str, int]:
    """Send the same payload to every subscription, pruning dead ones.

    Returns a dict of ``{sent, expired, failed}`` for logging.
    """
    store = get_subscription_store()
    subs = store.load()
    sent = expired = failed = 0
    live: list[PushSubscription] = []
    for sub in subs:
        try:
            send_push(sub, payload)
            sent += 1
            live.append(sub)
        except PushSubscriptionExpired:
            expired += 1
            # don't keep it
        except PushSendError:
            failed += 1
            live.append(sub)  # keep — might be a transient blip
    if expired:
        store.save(live)
    return {"sent": sent, "expired": expired, "failed": failed}


# --- Internals -------------------------------------------------------------


def _endpoint_host(endpoint: str) -> str:
    """Strip the path so we don't log full endpoint URLs (privacy)."""
    try:
        from urllib.parse import urlparse

        return urlparse(endpoint).netloc
    except Exception:
        return "unknown"
