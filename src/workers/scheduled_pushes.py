"""Time-of-day scheduled push triggers.

Three event types, all delivered via Web Push (with action buttons) so the
user can act from the lock screen:

- **Mon 9am work-on** — "Morning · N work things for today" with [View] +
  [Pause today] action buttons. Only fires if there's at least one work-
  context Active row.
- **Sun 6pm review nudge** — "N items need a date" with [Open Review].
  Only fires if /api/review or /api/needs-date has anything.
- **Monthly Parked resurface** — first Sunday of the month at 11am, only
  if ≥5 Parked items exist.

Each event has its own dedup key in the state store so re-runs within the
window (the nag worker fires every 5 min) don't spam.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .._tz import LOCAL_TZ
from ..integrations import push as push_mod
from ..integrations.notion_client import NotionClient
from ..state_backend import StateStore, S3Store, FileStore
from ..streak import compute_streak, next_milestone_above
from ..utils.logging import get_logger
from .. import work_mode

log = get_logger(__name__)

# Reuse the same S3 bucket as nag_state but a separate key so the nag worker's
# "prune stale" logic can't accidentally drop our scheduled-push entries.
SCHEDULED_PUSH_KEY = "scheduled_push_state.json"


def _scheduled_store() -> StateStore:
    bucket = os.environ.get("NAG_STATE_BUCKET")
    if bucket:
        return S3Store(bucket=bucket, key=SCHEDULED_PUSH_KEY)
    from pathlib import Path
    project_root = Path(__file__).resolve().parents[2]
    return FileStore(project_root / "state" / SCHEDULED_PUSH_KEY)


def _streak_body(milestone: int) -> str:
    """Short celebratory body matched to the milestone level."""
    if milestone >= 30:
        return "A month of shipping every day. That's a habit now."
    if milestone >= 14:
        return "Two weeks unbroken — you're building something real."
    return "One week of consistent wins. Good rhythm."


def _first_sunday_of_month(d: date) -> date:
    """The first Sunday on/after the 1st of ``d``'s month."""
    first = d.replace(day=1)
    # weekday(): Mon=0..Sun=6
    return first + timedelta(days=(6 - first.weekday()) % 7)


class ScheduledPushes:
    """One instance per worker process. Stateful via ``state_store``.

    State shape (JSON map):

        {
            "mon_morning": "2026-06-01",        # last date fired (local)
            "sun_review":  "2026-06-07",
            "monthly_parked": "2026-06"          # last month fired (YYYY-MM)
        }
    """

    def __init__(self, notion: NotionClient | None = None) -> None:
        self.notion = notion or NotionClient()
        self.store: StateStore = _scheduled_store()
        try:
            self.state: dict[str, str] = self.store.load() or {}
        except Exception:
            self.state = {}

    async def check_and_fire_all(self, *, now: datetime | None = None) -> dict[str, bool]:
        """Run every scheduled-push check. Return ``{event_name: fired}``."""
        now_local = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
        results: dict[str, bool] = {
            "mon_morning": await self._maybe_monday_morning(now_local),
            "sun_review": await self._maybe_sunday_review(now_local),
            "monthly_parked": await self._maybe_monthly_parked(now_local),
            "streak_milestone": await self._maybe_streak_milestone(now_local),
        }
        if any(results.values()):
            self._save_state()
        return results

    # --- Mon 9am work-on -------------------------------------------------

    async def _maybe_monday_morning(self, now_local: datetime) -> bool:
        # Monday is weekday 0. Trigger window: 09:00 ≤ t < 10:00.
        if now_local.weekday() != 0 or now_local.hour != 9:
            return False
        today_iso = now_local.date().isoformat()
        if self.state.get("mon_morning") == today_iso:
            return False  # already fired this Monday

        # D6: surface ALL active work-context rows here (not just today-due)
        # so weekend captures don't get lost. The nag worker silences work
        # rows over the weekend, so this is the user's first sight of them.
        try:
            rows = await self.notion.query_all_active_tasks()
        except Exception as e:
            log.warning("scheduled.monday_query_failed", error=str(e))
            return False
        work_rows = [r for r in rows if r.context == "work"]
        if not work_rows:
            log.info("scheduled.monday_skip_no_work_rows")
            self.state["mon_morning"] = today_iso  # don't retry today
            return False

        n = len(work_rows)
        payload = {
            "title": f"💼 Morning · {n} work thing{'s' if n != 1 else ''} for today",
            "body": ", ".join(r.title for r in work_rows[:3])
            + (f" + {n - 3} more" if n > 3 else ""),
            "tag": f"mon-morning-{today_iso}",
            "url": "/pwa-v2/?focus=work",
            "actions": [
                {"action": "view", "title": "View", "url": "/pwa-v2/?focus=work"},
                {
                    "action": "pause-work",
                    "title": "Pause today",
                    "url": "/pwa-v2/?action=pause-work",
                },
            ],
        }
        result = push_mod.broadcast(payload)
        log.info("scheduled.monday_pushed", count=n, **result)
        self.state["mon_morning"] = today_iso
        return True

    # --- Sun 6pm review nudge --------------------------------------------

    async def _maybe_sunday_review(self, now_local: datetime) -> bool:
        # Sunday is weekday 6. Trigger window: 18:00 ≤ t < 19:00.
        if now_local.weekday() != 6 or now_local.hour != 18:
            return False
        today_iso = now_local.date().isoformat()
        if self.state.get("sun_review") == today_iso:
            return False

        # Combine review + needs-date counts
        try:
            review = await self.notion.query_review_queue()
            needs = await self.notion.query_needs_date()
        except Exception as e:
            log.warning("scheduled.sunday_query_failed", error=str(e))
            return False
        total = len(review) + len(needs)
        if total == 0:
            log.info("scheduled.sunday_skip_empty")
            self.state["sun_review"] = today_iso
            return False

        bits = []
        if needs:
            bits.append(f"{len(needs)} need a date")
        if review:
            bits.append(f"{len(review)} flagged")

        payload = {
            "title": f"✦ Week reset · {total} item{'s' if total != 1 else ''} to triage",
            "body": " · ".join(bits),
            "tag": f"sun-review-{today_iso}",
            "url": "/pwa-v2/#/review",
            "actions": [
                {"action": "open-review", "title": "Open Review", "url": "/pwa-v2/#/review"},
            ],
        }
        result = push_mod.broadcast(payload)
        log.info("scheduled.sunday_pushed", review=len(review), needs_date=len(needs), **result)
        self.state["sun_review"] = today_iso
        return True

    # --- Monthly Parked resurface (1st Sunday, 11am) ---------------------

    async def _maybe_monthly_parked(self, now_local: datetime) -> bool:
        today = now_local.date()
        if today != _first_sunday_of_month(today):
            return False
        if now_local.hour != 11:
            return False
        month_key = today.strftime("%Y-%m")
        if self.state.get("monthly_parked") == month_key:
            return False

        try:
            parked = await self.notion.query_parked()
        except Exception as e:
            log.warning("scheduled.parked_query_failed", error=str(e))
            return False

        if len(parked) < 5:
            log.info("scheduled.parked_skip_below_threshold", count=len(parked))
            self.state["monthly_parked"] = month_key
            return False

        oldest_age_days = 0
        for r in parked:
            if r.captured_at:
                try:
                    captured = datetime.fromisoformat(r.captured_at.replace("Z", "+00:00"))
                    oldest_age_days = max(
                        oldest_age_days,
                        (datetime.now(LOCAL_TZ) - captured.astimezone(LOCAL_TZ)).days,
                    )
                except Exception:
                    pass

        payload = {
            "title": f"📦 {len(parked)} parked items · time to revisit?",
            "body": (
                f"Oldest is {oldest_age_days // 30}mo old."
                if oldest_age_days >= 30
                else f"Some have been parked a while."
            ),
            "tag": f"monthly-parked-{month_key}",
            "url": "/pwa-v2/#/parked",
            "actions": [
                {"action": "open-parked", "title": "Open Parked", "url": "/pwa-v2/#/parked"},
            ],
        }
        result = push_mod.broadcast(payload)
        log.info("scheduled.parked_pushed", count=len(parked), **result)
        self.state["monthly_parked"] = month_key
        return True

    # --- Streak milestone (7 / 14 / 30) ----------------------------------

    async def _maybe_streak_milestone(self, now_local: datetime) -> bool:
        # Fire at 19:00 local (after the user has had time to ship the day's
        # last task). Any day of the week.
        if now_local.hour != 19:
            return False
        today_iso = now_local.date().isoformat()
        if self.state.get("streak_check_date") == today_iso:
            return False  # already evaluated streak today

        try:
            today = now_local.date()
            wins = await self.notion.query_done_since(today - timedelta(days=29))
        except Exception as e:
            log.warning("scheduled.streak_query_failed", error=str(e))
            return False

        streak = compute_streak(wins)
        last_fired = int(self.state.get("streak_last_fired", "0") or "0")

        # If streak broke (back to 0), reset so future streaks can fire again.
        if streak == 0:
            self.state["streak_last_fired"] = "0"
            self.state["streak_check_date"] = today_iso
            return False

        milestone = next_milestone_above(streak, last_fired)
        if milestone is None:
            self.state["streak_check_date"] = today_iso
            return False

        payload = {
            "title": f"🔥 {milestone}-day streak",
            "body": _streak_body(milestone),
            "tag": f"streak-{milestone}-{today_iso}",
            "url": "/pwa-v2/",
        }
        result = push_mod.broadcast(payload)
        log.info("scheduled.streak_pushed", milestone=milestone, streak=streak, **result)
        self.state["streak_last_fired"] = str(milestone)
        self.state["streak_check_date"] = today_iso
        return True

    # --- Persistence -----------------------------------------------------

    def _save_state(self) -> None:
        try:
            self.store.save(self.state)
        except Exception as e:
            log.warning("scheduled.state_save_failed", error=str(e))
