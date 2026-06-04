"""Tests for ``src/work_mode.py`` — schedule, quiet hours, overrides.

These are pure-function tests with no network and no Anthropic calls. They
cover the load-bearing logic the nag worker depends on:

- :func:`is_within_work_hours` correctness at boundaries (Mon 09:00, Fri 16:59)
- :func:`is_quiet_hours` correctness across the midnight wrap (22:00–06:00)
- Override TTL: expired overrides do not influence state
- The "pause-today" / "start-now" / "end-early" pre-canned helpers produce
  overrides with the expected mode + a TTL in the right ballpark
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src import work_mode
from src.work_mode import (
    LOCAL_TZ,
    FileOverrideStore,
    Override,
    is_quiet_hours,
    is_within_work_hours,
    is_work_mode_active,
)


# --- Schedule predicates ----------------------------------------------------


@pytest.mark.parametrize(
    "iso,expected",
    [
        # Mon 2026-06-01 — Monday
        ("2026-06-01T08:59:00", False),  # 1 min before window
        ("2026-06-01T09:00:00", True),   # window start
        ("2026-06-01T13:00:00", True),   # middle of day
        ("2026-06-01T16:59:00", True),   # last covered minute
        ("2026-06-01T17:00:00", False),  # end-exclusive
        ("2026-06-01T22:00:00", False),  # evening — also quiet
        # Fri 2026-06-05
        ("2026-06-05T15:00:00", True),
        ("2026-06-05T17:00:00", False),
        # Sat 2026-06-06 — weekend, never work
        ("2026-06-06T10:00:00", False),
        ("2026-06-06T14:00:00", False),
        # Sun 2026-06-07
        ("2026-06-07T11:00:00", False),
    ],
)
def test_is_within_work_hours_boundaries(iso: str, expected: bool) -> None:
    local = datetime.fromisoformat(iso).replace(tzinfo=LOCAL_TZ)
    assert is_within_work_hours(local) is expected


@pytest.mark.parametrize(
    "iso,expected",
    [
        # Quiet window: 22:00 inclusive → 06:00 exclusive (wraps midnight)
        ("2026-06-01T21:59:00", False),
        ("2026-06-01T22:00:00", True),    # window start
        ("2026-06-01T23:59:00", True),
        ("2026-06-02T00:00:00", True),    # after midnight
        ("2026-06-02T05:59:00", True),
        ("2026-06-02T06:00:00", False),   # exclusive end
        ("2026-06-02T09:00:00", False),
        ("2026-06-02T17:00:00", False),
    ],
)
def test_is_quiet_hours_wrap(iso: str, expected: bool) -> None:
    local = datetime.fromisoformat(iso).replace(tzinfo=LOCAL_TZ)
    assert is_quiet_hours(local) is expected


# --- Effective state with overrides -----------------------------------------


def _local(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=LOCAL_TZ)


def test_no_override_falls_back_to_schedule() -> None:
    # Saturday — schedule says OFF
    assert is_work_mode_active(_local("2026-06-06T10:00:00")) is False
    # Tuesday 10am — schedule says ON
    assert is_work_mode_active(_local("2026-06-02T10:00:00")) is True


def test_override_work_forces_on_outside_hours() -> None:
    now = _local("2026-06-06T20:00:00")  # Saturday evening
    override = Override(
        mode="work",
        until=(now + timedelta(hours=2)).astimezone(timezone.utc),
        set_at=now.astimezone(timezone.utc),
        reason="start-now",
    )
    assert is_work_mode_active(now, override=override) is True


def test_override_personal_forces_off_inside_hours() -> None:
    now = _local("2026-06-02T14:00:00")  # Tuesday afternoon
    override = Override(
        mode="personal",
        until=(now + timedelta(hours=2)).astimezone(timezone.utc),
        set_at=now.astimezone(timezone.utc),
        reason="pause-today",
    )
    assert is_work_mode_active(now, override=override) is False


def test_expired_override_is_ignored() -> None:
    now = _local("2026-06-06T20:00:00")  # Saturday evening
    expired = Override(
        mode="work",
        until=(now - timedelta(hours=1)).astimezone(timezone.utc),
        set_at=(now - timedelta(hours=3)).astimezone(timezone.utc),
        reason="start-now",
    )
    # Expired → falls back to schedule (Saturday evening = OFF).
    assert is_work_mode_active(now, override=expired) is False
    assert expired.is_active(now) is False


# --- File-backed override store -------------------------------------------


def test_file_store_roundtrip(tmp_path: Path) -> None:
    store = FileOverrideStore(tmp_path / "work_override.json")

    # Empty initially
    assert store.load() is None

    now = datetime.now(timezone.utc)
    o = Override(
        mode="personal",
        until=now + timedelta(hours=4),
        set_at=now,
        reason="pause-today",
    )
    store.save(o)
    loaded = store.load()
    assert loaded is not None
    assert loaded.mode == "personal"
    assert loaded.reason == "pause-today"
    # ISO roundtrip should be lossless to the second
    assert abs((loaded.until - o.until).total_seconds()) < 1.0

    # Clearing writes an empty object, load returns None
    store.save(None)
    assert store.load() is None


def test_file_store_corrupt_file_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "work_override.json"
    path.write_text("this is not json", encoding="utf-8")
    assert FileOverrideStore(path).load() is None


# --- Pre-canned helpers ----------------------------------------------------


def test_pause_today_writes_personal_override(tmp_path: Path, monkeypatch) -> None:
    # Redirect the store to a tmp file
    monkeypatch.setattr(
        work_mode, "get_override_store",
        lambda: FileOverrideStore(tmp_path / "wo.json"),
    )
    override = work_mode.pause_today()
    assert override.mode == "personal"
    assert override.reason == "pause-today"
    # TTL is ≤ 24h (until end of day)
    ttl_hours = (
        override.until - override.set_at
    ).total_seconds() / 3600
    assert 0 < ttl_hours <= 24


def test_start_work_now_writes_work_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        work_mode, "get_override_store",
        lambda: FileOverrideStore(tmp_path / "wo.json"),
    )
    override = work_mode.start_work_now(hours=2)
    assert override.mode == "work"
    assert override.reason == "start-now"
    ttl_hours = (
        override.until - override.set_at
    ).total_seconds() / 3600
    assert 1.9 < ttl_hours < 2.1


# --- Auto-clear of expired overrides on read -------------------------------


def test_get_override_clears_expired(tmp_path: Path, monkeypatch) -> None:
    store = FileOverrideStore(tmp_path / "wo.json")
    monkeypatch.setattr(work_mode, "get_override_store", lambda: store)

    expired = Override(
        mode="work",
        until=datetime.now(timezone.utc) - timedelta(hours=1),
        set_at=datetime.now(timezone.utc) - timedelta(hours=3),
        reason="start-now",
    )
    store.save(expired)
    # On read, expired override should be cleared from disk
    assert work_mode.get_override() is None
    # Verify it was cleared
    raw = json.loads((tmp_path / "wo.json").read_text(encoding="utf-8"))
    assert raw == {}
