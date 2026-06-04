"""Tests for ``src/workers/scheduled_pushes.py`` — time-of-day triggers + dedup."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from src.workers import scheduled_pushes as sp_mod
from src.workers.scheduled_pushes import (
    LOCAL_TZ,
    ScheduledPushes,
    _first_sunday_of_month,
)


# --- _first_sunday_of_month --------------------------------------------------


@pytest.mark.parametrize(
    "input_date,expected",
    [
        (date(2026, 6, 3), date(2026, 6, 7)),    # input mid-month → first Sunday
        (date(2026, 6, 7), date(2026, 6, 7)),    # input IS the first Sunday
        (date(2026, 6, 1), date(2026, 6, 7)),    # Monday June 1 → Sun the 7th
        (date(2026, 11, 1), date(2026, 11, 1)),  # Nov 1 2026 is itself a Sunday
        (date(2026, 12, 31), date(2026, 12, 6)), # late month → still picks 1st Sun
    ],
)
def test_first_sunday_of_month(input_date: date, expected: date) -> None:
    assert _first_sunday_of_month(input_date) == expected


# --- ScheduledPushes time-of-day predicates ---------------------------------


def _make_sched(tmp_path: Path, monkeypatch) -> ScheduledPushes:
    """Build a ScheduledPushes with file-backed state and mocked notion."""
    from src.state_backend import FileStore
    monkeypatch.setattr(
        sp_mod, "_scheduled_store",
        lambda: FileStore(tmp_path / "sp_state.json"),
    )
    monkeypatch.setattr(
        sp_mod.push_mod, "broadcast",
        lambda payload: {"sent": 1, "expired": 0, "failed": 0},
    )
    sp = ScheduledPushes(notion=MagicMock())
    return sp


def _local(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=LOCAL_TZ)


# --- Monday morning ---------------------------------------------------------


@pytest.mark.asyncio
async def test_monday_morning_fires_on_monday_9am(tmp_path: Path, monkeypatch) -> None:
    sp = _make_sched(tmp_path, monkeypatch)
    # Mock notion: one work-context row
    work_row = MagicMock(); work_row.title = "Email Alice"; work_row.context = "work"
    sp.notion.query_all_active_tasks = AsyncMock(return_value=[work_row])

    # Monday 2026-06-01 at 09:30 local
    result = await sp.check_and_fire_all(now=_local("2026-06-01T09:30:00"))
    assert result["mon_morning"] is True
    assert sp.state["mon_morning"] == "2026-06-01"


@pytest.mark.asyncio
async def test_monday_morning_dedupes_within_window(tmp_path: Path, monkeypatch) -> None:
    sp = _make_sched(tmp_path, monkeypatch)
    work_row = MagicMock(); work_row.title = "x"; work_row.context = "work"
    sp.notion.query_all_active_tasks = AsyncMock(return_value=[work_row])
    await sp.check_and_fire_all(now=_local("2026-06-01T09:05:00"))
    result = await sp.check_and_fire_all(now=_local("2026-06-01T09:55:00"))
    assert result["mon_morning"] is False  # already fired today


@pytest.mark.asyncio
async def test_monday_morning_skips_when_no_work_rows(tmp_path: Path, monkeypatch) -> None:
    sp = _make_sched(tmp_path, monkeypatch)
    personal_row = MagicMock(); personal_row.title = "buy milk"; personal_row.context = "personal"
    sp.notion.query_all_active_tasks = AsyncMock(return_value=[personal_row])
    result = await sp.check_and_fire_all(now=_local("2026-06-01T09:30:00"))
    assert result["mon_morning"] is False


@pytest.mark.asyncio
async def test_monday_morning_skips_outside_hour(tmp_path: Path, monkeypatch) -> None:
    sp = _make_sched(tmp_path, monkeypatch)
    work_row = MagicMock(); work_row.title = "x"; work_row.context = "work"
    sp.notion.query_all_active_tasks = AsyncMock(return_value=[work_row])
    # 08:59 — outside window
    result = await sp.check_and_fire_all(now=_local("2026-06-01T08:59:00"))
    assert result["mon_morning"] is False
    # 10:00 — outside window
    result = await sp.check_and_fire_all(now=_local("2026-06-01T10:00:00"))
    assert result["mon_morning"] is False


@pytest.mark.asyncio
async def test_monday_morning_skips_other_weekdays(tmp_path: Path, monkeypatch) -> None:
    sp = _make_sched(tmp_path, monkeypatch)
    work_row = MagicMock(); work_row.title = "x"; work_row.context = "work"
    sp.notion.query_all_active_tasks = AsyncMock(return_value=[work_row])
    # Tuesday at 9:30am
    result = await sp.check_and_fire_all(now=_local("2026-06-02T09:30:00"))
    assert result["mon_morning"] is False


# --- Sunday review nudge ----------------------------------------------------


@pytest.mark.asyncio
async def test_sunday_review_fires_at_6pm(tmp_path: Path, monkeypatch) -> None:
    sp = _make_sched(tmp_path, monkeypatch)
    sp.notion.query_review_queue = AsyncMock(return_value=[MagicMock(), MagicMock()])
    sp.notion.query_needs_date = AsyncMock(return_value=[MagicMock()])
    result = await sp.check_and_fire_all(now=_local("2026-06-07T18:15:00"))
    assert result["sun_review"] is True
    assert sp.state["sun_review"] == "2026-06-07"


@pytest.mark.asyncio
async def test_sunday_review_skips_when_nothing_to_triage(tmp_path: Path, monkeypatch) -> None:
    sp = _make_sched(tmp_path, monkeypatch)
    sp.notion.query_review_queue = AsyncMock(return_value=[])
    sp.notion.query_needs_date = AsyncMock(return_value=[])
    result = await sp.check_and_fire_all(now=_local("2026-06-07T18:15:00"))
    assert result["sun_review"] is False


@pytest.mark.asyncio
async def test_sunday_review_dedupes(tmp_path: Path, monkeypatch) -> None:
    sp = _make_sched(tmp_path, monkeypatch)
    sp.notion.query_review_queue = AsyncMock(return_value=[MagicMock()])
    sp.notion.query_needs_date = AsyncMock(return_value=[])
    await sp.check_and_fire_all(now=_local("2026-06-07T18:05:00"))
    result = await sp.check_and_fire_all(now=_local("2026-06-07T18:55:00"))
    assert result["sun_review"] is False


# --- Monthly Parked resurface ----------------------------------------------


@pytest.mark.asyncio
async def test_monthly_parked_fires_first_sunday_11am(tmp_path: Path, monkeypatch) -> None:
    sp = _make_sched(tmp_path, monkeypatch)
    rows = []
    for i in range(6):  # 6 parked rows → above threshold
        r = MagicMock(); r.title = f"x{i}"; r.captured_at = "2025-05-01T00:00:00+00:00"
        rows.append(r)
    sp.notion.query_parked = AsyncMock(return_value=rows)
    # June 7 2026 = first Sunday of June 2026, 11:15 local
    result = await sp.check_and_fire_all(now=_local("2026-06-07T11:15:00"))
    assert result["monthly_parked"] is True
    assert sp.state["monthly_parked"] == "2026-06"


@pytest.mark.asyncio
async def test_monthly_parked_skips_below_threshold(tmp_path: Path, monkeypatch) -> None:
    sp = _make_sched(tmp_path, monkeypatch)
    rows = [MagicMock() for _ in range(4)]  # 4 < 5 threshold
    for r in rows:
        r.captured_at = "2025-05-01T00:00:00+00:00"
    sp.notion.query_parked = AsyncMock(return_value=rows)
    result = await sp.check_and_fire_all(now=_local("2026-06-07T11:15:00"))
    assert result["monthly_parked"] is False


@pytest.mark.asyncio
async def test_monthly_parked_skips_non_first_sunday(tmp_path: Path, monkeypatch) -> None:
    sp = _make_sched(tmp_path, monkeypatch)
    sp.notion.query_parked = AsyncMock(return_value=[MagicMock() for _ in range(10)])
    # Second Sunday of June 2026 = 14th
    result = await sp.check_and_fire_all(now=_local("2026-06-14T11:15:00"))
    assert result["monthly_parked"] is False
