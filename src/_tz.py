"""Single source of truth for the user's local timezone.

Set the ``PA_LOCAL_TZ`` env var (or SSM parameter ``pa-local-tz``) to a
valid IANA TZ identifier (e.g. ``Australia/Perth``, ``Europe/London``,
``America/New_York``). Falls back silently to the default if the value
is missing or invalid.

This module is imported by every other module that needs a wall-clock
TZ — work_mode, scheduled_pushes, notion_client, streak, main,
orchestrator — so a single config change rotates the whole app to a
new TZ without code edits.
"""

from __future__ import annotations

import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Default tuned for the current user (Perth). Override via PA_LOCAL_TZ.
_DEFAULT = "Australia/Perth"
_TZ_NAME = os.environ.get("PA_LOCAL_TZ", _DEFAULT).strip() or _DEFAULT

try:
    LOCAL_TZ = ZoneInfo(_TZ_NAME)
except (ZoneInfoNotFoundError, ValueError):
    # Bad config — don't crash the worker, fall back silently. The next
    # log line emitted by any caller will at least show the wrong-clock
    # behaviour, signaling something is off.
    LOCAL_TZ = ZoneInfo(_DEFAULT)


def tz_name() -> str:
    """Return the resolved IANA TZ name (for /api/work-mode reporting)."""
    return str(LOCAL_TZ)
