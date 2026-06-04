"""Streak computation — shared between the dashboard endpoint and the
scheduled-push worker.

A "streak" is the number of consecutive days, counting back from today,
on which the user marked at least one row Done. Today must have a Done
to start the count (so the streak only counts when you've actually shipped
something today).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ._tz import LOCAL_TZ


def compute_streak(wins_rows: list[Any], *, max_days: int = 30) -> int:
    """Compute the consecutive-Done-day streak from a list of TaskRow.

    ``wins_rows`` is the output of ``NotionClient.query_done_since``. Each
    row's ``done_at`` is grouped by local-tz date; the function then walks
    backwards from today and counts unbroken days.
    """
    if not wins_rows:
        return 0
    days_with_wins: set[str] = set()
    for row in wins_rows:
        ts = getattr(row, "done_at", None)
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            local = dt.astimezone(LOCAL_TZ).date()
            days_with_wins.add(local.isoformat())
        except (ValueError, AttributeError):
            continue
    today = datetime.now(LOCAL_TZ).date()
    streak = 0
    for i in range(max_days):
        d = (today - timedelta(days=i)).isoformat()
        if d in days_with_wins:
            streak += 1
        else:
            break
    return streak


# Milestone push levels — per PROJECT_STATUS N4 (milestones only, no daily).
STREAK_MILESTONES = [7, 14, 30]


def next_milestone_above(streak: int, last_fired: int) -> int | None:
    """Return the next streak milestone reached but not yet celebrated.

    Returns the milestone level (e.g. 7) or ``None`` if no new milestone.
    Picks the highest applicable level so a fresh user hitting 14 from
    a stale 0-state lights up at 14, not 7.
    """
    for level in reversed(STREAK_MILESTONES):
        if streak >= level > last_fired:
            return level
    return None
