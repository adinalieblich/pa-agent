"""The brain.

Takes raw voice text, classifies it, extracts structured fields, routes to the
right integration, and returns a confirmation summary.

v3 routing:

    classify (Haiku)
        ├── task        → extract → NotionClient.create_task
        ├── bill        → extract → NotionClient.create_bill
        ├── project     → extract → NotionClient.create_project_with_subtasks
        ├── brain_dump  → extract → NotionClient.append_to_brain_dump
        └── multi       → extract → for each item: recurse single-intent path

A single confidence-threshold rule applies to every intent: if the extractor's
``confidence`` falls below ``settings.review_confidence_threshold`` (default
0.7), the orchestrator pushes ``"review"`` into the row's ``auto_tags`` so the
user can sweep low-quality captures from a single Notion view later.

Errors are caught and surfaced as ``CaptureResponse(status="error" or
"partial")`` rather than exceptions — the iOS Shortcut needs *something* with
a ``summary`` field on the unhappy path. ``partial`` is reserved for multi-
intent captures where some items succeeded and others failed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ValidationError

from ._tz import LOCAL_TZ
from .config import Settings, get_settings
from .integrations.anthropic_client import AnthropicClient, AnthropicError
from .integrations.notion_client import NotionClient, NotionError
from .models import (
    AutoTag,
    BillFields,
    BrainDumpFields,
    CaptureResponse,
    CapturedItem,
    Classification,
    Intent,
    ProjectFields,
    TaskFields,
)
from .utils.logging import get_logger

log = get_logger(__name__)


class Orchestrator:
    """Holds the per-process integration clients so we don't reconnect per call."""

    def __init__(
        self,
        anthropic: AnthropicClient | None = None,
        notion: NotionClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.anthropic = anthropic or AnthropicClient(self.settings)
        self.notion = notion or NotionClient(self.settings)

    # --- Public entry point ---------------------------------------------

    async def handle(self, voice_text: str) -> CaptureResponse:
        """Run the full pipeline for one voice capture."""
        voice_text = voice_text.strip()
        if not voice_text:
            return CaptureResponse(
                status="error",
                summary="Empty voice input — nothing captured.",
                error="empty_input",
            )

        log.info("orchestrator.start", chars=len(voice_text))
        log.debug("orchestrator.text", text=voice_text)

        classification = await self._classify(voice_text)
        if classification is None:
            return CaptureResponse(
                status="error",
                summary="Couldn't understand that — please try again.",
                error="classify_failed",
            )

        return await self._route(classification.intent, voice_text)

    # --- Classification ------------------------------------------------

    async def _classify(self, voice_text: str) -> Classification | None:
        try:
            raw = await self.anthropic.classify(voice_text)
            classification = Classification.model_validate(raw)
        except (AnthropicError, ValidationError) as e:
            log.error("orchestrator.classify_failed", error=str(e))
            return None
        log.info(
            "orchestrator.classified",
            intent=classification.intent.value,
            confidence=classification.confidence,
        )
        return classification

    # --- Routing -------------------------------------------------------

    async def _route(self, intent: Intent, voice_text: str) -> CaptureResponse:
        if intent is Intent.TASK:
            return await self._handle_task(voice_text)
        if intent is Intent.BILL:
            return await self._handle_bill(voice_text)
        if intent is Intent.PROJECT:
            return await self._handle_project(voice_text)
        if intent is Intent.BRAIN_DUMP:
            return await self._handle_brain_dump(voice_text)
        if intent is Intent.MULTI:
            return await self._handle_multi(voice_text)
        # Unreachable but keeps mypy + future-proofs against enum additions.
        return CaptureResponse(
            status="error",
            summary=f"Unknown intent: {intent}.",
            error=f"unknown_intent: {intent}",
        )

    # --- Per-intent handlers -------------------------------------------

    async def _handle_task(self, voice_text: str) -> CaptureResponse:
        raw = await self._extract(voice_text, Intent.TASK.value)
        if raw is None:
            return _extract_failure("task")
        try:
            task = TaskFields.model_validate(raw)
        except ValidationError as e:
            log.error("orchestrator.task_validate_failed", error=str(e))
            return _extract_failure("task")

        self._apply_review_tag(raw, task.auto_tags)

        try:
            page = await self.notion.create_task(task)
        except NotionError as e:
            return _notion_failure(e)

        return CaptureResponse(
            status="success",
            captured=[CapturedItem(type="task", title=task.title, url=page.get("url"))],
            summary=_task_summary(task),
        )

    async def _handle_bill(self, voice_text: str) -> CaptureResponse:
        raw = await self._extract(voice_text, Intent.BILL.value)
        if raw is None:
            return _extract_failure("bill")
        try:
            bill = BillFields.model_validate(raw)
        except ValidationError as e:
            log.error("orchestrator.bill_validate_failed", error=str(e))
            return _extract_failure("bill")

        self._apply_review_tag(raw, bill.auto_tags)

        try:
            page = await self.notion.create_bill(bill)
        except NotionError as e:
            return _notion_failure(e)

        return CaptureResponse(
            status="success",
            captured=[CapturedItem(type="bill", title=bill.title, url=page.get("url"))],
            summary=_bill_summary(bill),
        )

    async def _handle_project(self, voice_text: str) -> CaptureResponse:
        raw = await self._extract(voice_text, Intent.PROJECT.value)
        if raw is None:
            return _extract_failure("project")
        try:
            project = ProjectFields.model_validate(raw)
        except ValidationError as e:
            log.error("orchestrator.project_validate_failed", error=str(e))
            return _extract_failure("project")

        self._apply_review_tag(raw, project.auto_tags)

        try:
            parent, children = await self.notion.create_project_with_subtasks(project)
        except NotionError as e:
            return _notion_failure(e)

        captured = [
            CapturedItem(type="project", title=project.title, url=parent.get("url")),
            *[
                CapturedItem(type="subtask", title=title, url=child.get("url"))
                for title, child in zip(project.decomposed_subtasks, children, strict=False)
            ],
        ]
        return CaptureResponse(
            status="success",
            captured=captured,
            summary=f"Created project: {project.title} (+ {len(children)} subtasks)",
        )

    async def _handle_brain_dump(self, voice_text: str) -> CaptureResponse:
        raw = await self._extract(voice_text, Intent.BRAIN_DUMP.value)
        if raw is None:
            return _extract_failure("brain_dump")
        try:
            dump = BrainDumpFields.model_validate(raw)
        except ValidationError as e:
            log.error("orchestrator.brain_dump_validate_failed", error=str(e))
            return _extract_failure("brain_dump")

        self._apply_review_tag(raw, dump.auto_tags)

        try:
            await self.notion.append_to_brain_dump(dump)
        except NotionError as e:
            return _notion_failure(e)

        preview = dump.content[:60] + ("…" if len(dump.content) > 60 else "")
        return CaptureResponse(
            status="success",
            captured=[CapturedItem(type="brain_dump", title=preview)],
            summary=f"Captured in Brain Dump: {preview}",
        )

    async def _handle_multi(self, voice_text: str) -> CaptureResponse:
        """Decompose into single-intent fragments and dispatch each.

        Strategy: ask the extractor (with intent=multi) to return an ``items``
        array, then for each item, run the single-intent path on its
        ``voice_fragment``. Aggregate the resulting ``captured[]`` so the
        phone sees one consolidated summary.
        """
        raw = await self._extract(voice_text, Intent.MULTI.value)
        if raw is None or not isinstance(raw.get("items"), list):
            return _extract_failure("multi")

        items = [i for i in raw["items"] if isinstance(i, dict)]
        if not items:
            return CaptureResponse(
                status="error",
                summary="Multi-intent extract returned no items.",
                error="multi_empty",
            )

        captured: list[CapturedItem] = []
        failures: list[str] = []
        for item in items:
            sub_intent_str = item.get("intent")
            fragment = (item.get("voice_fragment") or "").strip()
            if not sub_intent_str or not fragment:
                continue
            try:
                sub_intent = Intent(sub_intent_str)
            except ValueError:
                failures.append(f"unknown sub-intent: {sub_intent_str}")
                continue
            if sub_intent is Intent.MULTI:
                failures.append("nested multi not supported")
                continue

            sub_response = await self._route(sub_intent, fragment)
            if sub_response.status == "success":
                captured.extend(sub_response.captured)
            else:
                failures.append(f"{sub_intent.value}: {sub_response.error or sub_response.summary}")

        if captured and not failures:
            return CaptureResponse(
                status="success",
                captured=captured,
                summary=_multi_summary(captured),
            )
        if captured and failures:
            return CaptureResponse(
                status="partial",
                captured=captured,
                summary=_multi_summary(captured) + f" (with {len(failures)} failure(s))",
                error="; ".join(failures),
            )
        return CaptureResponse(
            status="error",
            summary="Multi-intent capture failed entirely.",
            error="; ".join(failures) or "no successful items",
        )

    # --- Shared helpers ------------------------------------------------

    async def _extract(self, voice_text: str, intent: str) -> dict[str, Any] | None:
        try:
            return await self.anthropic.extract(
                voice_text, intent, now=datetime.now(LOCAL_TZ)
            )
        except AnthropicError as e:
            log.error("orchestrator.extract_failed", intent=intent, error=str(e))
            return None

    def _apply_review_tag(self, raw: dict[str, Any], auto_tags: list[AutoTag]) -> None:
        """Push ``review`` into the tag list if extractor confidence is low.

        Mutates ``auto_tags`` in place. The extracted Pydantic model already
        copied the list from ``raw``, so the mutation flows through to the
        Notion property payload. Safe to call even when ``raw`` doesn't have
        a confidence key — defaults to 1.0 (no flag).
        """
        confidence = raw.get("confidence", 1.0)
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
        if confidence < self.settings.review_confidence_threshold:
            if AutoTag.REVIEW not in auto_tags:
                auto_tags.append(AutoTag.REVIEW)
            log.info(
                "orchestrator.review_tagged",
                confidence=confidence,
                threshold=self.settings.review_confidence_threshold,
            )


# --- Module-level helpers ---------------------------------------------------


def _task_summary(task: TaskFields) -> str:
    # Surface context in the iOS Shortcut confirmation so the user immediately
    # sees whether the work-mode classifier hit. Personal is the default — no
    # need to mention it.
    context_word = "work " if task.context == "work" else ""
    pieces = [f"Created {task.priority.lower()} {context_word}task: {task.title}"]
    if task.due_date is not None:
        pieces.append(f"(due {task.due_date.isoformat()})")
    if task.recurrence.value != "none":
        pieces.append(f"[{task.recurrence.value}]")
    return " ".join(pieces)


def _bill_summary(bill: BillFields) -> str:
    context_word = "work " if bill.context == "work" else ""
    pieces = [f"Created {context_word}bill: {bill.title}"]
    if bill.amount is not None:
        pieces.append(f"(${bill.amount:.2f})")
    if bill.due_date is not None:
        pieces.append(f"due {bill.due_date.isoformat()}")
    if bill.recurrence.value != "none":
        pieces.append(f"[{bill.recurrence.value}]")
    return " ".join(pieces)


def _multi_summary(items: list[CapturedItem]) -> str:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.type] = counts.get(item.type, 0) + 1
    parts = [f"{n} {typ}{'s' if n > 1 else ''}" for typ, n in counts.items()]
    return "Captured: " + ", ".join(parts)


def _extract_failure(intent: str) -> CaptureResponse:
    return CaptureResponse(
        status="error",
        summary=f"Couldn't extract {intent} details — please rephrase.",
        error=f"extract_failed: {intent}",
    )


def _notion_failure(e: NotionError) -> CaptureResponse:
    log.error("orchestrator.notion_failed", error=str(e))
    return CaptureResponse(
        status="error",
        summary="Couldn't save to Notion — check the integration.",
        error=f"notion_failed: {e}",
    )


# --- Module-level singleton --------------------------------------------------

_default: Orchestrator | None = None


def _get_default() -> Orchestrator:
    global _default
    if _default is None:
        _default = Orchestrator()
    return _default


async def handle_voice_text(voice_text: str) -> CaptureResponse:
    """Module-level convenience used by the CLI and the webhook."""
    return await _get_default().handle(voice_text)
