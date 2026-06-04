"""FastAPI entry point — webhook + PWA API + PWA static-file serving.

Endpoints, in three groups:

**Capture (used by the iOS Shortcut)**
- ``GET  /health`` — unauth'd liveness probe.
- ``POST /capture`` — voice text → orchestrator → Notion. ``X-PA-Token`` gated.

**PWA API (used by the in-browser PWA)**
- ``GET  /api/today``     — today's focus list
- ``GET  /api/wins``      — items marked Done today
- ``GET  /api/review``    — items tagged ``review``
- ``GET  /api/quickwins`` — items tagged ``quick-win``
- ``POST /api/task/{id}/done``    — mark a single row Done
- ``POST /api/task/{id}/snooze``  — push due date by 1 day (or ?days=N)
- All gated by ``X-PA-Token``.

**PWA static**
- ``GET /pwa/...`` — serves ``./pwa/*`` files; ``index.html`` is the entry point.
- ``GET /``       — redirects to ``/pwa/``.

Run::

    uvicorn src.main:app --host 127.0.0.1 --port 8000

Tunnel::

    ngrok http 8000
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import get_settings
from .integrations.notion_client import NotionClient, NotionError
from .models import (
    AutoTag,
    CaptureRequest,
    CaptureResponse,
    ProjectDetail,
    ProjectList,
    TaskList,
    TaskPatch,
    TaskRow,
)
from .orchestrator import handle_voice_text
from . import work_mode
from ._tz import LOCAL_TZ

from .utils.logging import configure_logging, get_logger
from .workers.nag_worker import NagWorker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PWA_DIR = PROJECT_ROOT / "pwa"
PWA_V2_DIR = PROJECT_ROOT / "pwa-v2" / "dist"


# --- App lifecycle ----------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks. Runs once per process.

    Starts the nag worker as a background task. The worker no-ops if
    ``NTFY_TOPIC`` is empty (local dev), so this is safe to always invoke.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger(__name__)

    # Generate-or-reuse the X-PA-Token shared secret. First-run users get a
    # secret written to .env automatically; the iOS Shortcut + PWA both use
    # the same value.
    secret = settings.ensure_webhook_secret()
    log.info(
        "app.startup",
        environment=settings.environment,
        host=settings.host,
        port=settings.port,
        webhook_secret_preview=secret[:6] + "...",
        pwa_dir_exists=PWA_DIR.exists(),
        ntfy_enabled=bool(settings.ntfy_topic),
    )

    # Start background worker. Stored on app.state so we can stop it cleanly.
    app.state.nag_worker = NagWorker(settings)
    app.state.nag_worker.start()

    yield

    # Shutdown: stop the worker first so it doesn't make calls during teardown.
    await app.state.nag_worker.stop()
    log.info("app.shutdown")


app = FastAPI(
    title="PA-Agent",
    description="Voice-first personal assistant. Phase 2: voice + PWA review surface.",
    version="0.2.0",
    lifespan=_lifespan,
)

log = get_logger(__name__)


# --- Auth dependency --------------------------------------------------------


async def require_shared_secret(
    x_pa_token: str | None = Header(default=None, alias="X-PA-Token"),
) -> None:
    """Constant-time compare of the X-PA-Token header against the configured secret.

    Used by both the /capture endpoint (iOS Shortcut) and the /api/* endpoints
    (PWA). Same secret, same model.
    """
    settings = get_settings()
    expected = settings.webhook_shared_secret.get_secret_value()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret not configured.",
        )
    if not x_pa_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-PA-Token header.",
        )
    import secrets as _secrets

    if not _secrets.compare_digest(x_pa_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-PA-Token.",
        )


# --- Notion-client dependency (singleton per process) -----------------------

_notion_client: NotionClient | None = None
_anthropic_client = None  # type: ignore[var-annotated]


def get_notion_client() -> NotionClient:
    """Lazy-init the Notion client so it's not constructed at import time."""
    global _notion_client
    if _notion_client is None:
        _notion_client = NotionClient()
    return _notion_client


def get_anthropic_client():
    """Lazy-init the Anthropic client. Used by the nudge endpoint."""
    global _anthropic_client
    if _anthropic_client is None:
        from .integrations.anthropic_client import AnthropicClient
        _anthropic_client = AnthropicClient()
    return _anthropic_client


# --- Public endpoints -------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — used to confirm the tunnel works before the demo."""
    return {"status": "ok"}


@app.post("/capture", response_model=CaptureResponse)
async def capture(
    body: CaptureRequest,
    _auth: None = Depends(require_shared_secret),
) -> CaptureResponse:
    """Voice-capture endpoint. Used by the iOS Shortcut."""
    start = time.perf_counter()
    response = await handle_voice_text(body.text)
    latency_ms = int((time.perf_counter() - start) * 1000)
    log.info(
        "webhook.capture",
        status=response.status,
        latency_ms=latency_ms,
        captured=len(response.captured),
    )
    return response


# --- PWA API endpoints ------------------------------------------------------


@app.get("/api/today", response_model=TaskList)
async def api_today(
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskList:
    """Today's focus: Active rows due today or earlier, plus undated Urgent."""
    try:
        rows = await notion.query_today_focus()
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return TaskList(items=rows, count=len(rows))


@app.get("/api/wins", response_model=TaskList)
async def api_wins(
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskList:
    """Today's wins: rows marked Done at some point today."""
    try:
        rows = await notion.query_wins_today()
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return TaskList(items=rows, count=len(rows))


@app.get("/api/review", response_model=TaskList)
async def api_review(
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskList:
    """Review queue: Active rows tagged ``review`` (low-confidence captures)."""
    try:
        rows = await notion.query_review_queue()
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return TaskList(items=rows, count=len(rows))


@app.get("/api/quickwins", response_model=TaskList)
async def api_quickwins(
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskList:
    """Quick wins: Active rows tagged ``quick-win`` for momentum moments."""
    try:
        from .models import AutoTag

        rows = await notion.query_by_tag(AutoTag.QUICK_WIN)
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return TaskList(items=rows, count=len(rows))


# --- PWA-v2 list endpoints (Screens 2/3/4/5) -----------------------------


@app.get("/api/tasks/all", response_model=TaskList)
async def api_all_tasks(
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskList:
    """All Active rows of Type=task. Used by the "All" tab.

    Bills are excluded (they have their own tab). Sorted by priority then
    due date.
    """
    try:
        rows = await notion.query_all_active_tasks()
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return TaskList(items=rows, count=len(rows))


@app.get("/api/bills", response_model=TaskList)
async def api_bills(
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskList:
    """All Active rows of Type=bill. Used by the "Bills" tab.

    The Bills screen splits these client-side into "Urgent" (due ≤7d) and
    "Recurring" (Recurrence != none), and shows a total at the top.
    """
    try:
        rows = await notion.query_all_active_bills()
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return TaskList(items=rows, count=len(rows))


@app.get("/api/projects", response_model=ProjectList)
async def api_projects(
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> ProjectList:
    """Projects DB rows with subtask aggregation. Used by the "Projects" tab.

    Each row includes total_subtasks, done_subtasks, and next_incomplete_title
    so the PWA can render the progress bar + "next" line without extra calls.
    """
    try:
        rows = await notion.query_projects()
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return ProjectList(items=rows, count=len(rows))


@app.get("/api/parked", response_model=TaskList)
async def api_parked(
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskList:
    """Status=Parked rows — long-tail "later" pile, sorted oldest-first."""
    try:
        rows = await notion.query_parked()
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return TaskList(items=rows, count=len(rows))


@app.get("/api/needs-date", response_model=TaskList)
async def api_needs_date(
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskList:
    """Active rows with no due date AND not Someday — needs a commitment."""
    try:
        rows = await notion.query_needs_date()
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return TaskList(items=rows, count=len(rows))


@app.get("/api/upcoming", response_model=TaskList)
async def api_upcoming(
    days: int = Query(7, ge=1, le=90),
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskList:
    """Active rows due in the next ``days`` days, excluding today.

    Powers the Today screen's collapsible "Coming up" section and the
    Browse → Upcoming card.
    """
    try:
        rows = await notion.query_upcoming(days_ahead=days)
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return TaskList(items=rows, count=len(rows))


@app.get("/api/wins/recent", response_model=TaskList)
async def api_wins_recent(
    days: int = Query(7, ge=1, le=90),
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskList:
    """Rows marked Done within the last ``days`` days. Default 7.

    Used by the "Wins" tab. The PWA groups client-side by Done-at day.
    """
    since = datetime.now(LOCAL_TZ).date() - timedelta(days=days - 1)
    try:
        rows = await notion.query_done_since(since)
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return TaskList(items=rows, count=len(rows))


# --- Single-row reads (detail screens) -----------------------------------


@app.get("/api/task/{page_id}", response_model=TaskRow)
async def api_get_task(
    page_id: str,
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskRow:
    """Full row for the Task Detail screen."""
    try:
        return await notion.get_task(page_id)
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/project/{project_id}", response_model=ProjectDetail)
async def api_get_project(
    project_id: str,
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> ProjectDetail:
    """Project header + subtasks for the Project Detail screen."""
    try:
        project, subtasks = await notion.get_project_with_subtasks(project_id)
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return ProjectDetail(project=project, subtasks=subtasks)


# --- PWA mutations -------------------------------------------------------


@app.patch("/api/task/{page_id}", response_model=TaskRow)
async def api_update_task(
    page_id: str,
    patch: TaskPatch,
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskRow:
    """Inline-edit endpoint used by Task Detail + Review-queue edit modal."""
    try:
        return await notion.update_task(
            page_id, patch.model_dump(exclude_unset=True)
        )
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.delete("/api/task/{page_id}", response_model=TaskRow)
async def api_delete_task(
    page_id: str,
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskRow:
    """Soft delete — sets Status=Cancelled, keeps the row in Notion."""
    try:
        return await notion.soft_delete(page_id)
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/task/{page_id}/confirm-review", response_model=TaskRow)
async def api_confirm_review(
    page_id: str,
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskRow:
    """Remove the ``review`` auto-tag from a single row.

    Used by the Review Queue "save" button — confirms the agent's
    interpretation and graduates the row to normal Active status.
    """
    try:
        return await notion.remove_auto_tag(page_id, AutoTag.REVIEW)
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/task/{page_id}/restore", response_model=TaskRow)
async def api_restore_task(
    page_id: str,
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> TaskRow:
    """Bring a row back from Done → Active. Powers shake-to-undo on the PWA."""
    try:
        return await notion.mark_active(page_id)
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/task/{page_id}/done")
async def api_mark_done(
    page_id: str,
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> dict[str, Any]:
    """Mark a single row Done."""
    try:
        row = await notion.mark_done(page_id)
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"status": "done", "id": row.id, "title": row.title}


@app.post("/api/task/{page_id}/snooze")
async def api_snooze(
    page_id: str,
    days: int = Query(1, ge=1, le=30),
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> dict[str, Any]:
    """Push a row's due date forward by N days (default 1)."""
    try:
        row = await notion.snooze(page_id, days=days)
    except NotionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {
        "status": "snoozed",
        "id": row.id,
        "title": row.title,
        "new_due_date": row.due_date.isoformat() if row.due_date else None,
    }


# --- PWA-v2 dashboard tiles + AI nudge --------------------------------------


from .streak import compute_streak as _compute_streak  # re-export for callers


@app.get("/api/dashboard")
async def api_dashboard(
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> dict[str, Any]:
    """One round-trip data feed for the PWA's top tiles.

    Returns money owed this week, current streak, review-queue count, wins
    today, urgent today, and a hint about the next bill due.
    """
    today = datetime.now(LOCAL_TZ).date()
    week_from_now = today + timedelta(days=7)

    bills = await notion.query_all_active_bills()
    wins_recent = await notion.query_done_since(today - timedelta(days=29))
    today_focus = await notion.query_today_focus()
    review = await notion.query_review_queue()

    money_due_week = 0.0
    next_bill = None
    for b in bills:
        if b.amount is None or b.due_date is None:
            continue
        if today <= b.due_date <= week_from_now:
            money_due_week += b.amount
            if next_bill is None or (b.due_date < next_bill["due"]):
                next_bill = {
                    "payee": b.payee or b.title,
                    "amount": b.amount,
                    "due": b.due_date.isoformat(),
                }

    wins_today_count = sum(
        1
        for r in wins_recent
        if r.done_at
        and datetime.fromisoformat(r.done_at.replace("Z", "+00:00"))
        .astimezone(LOCAL_TZ)
        .date()
        == today
    )
    urgent_count = sum(1 for r in today_focus if r.priority == "Urgent")

    return {
        "money_due_week": round(money_due_week, 2),
        "next_bill": next_bill,
        "streak_days": _compute_streak(wins_recent),
        "review_count": len(review),
        "wins_today": wins_today_count,
        "urgent_count": urgent_count,
    }


@app.get("/api/nudge")
async def api_nudge(
    _auth: None = Depends(require_shared_secret),
    notion: NotionClient = Depends(get_notion_client),
) -> dict[str, str]:
    """Generate the PWA's "Claude's take" one-liner from live user data.

    Calls Claude Haiku with a JSON snapshot of today's state. Cheap
    (input tokens ~400, output ~50, well under a tenth of a cent per call).
    The PWA caches the result for the morning and lets the user tap to
    refresh.
    """
    today = datetime.now(LOCAL_TZ).date()
    week_from_now = today + timedelta(days=7)

    focus = await notion.query_today_focus()
    bills = await notion.query_all_active_bills()
    wins_recent = await notion.query_done_since(today - timedelta(days=6))

    # Compact payload for the LLM
    snapshot = {
        "today": today.isoformat(),
        "urgent_items": [
            {"title": r.title, "due": r.due_date.isoformat() if r.due_date else None}
            for r in focus if r.priority == "Urgent"
        ][:5],
        "active_today": [
            {"title": r.title, "due": r.due_date.isoformat() if r.due_date else None}
            for r in focus if r.priority != "Urgent"
        ][:5],
        "bills_this_week": [
            {
                "payee": b.payee or b.title,
                "amount": b.amount,
                "due": b.due_date.isoformat() if b.due_date else None,
            }
            for b in bills
            if b.due_date and today <= b.due_date <= week_from_now
        ][:5],
        "wins_this_week": len(wins_recent),
        "wins_today": sum(
            1 for r in wins_recent
            if r.done_at
            and datetime.fromisoformat(r.done_at.replace("Z", "+00:00"))
            .astimezone(LOCAL_TZ)
            .date() == today
        ),
    }

    try:
        anthropic = get_anthropic_client()
        text = await anthropic.nudge(__import__("json").dumps(snapshot))
        return {"text": text}
    except Exception as e:
        log.warning("nudge.fallback", error=str(e))
        # Graceful fallback so the UI never breaks.
        if snapshot["urgent_items"]:
            n = len(snapshot["urgent_items"])
            return {"text": f"{n} urgent item{'s' if n != 1 else ''} pending — start with the smallest one."}
        if snapshot["bills_this_week"]:
            return {"text": "No urgent tasks, but a bill or two due this week. Knock one out."}
        return {"text": "Clear slate. Capture anything that's been bouncing around in your head."}


# --- Web Push endpoints -----------------------------------------------------


@app.get("/api/push/vapid-public-key")
async def api_vapid_public_key() -> dict[str, str]:
    """Return the VAPID public key the PWA needs to call ``pushManager.subscribe()``.

    Public on purpose — the key IS the public half, no auth needed. Empty
    string means push isn't configured (PWA falls back to in-app polling).
    """
    settings = get_settings()
    return {"key": settings.vapid_public_key or ""}


@app.post("/api/push/subscribe")
async def api_push_subscribe(
    body: dict[str, Any],
    _auth: None = Depends(require_shared_secret),
) -> dict[str, Any]:
    """Store a PushSubscription emitted by ``pushManager.subscribe()``.

    Body is the raw ``PushSubscription.toJSON()`` value. We accept an
    optional ``label`` so the user can remember which device this came
    from when pruning later.
    """
    from .integrations.push import PushSubscription, upsert_subscription

    payload = dict(body or {})
    label = payload.pop("label", None)
    try:
        sub = PushSubscription.model_validate({**payload, "label": label})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid subscription: {e}") from e
    upsert_subscription(sub)
    return {"ok": True, "endpoint_host": sub.endpoint.split("/")[2] if "//" in sub.endpoint else ""}


@app.delete("/api/push/subscribe")
async def api_push_unsubscribe(
    endpoint: str = Query(..., description="The endpoint URL of the subscription to remove"),
    _auth: None = Depends(require_shared_secret),
) -> dict[str, bool]:
    """Drop a subscription (called when the user revokes notification permission)."""
    from .integrations.push import remove_subscription

    return {"removed": remove_subscription(endpoint)}


@app.post("/api/push/test")
async def api_push_test(
    _auth: None = Depends(require_shared_secret),
) -> dict[str, Any]:
    """Broadcast a test push to every subscription — useful during setup."""
    from .integrations.push import broadcast

    result = broadcast({
        "title": "PA-Agent · test",
        "body": "If you see this, Web Push is working 🎉",
        "url": "/today",
    })
    return result


# --- Work mode endpoints ----------------------------------------------------


@app.get("/api/work-mode")
async def api_work_mode_state(
    _auth: None = Depends(require_shared_secret),
) -> dict[str, Any]:
    """Return current work-mode state.

    Fields:
      - ``active``: whether work tasks are currently visible (bool)
      - ``source``: ``schedule`` | ``override``
      - ``override``: details of an active override, or null
      - ``schedule``: window we use (so the PWA can render "Work mode · M–F 9–5")
      - ``quiet_hours``: whether we're currently inside the 22:00–06:00 quiet window
    """
    override = work_mode.get_override()
    active = work_mode.is_work_mode_active(override=override)
    return {
        "active": active,
        "source": "override" if override else "schedule",
        "override": override.to_dict() if override else None,
        "schedule": {
            "days": "Mon-Fri",
            "start": work_mode.WORK_START.isoformat(),
            "end": work_mode.WORK_END.isoformat(),
            "tz": str(work_mode.LOCAL_TZ),
        },
        "quiet_hours": work_mode.is_quiet_hours(),
    }


@app.post("/api/work-mode/override")
async def api_work_mode_set_override(
    action: str = Query(..., description="pause-today | start-now | end-early | holiday | clear"),
    hours: float = Query(work_mode.DEFAULT_START_NOW_TTL_HOURS, ge=0.25, le=72),
    until: str | None = Query(None, description="YYYY-MM-DD inclusive end date for holiday"),
    _auth: None = Depends(require_shared_secret),
) -> dict[str, Any]:
    """Apply one of the canned override actions from the PWA.

    Maps 1:1 to the PWA's work-mode toggle buttons (see D7 in PROJECT_STATUS).
    """
    try:
        if action == "pause-today":
            override = work_mode.pause_today()
        elif action == "start-now":
            override = work_mode.start_work_now(hours=hours)
        elif action == "end-early":
            override = work_mode.end_work_early()
        elif action == "holiday":
            if not until:
                raise HTTPException(
                    status_code=400, detail="holiday action requires `until=YYYY-MM-DD`"
                )
            override = work_mode.holiday_until(until)
        elif action == "clear":
            work_mode.clear_override()
            return {"cleared": True, "active": work_mode.is_work_mode_active()}
        else:
            raise HTTPException(status_code=400, detail=f"unknown action: {action}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {
        "active": work_mode.is_work_mode_active(override=override),
        "override": override.to_dict(),
    }


# --- PWA static serving -----------------------------------------------------


@app.get("/")
async def root_redirect() -> RedirectResponse:
    """Open ``/`` → bounce to the PWA so the user doesn't have to type ``/pwa/``."""
    return RedirectResponse(url="/pwa/")


if PWA_DIR.exists():
    # ``html=True`` makes ``/pwa/`` serve ``/pwa/index.html`` automatically.
    app.mount("/pwa", StaticFiles(directory=str(PWA_DIR), html=True), name="pwa")

# v2 — React+Vite PWA following the Jeweled Cream design system. Built via
# ``npm run build`` in pwa-v2/. Served with an SPA-friendly fallback: any
# unknown sub-path returns ``index.html`` so React Router can pick it up
# from there. This is what makes deep links + refreshes work without 404s.
if PWA_V2_DIR.exists():
    from fastapi.responses import FileResponse

    PWA_V2_INDEX = PWA_V2_DIR / "index.html"

    @app.get("/pwa-v2/{full_path:path}", include_in_schema=False)
    async def pwa_v2_spa(full_path: str) -> FileResponse:
        """Serve a static asset if it exists; otherwise fall back to index.html."""
        candidate = PWA_V2_DIR / full_path
        # Guard against ``../`` traversal escaping the dist dir.
        try:
            candidate_resolved = candidate.resolve()
            candidate_resolved.relative_to(PWA_V2_DIR.resolve())
        except (ValueError, OSError):
            return FileResponse(PWA_V2_INDEX)
        if candidate_resolved.is_file():
            return FileResponse(candidate_resolved)
        return FileResponse(PWA_V2_INDEX)

    @app.get("/pwa-v2", include_in_schema=False)
    async def pwa_v2_index() -> FileResponse:
        """``/pwa-v2`` (no trailing slash) → index."""
        return FileResponse(PWA_V2_INDEX)


# --- Friendly error envelope for unhandled exceptions ----------------------


@app.exception_handler(Exception)
async def _unhandled(_request, exc: Exception) -> JSONResponse:
    """Last-resort handler so callers always get parseable JSON back."""
    log.exception("webhook.unhandled", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"status": "error", "error": str(exc)},
    )
