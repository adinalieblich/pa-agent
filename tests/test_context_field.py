"""Tests for the new ``context`` field across models + prompt content.

These don't hit Anthropic — they verify schema wiring and that the prompt
explicitly mentions every work-signal token (so a future edit can't silently
drop one).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models import BillFields, ProjectFields, TaskFields, TaskPatch, TaskRow

PROMPT_DIR = Path(__file__).resolve().parents[1] / "src" / "prompts"

WORK_SIGNALS = ["PO", "INVOICE", "CRM", "ACME", "ALICE", "BOB", "CAROL"]


# --- Schema wiring ----------------------------------------------------------


def test_task_fields_context_defaults_to_personal() -> None:
    task = TaskFields(title="take meds")
    assert task.context == "personal"


def test_task_fields_accepts_work() -> None:
    task = TaskFields(title="email alice", context="work")
    assert task.context == "work"


def test_task_fields_rejects_unknown_context() -> None:
    with pytest.raises(Exception):
        TaskFields(title="x", context="other")  # type: ignore[arg-type]


def test_bill_fields_context_default() -> None:
    bill = BillFields(title="rent")
    assert bill.context == "personal"


def test_project_fields_context_default() -> None:
    project = ProjectFields(title="ship pa-agent")
    assert project.context == "personal"


def test_task_row_context_default() -> None:
    row = TaskRow(id="abc", title="x")
    assert row.context == "personal"


def test_task_patch_context_is_optional_and_none_by_default() -> None:
    patch = TaskPatch()
    assert patch.context is None
    # When set, accepts both literals
    assert TaskPatch(context="work").context == "work"
    assert TaskPatch(context="personal").context == "personal"


# --- Prompt content: every signal must appear in the extractor rules -------


def test_extractor_prompt_mentions_every_work_signal() -> None:
    text = (PROMPT_DIR / "extractor.md").read_text(encoding="utf-8")
    for signal in WORK_SIGNALS:
        assert signal in text, f"work signal {signal!r} missing from extractor.md"


def test_extractor_prompt_documents_context_field() -> None:
    text = (PROMPT_DIR / "extractor.md").read_text(encoding="utf-8")
    # The schema blocks for task + bill + project all list `context`
    assert text.count('"context": "personal | work"') >= 3, (
        "context field must appear in task, bill and project schemas"
    )


def test_classifier_prompt_warns_about_work_signals() -> None:
    """Classifier should explicitly note work-signal awareness so it doesn't misroute."""
    text = (PROMPT_DIR / "classifier.md").read_text(encoding="utf-8")
    assert "work signal" in text.lower() or "Work signals" in text
