"""Async wrapper around the official ``notion-client`` library.

Why a wrapper:
1. Notion's page-properties payload is verbose and easy to get wrong; one
   helper per field type keeps the orchestrator clean.
2. Property *names* are user-facing (they appear in Notion's UI) and may
   change. Centralising them here means a one-line edit if the user renames
   a column, instead of hunting through call sites.

v3 surface area:

**Writes (used by the voice orchestrator):**
- ``create_task`` — Type=task row in the Tasks DB.
- ``create_bill`` — Type=bill row in the same Tasks DB (with amount/payee/etc).
- ``create_project_with_subtasks`` — parent task + N children linked via
  the ``Parent task`` self-relation.
- ``append_to_brain_dump`` — appends one bulleted, timestamped line to the
  Brain Dump page.
- ``auto_complete_parent_if_all_subtasks_done`` — helper used later by the
  nag worker to roll status up the subtask tree.

**Reads + mutations (used by the PWA in Phase 2):**
- ``query_today_focus`` — Active rows due today or earlier, priority-sorted.
- ``query_wins_today`` — rows marked Done today.
- ``query_review_queue`` — rows with the ``review`` auto-tag.
- ``query_by_tag`` — generic auto-tag filter (powers Quick-wins, Waiting).
- ``mark_done`` / ``snooze`` — single-row status mutations.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from notion_client import AsyncClient

from .._tz import LOCAL_TZ
from ..config import Settings, get_settings
from ..models import (
    AutoTag,
    BillFields,
    BrainDumpFields,
    ProjectFields,
    ProjectRow,
    TaskFields,
    TaskRow,
)
from ..utils.logging import get_logger

log = get_logger(__name__)


class NotionError(RuntimeError):
    """Raised when a Notion API call fails or returns unexpected shape."""


# Property names live here, not inline at call sites. If the user renames a
# Notion column, only this block needs to change.
class TaskProps:
    TITLE = "Task"
    STATUS = "Status"
    TYPE = "Type"
    PRIORITY = "Priority"
    DUE = "Due"
    FIRST_STEP = "First step"
    NOTES = "Notes"
    PROJECT = "Project"
    PARENT_TASK = "Parent task"
    DEPENDS_ON = "Depends on"
    RECURRENCE = "Recurrence"
    RECURRENCE_ENDS = "Recurrence ends"
    AMOUNT = "Amount"
    PAYEE = "Payee"
    ACCOUNT_REF = "Account ref"
    AUTO_TAGS = "Auto tags"
    CONTEXT = "Context"  # Select: personal (default) | work


class ProjectProps:
    """Column names on the Projects DB. Centralised for the same reason as
    ``TaskProps``: renaming a Notion column is then a one-line edit.
    """

    TITLE = "Project"
    STATUS = "Status"
    PRIORITY = "Priority"
    NEXT_ACTION = "Next action"
    NOTES = "Notes"
    TASKS = "Tasks"  # relation → Tasks DB (back-reference)


# Status-column values
STATUS_ACTIVE = "Active"
STATUS_DONE = "Done"
STATUS_CANCELLED = "Cancelled"
STATUS_PARKED = "Parked"

# Type-column values
TYPE_TASK = "task"
TYPE_BILL = "bill"

# Context-column values
CONTEXT_PERSONAL = "personal"
CONTEXT_WORK = "work"

# Priority sort order — lower number sorts first. Used in client-side sort
# because Notion's select-column sort is alphabetical, which is wrong for us.
_PRIORITY_ORDER = {"Urgent": 0, "Important": 1, "Normal": 2, "Someday": 3}


class NotionClient:
    """Thin async wrapper around ``notion-client``'s ``AsyncClient``."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = AsyncClient(auth=self.settings.notion_api_key.get_secret_value())

    # --- create_task ---------------------------------------------------

    async def create_task(self, task: TaskFields) -> dict[str, Any]:
        """Create a Type=task row in the Tasks DB.

        Returns the created page dict (includes ``id`` and ``url``). Raises
        ``NotionError`` on API/network/auth failure.
        """
        properties = self._task_to_properties(task)
        body: dict[str, Any] = {
            "parent": self._tasks_parent(),
            "properties": properties,
        }
        notes_blocks = self._first_step_block(task.first_step)
        if notes_blocks:
            body["children"] = notes_blocks

        page = await self._create_page(body, label="create_task")
        log.info(
            "notion.create_task_ok",
            page_id=page["id"],
            url=page.get("url"),
            priority=task.priority,
            recurrence=task.recurrence.value,
            context=task.context,
        )
        return page

    # --- create_bill ---------------------------------------------------

    async def create_bill(self, bill: BillFields) -> dict[str, Any]:
        """Create a Type=bill row in the Tasks DB.

        Bills share the Tasks DB so they show up in the same "what do I need
        to deal with" view; the ``Type`` column distinguishes them.
        """
        properties = self._bill_to_properties(bill)
        body: dict[str, Any] = {
            "parent": self._tasks_parent(),
            "properties": properties,
        }
        page = await self._create_page(body, label="create_bill")
        log.info(
            "notion.create_bill_ok",
            page_id=page["id"],
            url=page.get("url"),
            amount=str(bill.amount) if bill.amount is not None else None,
            recurrence=bill.recurrence.value,
            context=bill.context,
        )
        return page

    # --- create_project_with_subtasks ---------------------------------

    async def create_project_with_subtasks(
        self, project: ProjectFields
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Create the parent task row, then N children linked via Parent task.

        Returns ``(parent_page, [child_pages...])``. Each child row is
        Type=task with Status=Active and ``Parent task`` pointing at the
        parent page ID. Notion auto-populates the parent's ``Subtasks`` field
        via the reverse relation.
        """
        # 1. Parent row
        parent_task = TaskFields(
            title=project.title,
            priority=project.priority,
            first_step=project.first_step,
            notes=project.notes,
            auto_tags=project.auto_tags,
        )
        parent_page = await self.create_task(parent_task)
        parent_id = parent_page["id"]

        # 2. Child rows. Sequential — we want to fail loud if any fails so
        #    the user can see partial state in the response. Going parallel
        #    would speed it up but obscure partial-failure semantics.
        children: list[dict[str, Any]] = []
        for child_title in project.decomposed_subtasks:
            child_task = TaskFields(
                title=child_title,
                priority=project.priority,
                parent_task=parent_id,  # carries the page-id through
            )
            try:
                child_page = await self.create_task(child_task)
            except NotionError as e:
                log.error(
                    "notion.create_subtask_failed",
                    parent_id=parent_id,
                    title=child_title,
                    error=str(e),
                )
                raise
            children.append(child_page)

        log.info(
            "notion.create_project_ok",
            parent_id=parent_id,
            url=parent_page.get("url"),
            subtasks=len(children),
        )
        return parent_page, children

    # --- append_to_brain_dump -----------------------------------------

    async def append_to_brain_dump(self, dump: BrainDumpFields) -> dict[str, Any]:
        """Append a single bulleted block to the Brain Dump page.

        Each entry is prefixed with an ISO timestamp so the page reads as a
        chronological river of thoughts. Returns the API response so callers
        can grab the page URL for the confirmation summary.
        """
        if not self.settings.notion_brain_dump_page_id:
            raise NotionError(
                "NOTION_BRAIN_DUMP_PAGE_ID is not configured — set it in .env."
            )

        # Timestamp in local TZ — configurable via PA_LOCAL_TZ env var (see src/_tz.py).
        local = datetime.now(LOCAL_TZ)
        stamp = local.strftime("%Y-%m-%d %H:%M")
        text = f"[{stamp}] {dump.content}"

        block_children = [
            {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [
                        {"type": "text", "text": {"content": text[:2000]}}
                    ]
                },
            }
        ]
        try:
            response = await self._client.blocks.children.append(
                block_id=self.settings.notion_brain_dump_page_id,
                children=block_children,
            )
        except Exception as e:
            log.error("notion.append_brain_dump_failed", error=str(e))
            raise NotionError(f"Notion brain-dump append failed: {e}") from e

        log.info("notion.append_brain_dump_ok", chars=len(text))
        return response  # type: ignore[no-any-return]

    # --- auto_complete_parent_if_all_subtasks_done --------------------

    async def auto_complete_parent_if_all_subtasks_done(self, parent_id: str) -> bool:
        """Mark a parent task Done if all of its child subtasks are Done.

        Returns True if the parent was updated, False otherwise. This is a
        helper used by future workers (nag worker, status-change webhooks);
        the orchestrator does not call it during a voice capture.
        """
        query = await self._client.data_sources.query(
            data_source_id=self.settings.notion_tasks_ds_id,
            filter={
                "property": TaskProps.PARENT_TASK,
                "relation": {"contains": parent_id},
            },
        )
        results = query.get("results", [])
        if not results:
            return False  # parent has no subtasks; nothing to roll up

        for child in results:
            status = (
                child.get("properties", {})
                .get(TaskProps.STATUS, {})
                .get("select", {})
                or {}
            ).get("name")
            if status != STATUS_DONE:
                return False

        # All children Done — mark parent Done.
        await self._client.pages.update(
            page_id=parent_id,
            properties={TaskProps.STATUS: _select(STATUS_DONE)},
        )
        log.info(
            "notion.parent_auto_completed",
            parent_id=parent_id,
            subtask_count=len(results),
        )
        return True

    # --- PWA queries ---------------------------------------------------

    async def query_today_focus(self) -> list[TaskRow]:
        """Active rows that are due today or earlier, OR undated + Urgent.

        Sorted by priority (Urgent → Someday), then by due date ascending.
        Bills + tasks are mixed; the PWA can group by Type if it wants.

        Implementation note: Notion's compound-filter depth is 2, so we run
        the two branches (dated-and-due vs undated-and-urgent) as separate
        queries and merge client-side, de-duplicating by page id.
        """
        today = datetime.now(LOCAL_TZ).date()
        dated_filter = {
            "and": [
                {"property": TaskProps.STATUS, "select": {"equals": STATUS_ACTIVE}},
                {
                    "property": TaskProps.DUE,
                    "date": {"on_or_before": today.isoformat()},
                },
            ]
        }
        undated_urgent_filter = {
            "and": [
                {"property": TaskProps.STATUS, "select": {"equals": STATUS_ACTIVE}},
                {"property": TaskProps.DUE, "date": {"is_empty": True}},
                {"property": TaskProps.PRIORITY, "select": {"equals": "Urgent"}},
            ]
        }
        dated = await self._query_tasks(dated_filter, label="today_focus.dated")
        urgent = await self._query_tasks(
            undated_urgent_filter, label="today_focus.urgent_undated"
        )
        seen: set[str] = set()
        merged: list[TaskRow] = []
        for row in dated + urgent:
            if row.id and row.id not in seen:
                seen.add(row.id)
                merged.append(row)
        merged.sort(key=lambda r: (_PRIORITY_ORDER.get(r.priority, 99), r.due_date or date.max))
        return merged

    async def query_wins_today(self) -> list[TaskRow]:
        """Rows marked Done at any point today (local time).

        Notion's ``last_edited_time`` is the proxy we use for "done at" — the
        Tasks DB's ``Done at`` column is a last_edited_time property. This is
        not perfectly accurate (any edit re-stamps it) but is good enough for
        the daily-wins celebration view.
        """
        today = datetime.now(LOCAL_TZ).date()
        filter_obj = {
            "and": [
                {"property": TaskProps.STATUS, "select": {"equals": STATUS_DONE}},
                {
                    "timestamp": "last_edited_time",
                    "last_edited_time": {"on_or_after": today.isoformat()},
                },
            ]
        }
        rows = await self._query_tasks(filter_obj, label="wins_today")
        rows.sort(key=lambda r: r.done_at or "", reverse=True)
        return rows

    async def query_review_queue(self) -> list[TaskRow]:
        """Active rows tagged ``review`` (low-confidence captures awaiting triage)."""
        return await self.query_by_tag(AutoTag.REVIEW)

    async def query_by_tag(self, tag: AutoTag) -> list[TaskRow]:
        """Active rows whose Auto-tags include the given tag."""
        filter_obj = {
            "and": [
                {"property": TaskProps.STATUS, "select": {"equals": STATUS_ACTIVE}},
                {
                    "property": TaskProps.AUTO_TAGS,
                    "multi_select": {"contains": tag.value},
                },
            ]
        }
        rows = await self._query_tasks(filter_obj, label=f"by_tag:{tag.value}")
        rows.sort(key=lambda r: (_PRIORITY_ORDER.get(r.priority, 99), r.due_date or date.max))
        return rows

    # --- Bulk lists (Screens 2/3/5) ------------------------------------

    async def query_parked(self) -> list[TaskRow]:
        """Rows the user has Parked — collapsible "later" pile on Review.

        Sorted oldest-first by captured_at so the long-dormant ones surface
        first. The PWA badges anything older than 12 months as "long parked".
        """
        filter_obj = {
            "property": TaskProps.STATUS,
            "select": {"equals": STATUS_PARKED},
        }
        rows = await self._query_tasks(filter_obj, label="parked")
        rows.sort(key=lambda r: r.captured_at or "")
        return rows

    async def query_needs_date(self) -> list[TaskRow]:
        """Active rows with no due date AND not Someday priority.

        Powers the "Needs a date" section on Review — these are commitments
        the user has implicitly made but never time-boxed. Someday tasks are
        intentionally dateless so they're excluded.
        """
        filter_obj = {
            "and": [
                {"property": TaskProps.STATUS, "select": {"equals": STATUS_ACTIVE}},
                {"property": TaskProps.DUE, "date": {"is_empty": True}},
                {
                    "property": TaskProps.PRIORITY,
                    "select": {"does_not_equal": "Someday"},
                },
            ]
        }
        rows = await self._query_tasks(filter_obj, label="needs_date")
        rows.sort(
            key=lambda r: (
                _PRIORITY_ORDER.get(r.priority, 99),
                r.title.lower(),
            )
        )
        return rows

    async def query_upcoming(self, days_ahead: int = 7) -> list[TaskRow]:
        """Active rows due in the next ``days_ahead`` days, EXCLUDING today.

        Powers the "Coming up" collapsible on Today and the "Upcoming" card
        on Browse. Excluding today avoids overlap with the main Today list.
        """
        today = datetime.now(LOCAL_TZ).date()
        horizon = today + timedelta(days=days_ahead)
        filter_obj = {
            "and": [
                {"property": TaskProps.STATUS, "select": {"equals": STATUS_ACTIVE}},
                {
                    "property": TaskProps.DUE,
                    "date": {"after": today.isoformat()},
                },
                {
                    "property": TaskProps.DUE,
                    "date": {"on_or_before": horizon.isoformat()},
                },
            ]
        }
        rows = await self._query_tasks(filter_obj, label=f"upcoming:{days_ahead}d")
        rows.sort(key=lambda r: (r.due_date or date.max, _PRIORITY_ORDER.get(r.priority, 99)))
        return rows

    async def query_all_active_tasks(self) -> list[TaskRow]:
        """All Active rows of Type=task. Sorted by priority then due-date.

        Used by the "All" tab (Screen 2). Bills excluded so they keep their
        dedicated tab.
        """
        filter_obj = {
            "and": [
                {"property": TaskProps.STATUS, "select": {"equals": STATUS_ACTIVE}},
                {"property": TaskProps.TYPE, "select": {"equals": TYPE_TASK}},
            ]
        }
        rows = await self._query_tasks(filter_obj, label="all_active_tasks")
        rows.sort(
            key=lambda r: (
                _PRIORITY_ORDER.get(r.priority, 99),
                r.due_date or date.max,
            )
        )
        return rows

    async def query_all_active_bills(self) -> list[TaskRow]:
        """All Active rows of Type=bill. Sorted by due-date ascending.

        Used by the "Bills" tab (Screen 3). The screen splits this list
        into Urgent (due ≤7d) + Recurring (recurrence != none) client-side.
        """
        filter_obj = {
            "and": [
                {"property": TaskProps.STATUS, "select": {"equals": STATUS_ACTIVE}},
                {"property": TaskProps.TYPE, "select": {"equals": TYPE_BILL}},
            ]
        }
        rows = await self._query_tasks(filter_obj, label="all_active_bills")
        rows.sort(key=lambda r: (r.due_date or date.max, r.title.lower()))
        return rows

    async def query_done_since(self, since: date) -> list[TaskRow]:
        """All rows marked Done at or after ``since`` (local-time date).

        Used by the "Wins" tab (Screen 5). The screen groups client-side
        by Done-at day. We use Notion's ``last_edited_time`` timestamp
        because the Tasks DB's ``Done at`` column is a last_edited_time
        property (its value tracks the most recent edit, which in our flow
        is the Done flip).
        """
        filter_obj = {
            "and": [
                {"property": TaskProps.STATUS, "select": {"equals": STATUS_DONE}},
                {
                    "timestamp": "last_edited_time",
                    "last_edited_time": {"on_or_after": since.isoformat()},
                },
            ]
        }
        rows = await self._query_tasks(filter_obj, label=f"done_since:{since}")
        rows.sort(key=lambda r: r.done_at or "", reverse=True)
        return rows

    # --- Projects (Screen 4) -------------------------------------------

    async def query_projects(self, *, include_paused: bool = False) -> list[ProjectRow]:
        """List rows from the Projects DB with subtask aggregation.

        For each project we run a follow-up query against the Tasks DB
        filtered by the ``Project`` relation = this project's page id, to
        compute total / done counts and pick a "next incomplete" title.

        Args:
            include_paused: when True, also returns Status=Paused. Default
                False keeps the screen focused on what's moving.
        """
        if not self.settings.notion_projects_ds_id:
            return []

        statuses = ["Active"]
        if include_paused:
            statuses.append("Paused")

        if len(statuses) == 1:
            project_filter: dict[str, Any] = {
                "property": ProjectProps.STATUS,
                "select": {"equals": statuses[0]},
            }
        else:
            project_filter = {
                "or": [
                    {
                        "property": ProjectProps.STATUS,
                        "select": {"equals": s},
                    }
                    for s in statuses
                ]
            }

        try:
            resp = await self._client.data_sources.query(
                data_source_id=self.settings.notion_projects_ds_id,
                filter=project_filter,
                page_size=100,
            )
        except Exception as e:
            log.error("notion.query_projects_failed", error=str(e))
            raise NotionError(f"projects query failed: {e}") from e

        project_pages = resp.get("results", [])
        log.info("notion.query_ok", label="projects", count=len(project_pages))

        # Aggregate each project in sequence. With a typical handful of
        # projects this is cheap; if it grows we can fan-out via asyncio.gather.
        rows: list[ProjectRow] = []
        for page in project_pages:
            row = await self._project_with_progress(page)
            rows.append(row)

        # Active first, then by completion (less-done first so attention
        # lands on stuck projects), then by title.
        rows.sort(
            key=lambda p: (
                0 if p.status == "Active" else 1,
                p.done_subtasks / p.total_subtasks if p.total_subtasks else 1.0,
                p.title.lower(),
            )
        )
        return rows

    async def _project_with_progress(self, project_page: dict[str, Any]) -> ProjectRow:
        """Build a ProjectRow from a Projects-DB page + a subtask query."""
        props = project_page.get("properties", {})
        project_id = project_page.get("id", "")
        title = _read_title(props.get(ProjectProps.TITLE))
        status = _read_select(props.get(ProjectProps.STATUS)) or "Active"
        priority = _read_select(props.get(ProjectProps.PRIORITY))
        next_action = _read_rich_text(props.get(ProjectProps.NEXT_ACTION))
        notes = _read_rich_text(props.get(ProjectProps.NOTES))

        # Fetch subtasks. We page through because some projects might have
        # many. The aggregate is cheap to compute in Python afterwards.
        subtasks = await self._query_tasks(
            {
                "property": TaskProps.PROJECT,
                "relation": {"contains": project_id},
            },
            label=f"project_subtasks:{title[:20]}",
        )
        total = len(subtasks)
        done = sum(1 for s in subtasks if s.status == STATUS_DONE)

        # Pick the first incomplete subtask, prioritising Active rows over
        # Parked/Cancelled. Sort by (priority, due, title).
        incomplete = [s for s in subtasks if s.status == STATUS_ACTIVE]
        incomplete.sort(
            key=lambda s: (
                _PRIORITY_ORDER.get(s.priority, 99),
                s.due_date or date.max,
                s.title.lower(),
            )
        )
        next_incomplete_title = incomplete[0].title if incomplete else None

        return ProjectRow(
            id=project_id,
            title=title,
            status=status,
            priority=priority,
            next_action=next_action,
            notes=notes,
            url=project_page.get("url"),
            total_subtasks=total,
            done_subtasks=done,
            next_incomplete_title=next_incomplete_title,
        )

    # --- Single-row reads (detail screens) ----------------------------

    async def get_task(self, page_id: str) -> TaskRow:
        """Fetch one Tasks-DB row and project to TaskRow."""
        try:
            page = await self._client.pages.retrieve(page_id=page_id)
        except Exception as e:
            log.error("notion.get_task_failed", page_id=page_id, error=str(e))
            raise NotionError(f"get_task failed: {e}") from e
        return _row_from_page(page)

    async def get_project_with_subtasks(
        self, project_id: str
    ) -> tuple[ProjectRow, list[TaskRow]]:
        """Fetch a Projects-DB row plus the full Tasks list linked to it.

        Subtasks are sorted Active-first, then by priority, then by due,
        then by title — same ordering the All screen uses.
        """
        try:
            page = await self._client.pages.retrieve(page_id=project_id)
        except Exception as e:
            log.error("notion.get_project_failed", project_id=project_id, error=str(e))
            raise NotionError(f"get_project failed: {e}") from e

        project_row = await self._project_with_progress(page)
        subtasks = await self._query_tasks(
            {
                "property": TaskProps.PROJECT,
                "relation": {"contains": project_id},
            },
            label=f"project_detail_subtasks:{project_id[:8]}",
        )
        subtasks.sort(
            key=lambda s: (
                0 if s.status == STATUS_ACTIVE else 1,
                _PRIORITY_ORDER.get(s.priority, 99),
                s.due_date or date.max,
                s.title.lower(),
            )
        )
        return project_row, subtasks

    # --- PWA mutations -------------------------------------------------

    async def update_task(self, page_id: str, patch: dict[str, Any]) -> TaskRow:
        """Apply a partial update. ``patch`` keys are the (Python) field
        names from :class:`TaskPatch`; values are pre-validated Pydantic
        types. Only non-None fields are written.
        """
        props: dict[str, Any] = {}
        if "title" in patch and patch["title"] is not None:
            props[TaskProps.TITLE] = _title(patch["title"])
        if "priority" in patch and patch["priority"] is not None:
            props[TaskProps.PRIORITY] = _select(patch["priority"])
        if "due_date" in patch and patch["due_date"] is not None:
            props[TaskProps.DUE] = _date(patch["due_date"])
        if "first_step" in patch and patch["first_step"] is not None:
            props[TaskProps.FIRST_STEP] = _rich_text(patch["first_step"])
        if "notes" in patch and patch["notes"] is not None:
            props[TaskProps.NOTES] = _rich_text(patch["notes"])
        if "recurrence" in patch and patch["recurrence"] is not None:
            # patch["recurrence"] is a Recurrence enum coming out of TaskPatch.
            value = (
                patch["recurrence"].value
                if hasattr(patch["recurrence"], "value")
                else str(patch["recurrence"])
            )
            props[TaskProps.RECURRENCE] = _select(value)
        if "auto_tags" in patch and patch["auto_tags"] is not None:
            props[TaskProps.AUTO_TAGS] = _multi_select(patch["auto_tags"])
        if "amount" in patch and patch["amount"] is not None:
            props[TaskProps.AMOUNT] = _number(patch["amount"])
        if "payee" in patch and patch["payee"] is not None:
            props[TaskProps.PAYEE] = _rich_text(patch["payee"])
        if "context" in patch and patch["context"] is not None:
            # Pydantic Literal — value is the string "personal"/"work"
            props[TaskProps.CONTEXT] = _select(str(patch["context"]))

        if not props:
            # Nothing to write — just return the current row.
            return await self.get_task(page_id)

        try:
            page = await self._client.pages.update(page_id=page_id, properties=props)
        except Exception as e:
            log.error("notion.update_task_failed", page_id=page_id, error=str(e))
            raise NotionError(f"update_task failed: {e}") from e
        log.info(
            "notion.update_task_ok",
            page_id=page_id,
            fields=list(props.keys()),
        )
        return _row_from_page(page)

    async def soft_delete(self, page_id: str) -> TaskRow:
        """Set Status=Cancelled. Notion keeps the row; the PWA hides it."""
        try:
            page = await self._client.pages.update(
                page_id=page_id,
                properties={TaskProps.STATUS: _select(STATUS_CANCELLED)},
            )
        except Exception as e:
            log.error("notion.soft_delete_failed", page_id=page_id, error=str(e))
            raise NotionError(f"soft_delete failed: {e}") from e
        log.info("notion.soft_delete_ok", page_id=page_id)
        return _row_from_page(page)

    async def remove_auto_tag(self, page_id: str, tag: AutoTag) -> TaskRow:
        """Strip one auto-tag from a row. Used by the Review-queue "save"
        button — confirming a flagged capture removes the ``review`` tag.
        """
        current = await self.get_task(page_id)
        new_tags = [t for t in current.auto_tags if t != tag.value]
        # Even if the tag wasn't present, we re-write the multi_select so
        # the page's modified timestamp updates and the row drops from the
        # review filter.
        try:
            page = await self._client.pages.update(
                page_id=page_id,
                properties={
                    TaskProps.AUTO_TAGS: {
                        "multi_select": [{"name": name} for name in new_tags]
                    }
                },
            )
        except Exception as e:
            log.error("notion.remove_tag_failed", page_id=page_id, error=str(e))
            raise NotionError(f"remove_auto_tag failed: {e}") from e
        log.info("notion.remove_tag_ok", page_id=page_id, removed=tag.value)
        return _row_from_page(page)

    async def mark_done(self, page_id: str) -> TaskRow:
        """Mark a single row Done. Returns the updated row projection."""
        try:
            page = await self._client.pages.update(
                page_id=page_id,
                properties={TaskProps.STATUS: _select(STATUS_DONE)},
            )
        except Exception as e:
            log.error("notion.mark_done_failed", page_id=page_id, error=str(e))
            raise NotionError(f"mark_done failed: {e}") from e
        log.info("notion.mark_done_ok", page_id=page_id)
        return _row_from_page(page)

    async def mark_active(self, page_id: str) -> TaskRow:
        """Restore a row to Active. Powers the PWA's shake-to-undo gesture."""
        try:
            page = await self._client.pages.update(
                page_id=page_id,
                properties={TaskProps.STATUS: _select(STATUS_ACTIVE)},
            )
        except Exception as e:
            log.error("notion.mark_active_failed", page_id=page_id, error=str(e))
            raise NotionError(f"mark_active failed: {e}") from e
        log.info("notion.mark_active_ok", page_id=page_id)
        return _row_from_page(page)

    async def snooze(self, page_id: str, days: int = 1) -> TaskRow:
        """Push a row's due date forward by N days.

        If the row has no due date, sets it to today + N. Bumping by 1 day
        is the PWA's default left-swipe behaviour; the API exposes ``days``
        for future "snooze a week" gestures.
        """
        try:
            current = await self._client.pages.retrieve(page_id=page_id)
        except Exception as e:
            log.error("notion.snooze_retrieve_failed", page_id=page_id, error=str(e))
            raise NotionError(f"snooze retrieve failed: {e}") from e

        existing_due = _parse_date_prop(
            current.get("properties", {}).get(TaskProps.DUE)
        )
        anchor = existing_due or datetime.now(LOCAL_TZ).date()
        new_due = anchor + timedelta(days=days)

        try:
            page = await self._client.pages.update(
                page_id=page_id,
                properties={TaskProps.DUE: _date(new_due)},
            )
        except Exception as e:
            log.error("notion.snooze_update_failed", page_id=page_id, error=str(e))
            raise NotionError(f"snooze update failed: {e}") from e
        log.info("notion.snooze_ok", page_id=page_id, new_due=new_due.isoformat())
        return _row_from_page(page)

    # --- Internal: query helper ----------------------------------------

    async def _query_tasks(
        self, filter_obj: dict[str, Any], *, label: str, page_size: int = 100
    ) -> list[TaskRow]:
        """Run a Notion data-source query and project each result to TaskRow."""
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        try:
            while True:
                kwargs: dict[str, Any] = {
                    "data_source_id": self.settings.notion_tasks_ds_id,
                    "filter": filter_obj,
                    "page_size": page_size,
                }
                if cursor:
                    kwargs["start_cursor"] = cursor
                resp = await self._client.data_sources.query(**kwargs)
                results.extend(resp.get("results", []))
                if not resp.get("has_more"):
                    break
                cursor = resp.get("next_cursor")
        except Exception as e:
            log.error("notion.query_failed", label=label, error=str(e))
            raise NotionError(f"Notion query {label} failed: {e}") from e
        log.info("notion.query_ok", label=label, count=len(results))
        return [_row_from_page(p) for p in results]

    # --- Internal: HTTP + property builders -----------------------------

    def _tasks_parent(self) -> dict[str, Any]:
        """The Tasks data-source parent reference used for create_page calls."""
        return {
            "type": "data_source_id",
            "data_source_id": self.settings.notion_tasks_ds_id,
        }

    async def _create_page(self, body: dict[str, Any], *, label: str) -> dict[str, Any]:
        try:
            page = await self._client.pages.create(**body)
        except Exception as e:
            log.error("notion.create_page_failed", label=label, error=str(e))
            raise NotionError(f"Notion {label} failed: {e}") from e
        if not isinstance(page, dict) or "id" not in page:
            raise NotionError(f"Notion returned unexpected payload: {type(page).__name__}")
        return page

    def _task_to_properties(self, task: TaskFields) -> dict[str, Any]:
        """Translate ``TaskFields`` to Notion's properties payload."""
        props: dict[str, Any] = {
            TaskProps.TITLE: _title(task.title),
            TaskProps.STATUS: _select(STATUS_ACTIVE),
            TaskProps.TYPE: _select(TYPE_TASK),
            TaskProps.PRIORITY: _select(task.priority),
            TaskProps.RECURRENCE: _select(task.recurrence.value),
            TaskProps.CONTEXT: _select(task.context),
        }
        if task.due_date is not None:
            props[TaskProps.DUE] = _date(task.due_date)
        if task.recurrence_ends is not None:
            props[TaskProps.RECURRENCE_ENDS] = _date(task.recurrence_ends)
        if task.first_step:
            props[TaskProps.FIRST_STEP] = _rich_text(task.first_step)
        if task.notes:
            props[TaskProps.NOTES] = _rich_text(task.notes)
        if task.parent_task:
            props[TaskProps.PARENT_TASK] = _relation([task.parent_task])
        if task.depends_on:
            props[TaskProps.DEPENDS_ON] = _relation(task.depends_on)
        if task.auto_tags:
            props[TaskProps.AUTO_TAGS] = _multi_select(task.auto_tags)
        return props

    def _bill_to_properties(self, bill: BillFields) -> dict[str, Any]:
        """Translate ``BillFields`` to Notion's properties payload."""
        props: dict[str, Any] = {
            TaskProps.TITLE: _title(bill.title),
            TaskProps.STATUS: _select(STATUS_ACTIVE),
            TaskProps.TYPE: _select(TYPE_BILL),
            TaskProps.PRIORITY: _select(bill.priority),
            TaskProps.RECURRENCE: _select(bill.recurrence.value),
            TaskProps.CONTEXT: _select(bill.context),
        }
        if bill.amount is not None:
            props[TaskProps.AMOUNT] = _number(bill.amount)
        if bill.due_date is not None:
            props[TaskProps.DUE] = _date(bill.due_date)
        if bill.recurrence_ends is not None:
            props[TaskProps.RECURRENCE_ENDS] = _date(bill.recurrence_ends)
        if bill.payee:
            props[TaskProps.PAYEE] = _rich_text(bill.payee)
        if bill.account_ref:
            props[TaskProps.ACCOUNT_REF] = _rich_text(bill.account_ref)
        if bill.notes:
            props[TaskProps.NOTES] = _rich_text(bill.notes)
        if bill.auto_tags:
            props[TaskProps.AUTO_TAGS] = _multi_select(bill.auto_tags)
        return props

    def _first_step_block(self, first_step: str | None) -> list[dict[str, Any]]:
        """Build child blocks under the task page.

        We surface the smallest-first-step as a callout so it's visually
        prominent — that's the field that makes ADHD tasks unblockable.
        Returns an empty list if there's nothing to show.
        """
        if not first_step:
            return []
        return [
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "icon": {"type": "emoji", "emoji": "▶️"},
                    "rich_text": [
                        {"type": "text", "text": {"content": f"First step: {first_step}"}}
                    ],
                },
            }
        ]


# --- Module-level builders. Free functions so they're trivially unit-testable.


def _title(value: str) -> dict[str, Any]:
    return {"title": [{"type": "text", "text": {"content": value[:200]}}]}


def _rich_text(value: str) -> dict[str, Any]:
    # Notion limits a single rich_text block to 2000 chars; truncate quietly.
    return {"rich_text": [{"type": "text", "text": {"content": value[:2000]}}]}


def _select(name: str) -> dict[str, Any]:
    return {"select": {"name": name}}


def _multi_select(values: list[AutoTag]) -> dict[str, Any]:
    return {"multi_select": [{"name": v.value} for v in values]}


def _date(value: date) -> dict[str, Any]:
    return {"date": {"start": value.isoformat()}}


def _number(value: Decimal | float) -> dict[str, Any]:
    # Notion's number column wants a JSON number — Decimal serializes as str
    # by default, which Notion would reject, so cast.
    return {"number": float(value)}


def _relation(page_ids: list[str]) -> dict[str, Any]:
    return {"relation": [{"id": pid} for pid in page_ids]}


# --- Module-level readers ---------------------------------------------------


def _row_from_page(page: dict[str, Any]) -> TaskRow:
    """Project a raw Notion page object down to a slim ``TaskRow`` for the PWA.

    Defensive: missing / null properties become sensible defaults so the PWA
    never has to handle ``KeyError``. Unknown property values fall back to
    string equivalents.
    """
    props = page.get("properties", {})
    # Context: default to "personal" if Notion column is missing or empty so
    # rows captured before the column was added still validate.
    raw_context = _read_select(props.get(TaskProps.CONTEXT))
    context = raw_context if raw_context in (CONTEXT_PERSONAL, CONTEXT_WORK) else CONTEXT_PERSONAL
    return TaskRow(
        id=page.get("id", ""),
        title=_read_title(props.get(TaskProps.TITLE)),
        type=_read_select(props.get(TaskProps.TYPE)) or "task",  # type: ignore[arg-type]
        status=_read_select(props.get(TaskProps.STATUS)) or "Active",
        priority=_read_select(props.get(TaskProps.PRIORITY)) or "Normal",
        due_date=_parse_date_prop(props.get(TaskProps.DUE)),
        first_step=_read_rich_text(props.get(TaskProps.FIRST_STEP)),
        recurrence=_read_select(props.get(TaskProps.RECURRENCE)) or "none",
        amount=_read_number(props.get(TaskProps.AMOUNT)),
        payee=_read_rich_text(props.get(TaskProps.PAYEE)),
        auto_tags=_read_multi_select(props.get(TaskProps.AUTO_TAGS)),
        parent_task_id=_read_first_relation(props.get(TaskProps.PARENT_TASK)),
        url=page.get("url"),
        captured_at=_read_created_time(props.get("Captured")),
        done_at=_read_last_edited(props.get("Done at")),
        context=context,  # type: ignore[arg-type]
    )


def _read_title(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""
    parts = prop.get("title", [])
    return "".join(p.get("plain_text", "") for p in parts)


def _read_select(prop: dict[str, Any] | None) -> str | None:
    if not prop:
        return None
    sel = prop.get("select")
    return sel.get("name") if isinstance(sel, dict) else None


def _read_multi_select(prop: dict[str, Any] | None) -> list[str]:
    if not prop:
        return []
    return [o.get("name", "") for o in prop.get("multi_select", []) if o.get("name")]


def _read_rich_text(prop: dict[str, Any] | None) -> str | None:
    if not prop:
        return None
    parts = prop.get("rich_text", [])
    text = "".join(p.get("plain_text", "") for p in parts)
    return text or None


def _read_number(prop: dict[str, Any] | None) -> float | None:
    if not prop:
        return None
    val = prop.get("number")
    return float(val) if val is not None else None


def _read_first_relation(prop: dict[str, Any] | None) -> str | None:
    if not prop:
        return None
    rels = prop.get("relation", [])
    return rels[0].get("id") if rels else None


def _read_created_time(prop: dict[str, Any] | None) -> str | None:
    if not prop:
        return None
    return prop.get("created_time")


def _read_last_edited(prop: dict[str, Any] | None) -> str | None:
    if not prop:
        return None
    return prop.get("last_edited_time")


def _parse_date_prop(prop: dict[str, Any] | None) -> date | None:
    """Extract a ``date`` from Notion's date column shape."""
    if not prop:
        return None
    date_obj = prop.get("date")
    if not isinstance(date_obj, dict):
        return None
    start = date_obj.get("start")
    if not start:
        return None
    # Notion returns either YYYY-MM-DD or full ISO datetime; take the date part.
    return date.fromisoformat(start[:10])
