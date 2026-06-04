"""Thin async client for ntfy.sh push notifications.

ntfy.sh is a stateless HTTP-based push relay. You POST to ``/{topic}`` and any
device subscribed to that topic on the official ntfy app receives a push
notification through Apple's APNs / Google's FCM. There is no account or
auth — the topic name *is* the shared secret. PA-Agent generates a 32-char
random topic at install time.

This module deliberately swallows network errors and logs them rather than
raising: a transient push failure must never crash the nag worker loop.
The next poll will retry the row anyway.

See: https://docs.ntfy.sh/publish/
"""

from __future__ import annotations

from typing import Iterable

import httpx

from ..config import Settings, get_settings
from ..utils.logging import get_logger

log = get_logger(__name__)


class Ntfy:
    """Async wrapper around ntfy.sh's HTTP publish API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        # Reuse one httpx client across calls for connection pooling.
        self._client = httpx.AsyncClient(timeout=10.0)

    @property
    def enabled(self) -> bool:
        """Whether pushes are configured (topic set + non-empty)."""
        return bool(self.settings.ntfy_topic.strip())

    async def aclose(self) -> None:
        """Close the underlying httpx client. Called on app shutdown."""
        await self._client.aclose()

    async def send(
        self,
        *,
        title: str,
        body: str,
        priority: int = 3,
        click_url: str | None = None,
        tags: Iterable[str] = (),
    ) -> bool:
        """Push one notification. Returns True on success, False on failure.

        Args:
            title: Notification title (lock-screen headline). UTF-8 OK.
            body: Notification body (one-line summary). UTF-8 OK.
            priority: 1 (min) .. 5 (max urgent). Default 3 = normal.
            click_url: URL the notification opens when tapped — typically
                the Notion page URL so one tap takes the user to the row.
            tags: ntfy "tags" → emoji prefix on the notification. E.g.
                ``["warning"]`` prepends ⚠️. See ntfy emoji-tag list.

        Uses ntfy's JSON-publish endpoint (POST to ``/`` with a JSON body)
        rather than the HTTP-header style — the header style only accepts
        ASCII, which breaks for Unicode titles. The JSON endpoint is
        UTF-8-native.
        """
        if not self.enabled:
            log.debug("ntfy.disabled")
            return False

        base = self.settings.ntfy_base_url.rstrip("/")
        payload: dict[str, object] = {
            "topic": self.settings.ntfy_topic,
            "title": title[:250],
            "message": body[:4000],
            "priority": priority,
            "tags": list(tags),
        }
        if click_url:
            payload["click"] = click_url

        try:
            resp = await self._client.post(f"{base}/", json=payload)
            if resp.status_code >= 400:
                log.error(
                    "ntfy.publish_http_error",
                    status=resp.status_code,
                    body=resp.text[:200],
                )
                return False
        except httpx.HTTPError as e:
            log.error("ntfy.publish_failed", error=str(e))
            return False

        log.info(
            "ntfy.publish_ok",
            title=title[:80],
            priority=priority,
            tags=list(tags),
        )
        return True
