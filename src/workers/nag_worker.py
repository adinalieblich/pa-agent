"""Nag worker — polls Notion for overdue/urgent rows and pushes via ntfy.sh.

Behaviour:

1. Every ``settings.nag_poll_interval_seconds`` (default 5 min), query the
   Tasks DB for rows where:
     * Status = Active AND Due <= today, OR
     * Status = Active AND Priority = Urgent AND no due date.
2. For each matching row, send a push notification — UNLESS the same row was
   already notified within ``settings.nag_reping_interval_seconds`` (default
   15 min). This prevents spam.
3. Persist the per-row last-notified timestamp to ``state/nag_state.json`` so
   restarts don't re-ping everything immediately.
4. When a row's Status changes to Done (next poll), its state entry is removed
   so the cycle is clean for the next time the row goes Active.

Designed to run as an asyncio background task started by the FastAPI
lifespan in ``src.main``. The worker NEVER raises out of its loop — any
failure logs and the next iteration retries.

Why ntfy.sh vs APNs directly: free, no Apple Developer account, no certs,
single HTTP POST. The topic name is the only auth — keep it secret.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any

from ..config import Settings, get_settings
from ..integrations.notion_client import NotionClient
from ..integrations.ntfy import Ntfy
from ..integrations import push as push_mod
from ..models import TaskRow
from ..state_backend import StateStore, get_state_store
from ..utils.logging import get_logger
from .. import work_mode
from .scheduled_pushes import ScheduledPushes

log = get_logger(__name__)


# --- State persistence -----------------------------------------------------
#
# Persistence is delegated to a pluggable backend (local file by default, S3
# in Lambda — selected via env var). See ``src/state_backend.py``.


def _load_state(store: StateStore) -> dict[str, str]:
    """Load ``page_id → last_notified_at`` map from the backend."""
    try:
        raw = store.load()
    except Exception as e:
        log.warning("nag.state_unreadable", error=str(e))
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}


def _save_state(store: StateStore, state: dict[str, str]) -> None:
    """Write the state map via the backend."""
    try:
        store.save(state)
    except Exception as e:
        # Don't crash the loop on a persistence hiccup — next tick retries.
        log.warning("nag.state_save_failed", error=str(e))


# --- Push composition ------------------------------------------------------


def _row_to_push(row: TaskRow) -> tuple[str, str, int, list[str]]:
    """Build (title, body, priority, tags) for a single row's notification.

    Priority mapping:
      - Urgent → ntfy priority 5 (max)
      - Important → 4
      - Bills with overdue → 5 (money lateness is expensive)
      - Everything else → 3
    Tags become emoji prefixes on the lock screen.
    """
    today = datetime.now(timezone.utc).date()
    overdue = row.due_date is not None and row.due_date < today

    if row.type == "bill":
        prefix = "💸"
        tags = ["money_bag"]
    else:
        prefix = "⚠️" if overdue else "▶️"
        tags = ["warning"] if overdue else ["arrow_forward"]

    if row.priority == "Urgent":
        priority = 5
    elif row.priority == "Important":
        priority = 4
    elif overdue and row.type == "bill":
        priority = 5
    else:
        priority = 3

    title = f"{prefix} {row.title}"
    parts: list[str] = []
    if row.priority and row.priority != "Normal":
        parts.append(row.priority)
    if row.due_date:
        if overdue:
            delta = (today - row.due_date).days
            parts.append(f"{delta}d overdue" if delta > 0 else "due today")
        else:
            parts.append(f"due {row.due_date.isoformat()}")
    if row.type == "bill" and row.amount is not None:
        parts.append(f"${row.amount:.2f}")
    if row.first_step:
        parts.append(f"→ {row.first_step}")
    body = " · ".join(parts) or "no details"
    return title, body, priority, tags


def _row_to_webpush_payload(row: TaskRow) -> dict:
    """Build the Web Push payload — same content as ntfy + action buttons.

    Action buttons land the user on a deep link the PWA owns; the PWA
    itself runs the API call. This avoids putting the X-PA-Token into the
    service worker.
    """
    title, body, _, _ = _row_to_push(row)
    # The service worker focuses an open PWA window if any; otherwise
    # opens fresh at the URL below.
    actions = [
        {
            "action": "done",
            "title": "Done",
            "url": f"/pwa-v2/?action=done&id={row.id}",
        },
        {
            "action": "snooze-1",
            "title": "+1 day",
            "url": f"/pwa-v2/?action=snooze&id={row.id}&days=1",
        },
    ]
    return {
        "title": title,
        "body": body,
        "tag": f"task-{row.id}",
        "url": row.url or f"/pwa-v2/?id={row.id}",
        "actions": actions,
    }


# --- Core loop -------------------------------------------------------------


class NagWorker:
    """One-instance-per-process. Started by FastAPI lifespan."""

    def __init__(
        self,
        settings: Settings | None = None,
        notion: NotionClient | None = None,
        ntfy: Ntfy | None = None,
        store: StateStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.notion = notion or NotionClient(self.settings)
        self.ntfy = ntfy or Ntfy(self.settings)
        self.store: StateStore = store or get_state_store()
        self._stopping = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.state: dict[str, str] = _load_state(self.store)
        # Scheduled-push checker (Mon morning, Sun review, monthly Parked).
        # Cheap to instantiate — only fires when its time-of-day matches.
        self.scheduled = ScheduledPushes(notion=self.notion)
        # Web Push is preferred when VAPID keys are configured. ntfy stays
        # as the safety net so the user always gets *something* until they
        # finish the Web Push enrolment on their device.
        self._webpush_configured = bool(
            self.settings.vapid_private_key.get_secret_value()
            and self.settings.vapid_public_key
        )

    # --- Lifecycle ------------------------------------------------------

    def start(self) -> None:
        """Spawn the background loop. Idempotent."""
        if not self.ntfy.enabled and not self._webpush_configured:
            log.warning("nag.disabled_no_push_channel")
            return
        if self._task and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run_forever(), name="nag_worker")
        log.info(
            "nag.started",
            poll_interval=self.settings.nag_poll_interval_seconds,
            reping_interval=self.settings.nag_reping_interval_seconds,
        )

    async def stop(self) -> None:
        """Signal the loop to exit and wait for it. Idempotent."""
        self._stopping.set()
        if self._task and not self._task.done():
            await self._task
        await self.ntfy.aclose()
        log.info("nag.stopped")

    # --- Internals ------------------------------------------------------

    async def _run_forever(self) -> None:
        """Top-level loop. Never raises — logs and continues on any error."""
        # First tick happens immediately so the user gets a fast signal that
        # the worker is alive without waiting 5 minutes after a restart.
        await self._tick_safely()
        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=self.settings.nag_poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass  # normal — poll interval elapsed
            if self._stopping.is_set():
                break
            await self._tick_safely()

    async def _tick_safely(self) -> None:
        try:
            await self._tick()
        except Exception as e:  # last-ditch — never crash the loop
            log.exception("nag.tick_unhandled", error=str(e))

    async def _tick(self) -> None:
        """One poll cycle.

        Two gating layers run before we even look at rows:

        1. **Quiet hours** (22:00–06:00 local) — skip the whole tick. Nag
           state still gets recomputed for staleness but we send nothing.
        2. **Work mode** — work-context rows are skipped when work mode is
           OFF (off-hours/weekends, unless override). Personal rows are
           always candidates.
        """
        # Quiet hours: short-circuit. Don't even pull rows — saves API quota.
        if work_mode.is_quiet_hours():
            log.info("nag.tick_quiet_hours_skip")
            return

        override = work_mode.get_override()
        work_mode_on = work_mode.is_work_mode_active(override=override)

        rows = await self.notion.query_today_focus()
        now_iso = datetime.now(timezone.utc).isoformat()
        reping_floor = self._now_minus_reping()

        # Drop state entries for rows that no longer appear in today_focus
        # (they were marked Done, snoozed past today, cancelled, etc.).
        active_ids = {r.id for r in rows if r.id}
        stale = [k for k in self.state if k not in active_ids]
        for k in stale:
            self.state.pop(k, None)

        notified = 0
        skipped_recent = 0
        skipped_work_mode = 0
        for row in rows:
            if not row.id:
                continue
            # Work-mode filter: skip work-context rows when work mode is OFF.
            if row.context == "work" and not work_mode_on:
                skipped_work_mode += 1
                continue
            last = self.state.get(row.id)
            if last and last >= reping_floor:
                skipped_recent += 1
                continue
            ok = await self._send_row(row)
            if ok:
                self.state[row.id] = now_iso
                notified += 1

        if stale or notified:
            _save_state(self.store, self.state)

        # Time-of-day scheduled pushes (Mon 9am · Sun 6pm · monthly Parked).
        # Each one's own dedup ensures we don't double-fire within its window.
        try:
            await self.scheduled.check_and_fire_all()
        except Exception as e:
            log.warning("nag.scheduled_failed", error=str(e))

        log.info(
            "nag.tick",
            candidates=len(rows),
            notified=notified,
            skipped_recent=skipped_recent,
            skipped_work_mode=skipped_work_mode,
            dropped_stale=len(stale),
            work_mode_on=work_mode_on,
        )

    async def _send_row(self, row: TaskRow) -> bool:
        """Send one row's notification — Web Push primary, ntfy as fallback.

        Logic:
          1. If Web Push is configured AND delivered to ≥1 subscription →
             we're done. Don't double-ping via ntfy.
          2. If Web Push isn't configured OR delivered to 0 subscriptions
             (no devices enrolled, all expired, service blip) → fall through
             to ntfy so the user still gets *something*.

        Returns True if EITHER channel reported a successful send so the
        dedup state still updates.
        """
        title, body, priority, tags = _row_to_push(row)

        webpush_sent = 0
        if self._webpush_configured:
            try:
                payload = _row_to_webpush_payload(row)
                # `broadcast` is sync (boto3 + pywebpush) — run it on a
                # thread so we don't block the asyncio loop.
                result = await asyncio.to_thread(push_mod.broadcast, payload)
                webpush_sent = int(result.get("sent", 0))
            except Exception as e:
                log.warning("nag.webpush_failed", row_id=row.id, error=str(e))

        # Web Push delivered? Stop here — no need to double-ping.
        if webpush_sent > 0:
            return True

        # Otherwise, fall back to ntfy as a safety net.
        if self.ntfy.enabled:
            return await self.ntfy.send(
                title=title,
                body=body,
                priority=priority,
                click_url=row.url,
                tags=tags,
            )

        return False

    def _now_minus_reping(self) -> str:
        """ISO timestamp ``reping_interval`` ago — anything older is fair game."""
        from datetime import timedelta

        floor = datetime.now(timezone.utc) - timedelta(
            seconds=self.settings.nag_reping_interval_seconds
        )
        return floor.isoformat()
