"""Tests for ``src/streak.py`` — compute_streak + next_milestone_above."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.streak import LOCAL_TZ, STREAK_MILESTONES, compute_streak, next_milestone_above


def _row(done_at: datetime | None) -> SimpleNamespace:
    """Minimal stand-in for TaskRow — only `done_at` matters here."""
    return SimpleNamespace(
        done_at=done_at.astimezone(timezone.utc).isoformat() if done_at else None
    )


# --- compute_streak ---------------------------------------------------------


def test_empty_rows_returns_zero() -> None:
    assert compute_streak([]) == 0


def test_no_done_today_returns_zero() -> None:
    # Done two days ago — broken chain.
    two_days_ago = datetime.now(LOCAL_TZ) - timedelta(days=2)
    assert compute_streak([_row(two_days_ago)]) == 0


def test_done_today_returns_one() -> None:
    now = datetime.now(LOCAL_TZ)
    assert compute_streak([_row(now)]) == 1


def test_three_day_unbroken() -> None:
    now = datetime.now(LOCAL_TZ)
    rows = [_row(now), _row(now - timedelta(days=1)), _row(now - timedelta(days=2))]
    assert compute_streak(rows) == 3


def test_gap_breaks_streak() -> None:
    now = datetime.now(LOCAL_TZ)
    # today and 2 days ago but NOT yesterday → chain breaks at the gap
    rows = [_row(now), _row(now - timedelta(days=2))]
    assert compute_streak(rows) == 1


def test_invalid_done_at_skipped() -> None:
    rows = [SimpleNamespace(done_at="not-a-date"), _row(datetime.now(LOCAL_TZ))]
    assert compute_streak(rows) == 1


# --- next_milestone_above ---------------------------------------------------


@pytest.mark.parametrize(
    "streak,last_fired,expected",
    [
        (0, 0, None),
        (6, 0, None),       # below the 7-day floor
        (7, 0, 7),          # crosses 7 for the first time
        (8, 7, None),       # 7 already fired, 14 not yet reached
        (14, 7, 14),        # crosses 14
        (29, 14, None),     # nothing new
        (30, 14, 30),       # crosses 30
        (31, 30, None),
        # Fresh user jumps straight to 14 (e.g. backfill) → fire 14, not 7.
        (14, 0, 14),
        (30, 0, 30),
    ],
)
def test_next_milestone_above(streak: int, last_fired: int, expected: int | None) -> None:
    assert next_milestone_above(streak, last_fired) == expected


def test_milestones_are_immutable_and_sorted() -> None:
    assert STREAK_MILESTONES == [7, 14, 30]
