"""Shared Pydantic models used across the pipeline.

These types pin the contract between the orchestrator and the integrations.
The classifier + extractor return raw dicts from Claude; the orchestrator
validates them into these models so downstream code gets type-checking and
auto-completion.

v3 schema: four top-level intents (task / bill / project / brain_dump) plus a
``multi`` wrapper. Calendar events are out — Siri handles those directly. The
Tasks DB is now unified: bills live there too, distinguished by the ``Type``
column.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# --- Enums ------------------------------------------------------------------


class Intent(str, Enum):
    """The top-level intents the classifier returns (v3)."""

    TASK = "task"
    BILL = "bill"
    PROJECT = "project"
    BRAIN_DUMP = "brain_dump"
    MULTI = "multi"


class Recurrence(str, Enum):
    """Recurrence cadence — applies to any task/bill, not a category of its own.

    Values mirror the Notion ``Recurrence`` select column exactly so we can
    pass them through without translation.
    """

    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    FORTNIGHTLY = "fortnightly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class AutoTag(str, Enum):
    """Automated triage tags written to the Notion ``Auto tags`` multi-select.

    The orchestrator auto-adds ``REVIEW`` when classifier/extractor confidence
    falls below the v3 threshold (0.7). The remaining tags are reserved for
    future workers (nag worker promotes overdue items to ``WAITING``, etc.).
    """

    REVIEW = "review"
    WAITING = "waiting"
    BLOCKED = "blocked"
    QUICK_WIN = "quick-win"


Priority = Literal["Urgent", "Important", "Normal", "Someday"]

# Context: which "world" a task belongs to. Drives work-mode visibility.
# - "personal" is the default; visible at all hours.
# - "work" is only surfaced during work hours (Mon-Fri 9-5 local) unless an
#   override is active. Matched out of the classifier via explicit `work:` /
#   `@work` keywords + the user's work-signal list (see classifier.md).
Context = Literal["personal", "work"]


# --- Classifier output ------------------------------------------------------


class Classification(BaseModel):
    """Output of the classifier (Haiku). Mirrors ``classifier.md``."""

    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str

    model_config = ConfigDict(extra="ignore")


# --- Per-intent extractor outputs ------------------------------------------


class TaskFields(BaseModel):
    """Fields the extractor produces for a single actionable task.

    Mirrors the ``task`` schema in ``extractor.md`` and the Notion Tasks DB
    columns when ``Type = task``.
    """

    title: str = Field(..., max_length=200)
    priority: Priority = "Normal"
    due_date: date | None = None
    first_step: str | None = None
    recurrence: Recurrence = Recurrence.NONE
    recurrence_ends: date | None = None
    project_link: str | None = None
    parent_task: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    auto_tags: list[AutoTag] = Field(default_factory=list)
    notes: str | None = None
    context: Context = "personal"

    model_config = ConfigDict(extra="ignore")


class BillFields(BaseModel):
    """Fields the extractor produces for a money-owed item.

    Bills live in the same Tasks DB as tasks (Type=bill), so this model
    mirrors the task fields plus bill-specific columns (amount, payee,
    account_ref). The orchestrator routes through ``NotionClient.create_bill``.
    """

    title: str = Field(..., max_length=200)
    amount: Decimal | None = None
    due_date: date | None = None
    payee: str | None = None
    account_ref: str | None = None
    recurrence: Recurrence = Recurrence.NONE
    recurrence_ends: date | None = None
    priority: Priority = "Normal"
    auto_tags: list[AutoTag] = Field(default_factory=list)
    notes: str | None = None
    context: Context = "personal"

    model_config = ConfigDict(extra="ignore")


class ProjectFields(BaseModel):
    """Fields the extractor produces for a multi-step project.

    The extractor decomposes the project into ``decomposed_subtasks`` (just
    titles); the orchestrator creates a parent task with Type=task and then a
    child task per entry with ``parent_task`` set.
    """

    title: str = Field(..., max_length=200)
    first_step: str | None = None
    decomposed_subtasks: list[str] = Field(default_factory=list)
    notes: str | None = None
    auto_tags: list[AutoTag] = Field(default_factory=list)
    priority: Priority = "Normal"
    context: Context = "personal"

    model_config = ConfigDict(extra="ignore")


class BrainDumpFields(BaseModel):
    """A non-actionable thought — append-only to the Brain Dump page."""

    content: str = Field(..., min_length=1, max_length=5000)
    auto_tags: list[AutoTag] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


# --- Webhook request + response models ---------------------------------------


class CaptureRequest(BaseModel):
    """The JSON body the iOS Shortcut posts to ``/capture``.

    Kept deliberately permissive: an iOS Shortcut sends whatever string field
    the user wires up. We accept ``text`` (the canonical name) and tolerate
    surrounding whitespace.
    """

    text: str = Field(..., min_length=1, max_length=5000)

    model_config = ConfigDict(extra="ignore")


# --- Webhook response model --------------------------------------------------


class CapturedItem(BaseModel):
    """One row of the ``captured`` array in the webhook response."""

    type: str
    title: str
    url: str | None = None


class CaptureResponse(BaseModel):
    """The JSON body the iOS Shortcut will read.

    The Shortcut shows ``summary`` as a notification, so it must be a single
    short sentence the user can grok at a glance.
    """

    status: Literal["success", "partial", "error"]
    captured: list[CapturedItem] = Field(default_factory=list)
    summary: str
    error: str | None = None


# --- PWA-facing row projections ---------------------------------------------


class TaskRow(BaseModel):
    """Slim projection of a Notion Tasks-DB row for the PWA to render.

    Includes only the columns the UI needs. The full Notion page is one click
    away via ``url``.
    """

    id: str  # Notion page id (UUID with hyphens)
    title: str
    type: Literal["task", "bill"] = "task"
    status: str = "Active"
    priority: str = "Normal"
    due_date: date | None = None
    first_step: str | None = None
    recurrence: str = "none"
    amount: float | None = None
    payee: str | None = None
    auto_tags: list[str] = Field(default_factory=list)
    parent_task_id: str | None = None
    url: str | None = None
    captured_at: str | None = None  # ISO timestamp from Notion's Captured col
    done_at: str | None = None      # ISO timestamp from Notion's Done at col
    context: Context = "personal"   # "personal" | "work" — drives work-mode filter


class TaskList(BaseModel):
    """Response envelope for the PWA list endpoints."""

    items: list[TaskRow]
    count: int


# --- Project projections (PWA screen 4) -------------------------------------


class ProjectRow(BaseModel):
    """Slim projection of a Notion Projects-DB row, aggregated with progress.

    Subtask counts come from a follow-up query on the Tasks DB filtered by
    the ``Project`` relation. The aggregation is server-side so the PWA
    only needs one round-trip to render the Projects screen.
    """

    id: str
    title: str
    status: str = "Active"
    priority: str | None = None      # Projects DB uses High/Medium/Low — null if unset
    next_action: str | None = None   # from Projects DB "Next action" rich_text
    notes: str | None = None
    url: str | None = None

    # Subtask aggregation
    total_subtasks: int = 0
    done_subtasks: int = 0
    next_incomplete_title: str | None = None  # first non-Done subtask, by name


class ProjectList(BaseModel):
    items: list[ProjectRow]
    count: int


class ProjectDetail(BaseModel):
    """Full project payload for the Project Detail screen.

    ``project`` is the aggregated header info. ``subtasks`` is the full
    Tasks-DB list filtered by this project's relation, sorted so completed
    rows sink to the bottom and Active rows rise to the top.
    """

    project: ProjectRow
    subtasks: list[TaskRow]


# --- PWA inbound mutation payloads ------------------------------------------


class TaskPatch(BaseModel):
    """Partial update for a single Tasks-DB row, sent by the PWA edit flow.

    Every field is optional. ``None`` means "leave unchanged" — to clear a
    value, pass the empty string for text fields or unset relations via a
    dedicated endpoint later. Keeps the surface minimal for the v1 PWA.
    """

    title: str | None = None
    priority: Priority | None = None
    due_date: date | None = None
    first_step: str | None = None
    notes: str | None = None
    recurrence: Recurrence | None = None
    auto_tags: list[AutoTag] | None = None
    amount: float | None = None
    payee: str | None = None
    context: Context | None = None

    model_config = ConfigDict(extra="ignore")
