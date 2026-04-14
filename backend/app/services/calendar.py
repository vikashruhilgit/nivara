"""Market calendar service.

Wraps the ``exchange_calendars`` library (MIC codes: XNYS, XNAS, XBOM) and
merges with the ``calendar_overrides`` table. Override rows always win over
the library — this lets us patch missing/incorrect holidays (e.g. Muhurat
trading sessions, emergency closures) without waiting for a library release.

Public API
----------
* :meth:`CalendarService.is_market_open` — bool (ts → open?)
* :meth:`CalendarService.get_session_hours` — open/close times for a date
* :meth:`CalendarService.next_session_close` — next close after a ts
* :meth:`CalendarService.record_unexpected_closed` — auto-create override
  when a broker reports a market as closed on a date the library thought
  was open.

All timestamps in/out are timezone-aware UTC (``datetime`` with tzinfo).
Naive datetimes are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from functools import lru_cache
from typing import TYPE_CHECKING

import exchange_calendars as xcals
from backend.app.models.calendar_overrides import CalendarOverride
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from exchange_calendars import ExchangeCalendar

# Accepted MIC codes. Anything else raises ValueError at the edge.
SUPPORTED_EXCHANGES: frozenset[str] = frozenset({"XNYS", "XNAS", "XBOM"})

# Seed-style → MIC normalisation. The ``instruments.exchange`` column stores
# seed-style codes (``NYSE``/``NASDAQ``/``BSE``/``NSE``); callers that pass
# those are auto-normalised. NSE is mapped to XBOM because India's two major
# exchanges share the same session calendar; XBOM is what exchange_calendars
# ships.
_SEED_TO_MIC: dict[str, str] = {
    "NYSE": "XNYS",
    "NASDAQ": "XNAS",
    "ARCX": "XNYS",
    "BATS": "XNYS",
    "BSE": "XBOM",
    "NSE": "XBOM",
}


def normalize_exchange(value: str) -> str:
    """Return the canonical MIC code, raising ``ValueError`` on unsupported input.

    Accepts both MIC codes and seed-style codes. Case-insensitive.
    """
    if not value:
        raise ValueError("exchange is required")
    upper = value.strip().upper()
    if upper in SUPPORTED_EXCHANGES:
        return upper
    mapped = _SEED_TO_MIC.get(upper)
    if mapped is None:
        raise ValueError(f"unsupported exchange: {value!r}")
    return mapped


@lru_cache(maxsize=8)
def _get_calendar(exchange_mic: str) -> ExchangeCalendar:
    """Cached ``exchange_calendars`` lookup keyed on the MIC code."""
    return xcals.get_calendar(exchange_mic)


def _ensure_utc(ts: datetime) -> datetime:
    """Require a tz-aware datetime; convert to UTC if needed."""
    if ts.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (use UTC)")
    return ts.astimezone(UTC)


@dataclass(frozen=True)
class SessionHours:
    """Internal result of ``get_session_hours`` — service-layer representation."""

    exchange: str
    session_date: date
    is_open: bool
    open_utc: datetime | None
    close_utc: datetime | None
    is_half_day: bool
    source: str  # 'override' | 'library' | 'closed'

    @property
    def open_local(self) -> time | None:
        if self.open_utc is None:
            return None
        cal = _get_calendar(self.exchange)
        return self.open_utc.astimezone(cal.tz).time()

    @property
    def close_local(self) -> time | None:
        if self.close_utc is None:
            return None
        cal = _get_calendar(self.exchange)
        return self.close_utc.astimezone(cal.tz).time()


class CalendarService:
    """Market calendar queries with DB override merge."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---------------- override lookup ----------------

    async def _override_for(self, exchange: str, on: date) -> CalendarOverride | None:
        stmt = select(CalendarOverride).where(
            CalendarOverride.exchange == exchange,
            CalendarOverride.date == on,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # ---------------- public API ----------------

    async def is_market_open(self, exchange: str, ts_utc: datetime) -> bool:
        """Return ``True`` iff the exchange is in a trading session at ``ts_utc``.

        Override wins: a matching override row with ``is_open=False`` forces a
        False result regardless of the library; ``is_open=True`` forces a True
        result only when within the library's session window (overrides cannot
        extend session hours — only close or reopen a full day).
        """
        mic = normalize_exchange(exchange)
        ts = _ensure_utc(ts_utc)
        session_date = ts.astimezone(_get_calendar(mic).tz).date()

        override = await self._override_for(mic, session_date)
        if override is not None and not override.is_open:
            return False

        cal = _get_calendar(mic)
        try:
            is_session = bool(cal.is_trading_minute(ts))
        except Exception:
            # Dates far outside the loaded range — safest answer is closed.
            is_session = False

        if override is not None and override.is_open:
            # Only honour a "force open" override if the library thinks this
            # is a valid session minute (prevents overrides from inventing
            # 24h trading). For a full-day reopen we'd need to combine with a
            # get_session_hours override; out of scope for the MVP.
            return is_session

        return is_session

    async def get_session_hours(self, exchange: str, on: date) -> SessionHours:
        """Return open/close times for ``on``, honouring overrides.

        Half-day sessions and Muhurat-style special sessions are reflected in
        the library's minute data (``session_open`` / ``session_close``).
        """
        mic = normalize_exchange(exchange)
        override = await self._override_for(mic, on)

        if override is not None and not override.is_open:
            return SessionHours(
                exchange=mic,
                session_date=on,
                is_open=False,
                open_utc=None,
                close_utc=None,
                is_half_day=False,
                source="override",
            )

        cal = _get_calendar(mic)
        if not cal.is_session(on):
            # Library says closed, and no "force open" override applies.
            return SessionHours(
                exchange=mic,
                session_date=on,
                is_open=False,
                open_utc=None,
                close_utc=None,
                is_half_day=False,
                source="closed",
            )

        open_utc = cal.session_open(on).to_pydatetime().astimezone(UTC)
        close_utc = cal.session_close(on).to_pydatetime().astimezone(UTC)

        # Half-day detection: compare today's session length to the calendar's
        # typical daily session length. Anything significantly shorter (>= 60
        # minutes below typical) is flagged as a half-day / special session.
        minutes = (close_utc - open_utc).total_seconds() / 60.0
        is_half_day = minutes < (_typical_session_minutes(mic) - 60)

        source = "override" if override is not None and override.is_open else "library"
        return SessionHours(
            exchange=mic,
            session_date=on,
            is_open=True,
            open_utc=open_utc,
            close_utc=close_utc,
            is_half_day=is_half_day,
            source=source,
        )

    async def next_session_close(self, exchange: str, ts_utc: datetime) -> datetime:
        """Return the next session close strictly at or after ``ts_utc``.

        If the market is currently open the result is today's close (or half-
        day close). Otherwise it is the next trading session's close.
        """
        mic = normalize_exchange(exchange)
        ts = _ensure_utc(ts_utc)
        cal = _get_calendar(mic)

        # Walk forward until we find a session that is not vetoed by an
        # override and whose close is >= ts.
        candidate = ts.astimezone(cal.tz).date()
        # Hard safety bound: at most ~2 weeks of empty days before we give up.
        for _ in range(20):
            hours = await self.get_session_hours(mic, candidate)
            if hours.is_open and hours.close_utc is not None and hours.close_utc >= ts:
                return hours.close_utc
            candidate = _add_days(candidate, 1)
        raise RuntimeError(
            f"no upcoming session close found for {mic} within 20 days of {ts.isoformat()}"
        )

    # ---------------- auto-override (subtask 3) ----------------

    async def record_unexpected_closed(
        self,
        exchange: str,
        on: date,
        reason: str,
    ) -> CalendarOverride:
        """Insert / upsert a ``calendar_overrides`` row when the broker reports
        the market closed on a date our library thought was open.

        Idempotent — repeated calls with the same ``(exchange, date)`` update
        the existing row rather than failing on the unique constraint.

        Returns the persisted ``CalendarOverride``.
        """
        mic = normalize_exchange(exchange)

        # Dialect-aware upsert: Postgres uses ON CONFLICT; everything else
        # (SQLite in tests) goes through a SELECT-then-INSERT/UPDATE path.
        # The caller controls the transaction boundary — we only ``flush``.
        dialect = self._session.bind.dialect.name if self._session.bind else ""
        if dialect == "postgresql":
            stmt = (
                pg_insert(CalendarOverride)
                .values(exchange=mic, date=on, is_open=False, reason=reason)
                .on_conflict_do_update(
                    index_elements=[CalendarOverride.exchange, CalendarOverride.date],
                    set_={"is_open": False, "reason": reason},
                )
                .returning(CalendarOverride)
            )
            try:
                result = await self._session.execute(stmt)
                row = result.scalar_one()
                await self._session.flush()
                return row
            except IntegrityError:
                # Extremely unlikely given ON CONFLICT, but defensive: fall through.
                await self._session.rollback()

        existing = await self._override_for(mic, on)
        if existing is not None:
            existing.is_open = False
            existing.reason = reason
            await self._session.flush()
            return existing
        new = CalendarOverride(
            exchange=mic,
            date=on,
            is_open=False,
            reason=reason,
        )
        self._session.add(new)
        await self._session.flush()
        return new


# ---------------- helpers ----------------


def _add_days(d: date, n: int) -> date:
    from datetime import timedelta

    return d + timedelta(days=n)


def _typical_session_minutes(mic: str) -> float:
    """Rough typical trading minutes per session for half-day detection."""
    return {
        "XNYS": 390.0,  # 9:30–16:00 ET = 6.5h
        "XNAS": 390.0,
        "XBOM": 375.0,  # 9:15–15:30 IST = 6h 15m
    }.get(mic, 390.0)
