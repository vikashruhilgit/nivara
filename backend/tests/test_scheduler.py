"""Tests for the session-aware scheduler planning logic.

These tests exercise ``SessionAwareScheduler.plan`` with a fake
``CalendarService`` so we avoid DB + live exchange_calendars lookups.
Assertions cover the acceptance criteria of M2.14:

* AC #1 — market open → in-session tasks planned (5-min indicator, hourly sync)
* AC #2 — market closed → no in-session dispatch
* AC #3 — session close tick → post-close batch planned with half-day flag
* AC #4 — holiday → no in-session dispatch
* AC #5 — half-day → close-time from calendar (not standard close)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from backend.app.scheduling.scheduler import (
    MarketState,
    SessionAwareScheduler,
    compute_market_state,
)


@dataclass
class _FakeHours:
    """Mimic :class:`backend.app.services.calendar.SessionHours`."""

    exchange: str
    session_date: date
    is_open: bool
    open_utc: datetime | None
    close_utc: datetime | None
    is_half_day: bool
    source: str = "library"


class _FakeCalendar:
    """Fake CalendarService that returns canned SessionHours per (exchange, date)."""

    def __init__(self, hours_map: dict[tuple[str, date], _FakeHours]) -> None:
        self._map = hours_map

    async def get_session_hours(self, exchange: str, on: date) -> _FakeHours:
        return self._map[(exchange, on)]


@pytest.fixture(autouse=True)
def _patch_get_calendar() -> Any:
    """Patch ``_get_calendar`` so compute_market_state can resolve the tz without
    loading real exchange_calendars data."""
    fake_cal = SimpleNamespace(tz=UTC)
    with (
        patch(
            "backend.app.scheduling.scheduler._get_calendar",
            return_value=fake_cal,
            create=True,
        ),
        patch(
            "backend.app.services.calendar._get_calendar",
            return_value=fake_cal,
        ),
    ):
        yield


@pytest.mark.asyncio
async def test_market_open_dispatches_in_session_tasks() -> None:
    """AC #1: During open session, 5-min recalc + hourly sync planned at boundary."""
    session_date = date(2026, 4, 14)
    now = datetime(2026, 4, 14, 14, 0, tzinfo=UTC)  # minute 0 → both triggers fire
    hours = _FakeHours(
        exchange="XNYS",
        session_date=session_date,
        is_open=True,
        open_utc=datetime(2026, 4, 14, 13, 30, tzinfo=UTC),
        close_utc=datetime(2026, 4, 14, 20, 0, tzinfo=UTC),
        is_half_day=False,
    )
    cal = _FakeCalendar({("XNYS", session_date): hours})

    scheduler = SessionAwareScheduler(cal, redis=None)  # type: ignore[arg-type]
    tick = await scheduler.plan(now, exchanges=("XNYS",))

    task_names = {p.task_name for p in tick.planned}
    assert "tasks.in_session.recalc_indicators" in task_names
    assert "tasks.in_session.sync_portfolios" in task_names
    assert tick.snapshots[0].state is MarketState.OPEN


@pytest.mark.asyncio
async def test_market_closed_skips_in_session() -> None:
    """AC #2: When market is closed, no in-session tasks are planned."""
    session_date = date(2026, 4, 14)
    now = datetime(2026, 4, 14, 2, 0, tzinfo=UTC)  # pre-open
    hours = _FakeHours(
        exchange="XNYS",
        session_date=session_date,
        is_open=True,
        open_utc=datetime(2026, 4, 14, 13, 30, tzinfo=UTC),
        close_utc=datetime(2026, 4, 14, 20, 0, tzinfo=UTC),
        is_half_day=False,
    )
    cal = _FakeCalendar({("XNYS", session_date): hours})

    scheduler = SessionAwareScheduler(cal, redis=None)  # type: ignore[arg-type]
    tick = await scheduler.plan(now, exchanges=("XNYS",))

    assert tick.planned == ()
    assert tick.snapshots[0].state is MarketState.CLOSED


@pytest.mark.asyncio
async def test_session_close_triggers_post_close_batch() -> None:
    """AC #3: First tick at/after close_utc plans the post-close batch."""
    session_date = date(2026, 4, 14)
    close = datetime(2026, 4, 14, 20, 0, tzinfo=UTC)
    now = close  # JUST_CLOSED window (within 60s after close)
    hours = _FakeHours(
        exchange="XNYS",
        session_date=session_date,
        is_open=True,
        open_utc=datetime(2026, 4, 14, 13, 30, tzinfo=UTC),
        close_utc=close,
        is_half_day=False,
    )
    cal = _FakeCalendar({("XNYS", session_date): hours})

    scheduler = SessionAwareScheduler(cal, redis=None)  # type: ignore[arg-type]
    tick = await scheduler.plan(now, exchanges=("XNYS",))

    names = [p.task_name for p in tick.planned]
    assert "tasks.post_close.run_post_close_batch" in names
    post_close = next(
        p for p in tick.planned if p.task_name == "tasks.post_close.run_post_close_batch"
    )
    assert post_close.kwargs["exchange"] == "XNYS"
    assert post_close.kwargs["is_half_day"] is False


@pytest.mark.asyncio
async def test_holiday_skips_in_session() -> None:
    """AC #4: Holiday day → no in-session dispatch; state=HOLIDAY."""
    session_date = date(2026, 7, 4)
    now = datetime(2026, 7, 4, 17, 0, tzinfo=UTC)
    hours = _FakeHours(
        exchange="XNYS",
        session_date=session_date,
        is_open=False,
        open_utc=None,
        close_utc=None,
        is_half_day=False,
        source="closed",
    )
    cal = _FakeCalendar({("XNYS", session_date): hours})

    scheduler = SessionAwareScheduler(cal, redis=None)  # type: ignore[arg-type]
    tick = await scheduler.plan(now, exchanges=("XNYS",))

    assert tick.planned == ()
    assert tick.snapshots[0].state is MarketState.HOLIDAY


@pytest.mark.asyncio
async def test_half_day_post_close_uses_library_close_time() -> None:
    """AC #5: Half-day close fires post-close batch at actual (early) close."""
    session_date = date(2026, 11, 25)  # day before US Thanksgiving
    # Simulate 1:00 PM ET = 18:00 UTC half-day close
    close = datetime(2026, 11, 25, 18, 0, tzinfo=UTC)
    now = close
    hours = _FakeHours(
        exchange="XNYS",
        session_date=session_date,
        is_open=True,
        open_utc=datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
        close_utc=close,
        is_half_day=True,
    )
    cal = _FakeCalendar({("XNYS", session_date): hours})

    scheduler = SessionAwareScheduler(cal, redis=None)  # type: ignore[arg-type]
    tick = await scheduler.plan(now, exchanges=("XNYS",))

    post_close = next(
        p for p in tick.planned if p.task_name == "tasks.post_close.run_post_close_batch"
    )
    assert post_close.kwargs["is_half_day"] is True
    # Non-standard (not 21:00 UTC/4PM ET) close captured via session_date
    assert post_close.kwargs["session_date"] == "2026-11-25"


@pytest.mark.asyncio
async def test_compute_market_state_open_window() -> None:
    """Sanity: compute_market_state correctly flags OPEN during the window."""
    session_date = date(2026, 4, 14)
    hours = _FakeHours(
        exchange="XNYS",
        session_date=session_date,
        is_open=True,
        open_utc=datetime(2026, 4, 14, 13, 30, tzinfo=UTC),
        close_utc=datetime(2026, 4, 14, 20, 0, tzinfo=UTC),
        is_half_day=False,
    )
    cal = _FakeCalendar({("XNYS", session_date): hours})
    snap = await compute_market_state(
        cal,  # type: ignore[arg-type]
        "XNYS",
        datetime(2026, 4, 14, 15, 0, tzinfo=UTC),
    )
    assert snap.state is MarketState.OPEN
