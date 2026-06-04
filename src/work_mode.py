"""Work-mode predicate and override state.

Work mode is ON during Mon–Fri 09:00–17:00 local time. Outside those hours
(plus weekends), tasks tagged ``context=work`` are hidden from the user's
view and the nag worker skips them — the user explicitly does NOT want work
bleeding into evenings.

Two layers:

1. **Schedule** — :func:`is_within_work_hours` is the pure time-of-day check.
2. **Override** — :func:`get_override` returns any user-set override that
   should win over the schedule. Overrides have a TTL so they can't accidentally
   stay on forever.

Quiet hours (22:00–06:00 every day, all contexts) are enforced by
:func:`is_quiet_hours`. The nag worker checks this before sending anything.

Override storage:

- In Lambda → SSM Parameter Store key (env var ``WORK_OVERRIDE_SSM_PARAM``)
- Locally   → JSON file at ``state/work_override.json``
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from ._tz import LOCAL_TZ
from .utils.logging import get_logger

log = get_logger(__name__)


# --- Constants --------------------------------------------------------------

# Work-hours window. End-exclusive — 17:00 itself is OFF.
WORK_START = time(9, 0)
WORK_END = time(17, 0)

# Quiet-hours window — no pings between these, all contexts.
# Window wraps midnight: [22:00, 24:00) ∪ [00:00, 06:00).
QUIET_START = time(22, 0)
QUIET_END = time(6, 0)

# How long a "start now" override stays on if the caller doesn't specify a TTL.
# 4 hours is short enough that you won't forget it's running.
DEFAULT_START_NOW_TTL_HOURS = 4

OverrideMode = Literal["work", "personal"]


# --- Override record --------------------------------------------------------


@dataclass
class Override:
    """A user-set override that forces work mode on/off until ``until``."""

    mode: OverrideMode  # what to force: "work" forces ON, "personal" forces OFF
    until: datetime    # UTC. When now > until the override is ignored.
    set_at: datetime   # UTC. Audit only.
    reason: str = ""   # free-text label e.g. "pause-today", "holiday", "start-now"

    def to_dict(self) -> dict[str, str]:
        return {
            "mode": self.mode,
            "until": self.until.astimezone(timezone.utc).isoformat(),
            "set_at": self.set_at.astimezone(timezone.utc).isoformat(),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Override | None":
        try:
            mode = raw["mode"]
            if mode not in ("work", "personal"):
                return None
            return cls(
                mode=mode,
                until=datetime.fromisoformat(raw["until"]),
                set_at=datetime.fromisoformat(raw["set_at"]),
                reason=str(raw.get("reason", "")),
            )
        except (KeyError, ValueError, TypeError):
            return None

    def is_active(self, now: datetime | None = None) -> bool:
        """True if the override hasn't expired yet."""
        now = now or datetime.now(timezone.utc)
        return now.astimezone(timezone.utc) < self.until.astimezone(timezone.utc)


# --- Schedule predicates ----------------------------------------------------


def is_within_work_hours(now: datetime | None = None) -> bool:
    """True if ``now`` is Mon–Fri 09:00–17:00 local time."""
    local = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
    # weekday(): Mon=0..Sun=6
    if local.weekday() >= 5:  # Sat or Sun
        return False
    return WORK_START <= local.time() < WORK_END


def is_quiet_hours(now: datetime | None = None) -> bool:
    """True if ``now`` is between 22:00 and 06:00 local time.

    The window wraps midnight, so we handle the two halves separately.
    """
    local_time = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ).time()
    return local_time >= QUIET_START or local_time < QUIET_END


# --- Effective state --------------------------------------------------------


def is_work_mode_active(
    now: datetime | None = None, override: Override | None = None
) -> bool:
    """The single question every caller asks: "are work tasks visible now?"

    Order:
      1. If a non-expired override exists → it wins.
      2. Otherwise fall back to the schedule (work hours = ON).
    """
    now_local = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
    if override is not None and override.is_active(now_local):
        return override.mode == "work"
    return is_within_work_hours(now_local)


# --- Override storage -------------------------------------------------------


class OverrideStore(Protocol):
    """Minimal interface every backend implements."""

    def load(self) -> Override | None: ...
    def save(self, override: Override | None) -> None: ...


class FileOverrideStore:
    """Local JSON file backend. Used in dev."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Override | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(raw, dict) or not raw:
            return None
        return Override.from_dict(raw)

    def save(self, override: Override | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if override is None:
            # "Clear override" — write empty object so the file still exists
            # (some tools dislike a missing file).
            self.path.write_text("{}", encoding="utf-8")
            return
        self.path.write_text(
            json.dumps(override.to_dict(), indent=2), encoding="utf-8"
        )


class SSMOverrideStore:
    """SSM Parameter Store backend. Used in Lambda.

    The parameter value is the JSON-encoded :class:`Override` dict; an empty
    object (``{}``) or absent parameter means "no override".
    """

    def __init__(self, param_name: str) -> None:
        import boto3  # noqa: PLC0415 — lazy import (only needed in Lambda)

        self.param_name = param_name
        self._ssm = boto3.client("ssm")

    def load(self) -> Override | None:
        try:
            resp = self._ssm.get_parameter(
                Name=self.param_name, WithDecryption=True
            )
        except self._ssm.exceptions.ParameterNotFound:
            return None
        except Exception as e:
            # Network/IAM hiccup — degrade to no override. Better than failing
            # the whole nag tick.
            log.warning("work_mode.ssm_load_failed", error=str(e))
            return None
        try:
            raw = json.loads(resp["Parameter"]["Value"])
        except Exception:
            return None
        if not isinstance(raw, dict) or not raw:
            return None
        return Override.from_dict(raw)

    def save(self, override: Override | None) -> None:
        value = json.dumps(override.to_dict()) if override is not None else "{}"
        try:
            self._ssm.put_parameter(
                Name=self.param_name,
                Value=value,
                Type="String",
                Overwrite=True,
            )
        except Exception as e:
            log.error("work_mode.ssm_save_failed", error=str(e))
            raise


_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_override_store() -> OverrideStore:
    """Pick the backend based on the environment.

    SSM wins if ``WORK_OVERRIDE_SSM_PARAM`` is set; otherwise fall back to a
    local JSON file at ``<repo>/state/work_override.json``.
    """
    param_name = os.environ.get("WORK_OVERRIDE_SSM_PARAM")
    if param_name:
        return SSMOverrideStore(param_name=param_name)
    return FileOverrideStore(_PROJECT_ROOT / "state" / "work_override.json")


# --- High-level helpers used by API + worker --------------------------------


def get_override() -> Override | None:
    """Load the current override, dropping it if it has expired.

    Side-effect: if an expired override is found, it's cleared from the store
    so the next read is fast.
    """
    store = get_override_store()
    override = store.load()
    if override is None:
        return None
    if not override.is_active():
        log.info("work_mode.override_expired", reason=override.reason)
        store.save(None)
        return None
    return override


def set_override(
    mode: OverrideMode, *, reason: str, ttl_hours: float
) -> Override:
    """Persist a new override. Replaces any existing one.

    ``ttl_hours`` is required so we never silently set an indefinite override.
    """
    if ttl_hours <= 0:
        raise ValueError("ttl_hours must be > 0")
    now = datetime.now(timezone.utc)
    override = Override(
        mode=mode,
        until=now + timedelta(hours=ttl_hours),
        set_at=now,
        reason=reason,
    )
    get_override_store().save(override)
    log.info(
        "work_mode.override_set",
        mode=mode,
        ttl_hours=ttl_hours,
        reason=reason,
        until=override.until.isoformat(),
    )
    return override


def clear_override() -> None:
    """Drop any override so the schedule resumes."""
    get_override_store().save(None)
    log.info("work_mode.override_cleared")


# Pre-canned override shortcuts the PWA buttons map to. ------------------


def pause_today() -> Override:
    """Force work mode OFF until end-of-day local. Used from the work-mode pill."""
    local_now = datetime.now(LOCAL_TZ)
    end_of_day_local = local_now.replace(
        hour=23, minute=59, second=59, microsecond=0
    )
    hours = max(0.1, (end_of_day_local - local_now).total_seconds() / 3600)
    return set_override("personal", reason="pause-today", ttl_hours=hours)


def start_work_now(hours: float = DEFAULT_START_NOW_TTL_HOURS) -> Override:
    """Force work mode ON for the next ``hours`` hours."""
    return set_override("work", reason="start-now", ttl_hours=hours)


def end_work_early() -> Override:
    """Force work mode OFF until tomorrow morning's work-start time."""
    local_now = datetime.now(LOCAL_TZ)
    # Find the next work-start: tomorrow 9am if today is a weekday, else
    # the next Monday 9am.
    next_day = local_now.date() + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day = next_day + timedelta(days=1)
    next_work_start = datetime.combine(next_day, WORK_START, tzinfo=LOCAL_TZ)
    hours = max(0.1, (next_work_start - local_now).total_seconds() / 3600)
    return set_override("personal", reason="end-early", ttl_hours=hours)


def holiday_until(date_inclusive_end_iso: str) -> Override:
    """Force OFF for a multi-day range, ending at 23:59 local on the given date."""
    end_date = datetime.fromisoformat(date_inclusive_end_iso[:10]).date()
    end_dt = datetime.combine(
        end_date, time(23, 59, 59), tzinfo=LOCAL_TZ
    )
    local_now = datetime.now(LOCAL_TZ)
    hours = max(0.1, (end_dt - local_now).total_seconds() / 3600)
    return set_override(
        "personal",
        reason=f"holiday-until-{end_date.isoformat()}",
        ttl_hours=hours,
    )
