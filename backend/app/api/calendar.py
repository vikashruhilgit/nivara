"""Market calendar API routes.

Exposes:

* ``GET /api/calendar/is-open?exchange=XNYS&ts_utc=...`` — boolean check.
* ``GET /api/calendar/session-hours?exchange=XNYS&date=YYYY-MM-DD`` —
  full open/close for a session date (includes half-day flag).
* ``GET /api/calendar/next-close?exchange=XNYS[&ts_utc=...]`` — next
  session close; defaults to "now" when ``ts_utc`` is omitted.

All routes require an authenticated user (bearer token).
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as date_cls

from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.models.users import User
from backend.app.schemas.calendar import IsOpenOut, NextCloseOut, SessionHoursOut
from backend.app.services.calendar import CalendarService, normalize_exchange
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _calendar_service(session: AsyncSession = Depends(get_session)) -> CalendarService:
    return CalendarService(session=session)


def _require_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ts_utc must be timezone-aware (include tz offset, e.g. +00:00)",
        )
    return ts.astimezone(UTC)


def _normalize_or_400(exchange: str) -> str:
    try:
        return normalize_exchange(exchange)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/is-open", response_model=IsOpenOut)
async def is_open(
    exchange: str = Query(..., description="MIC code or seed-style exchange code."),
    ts_utc: datetime = Query(..., description="Timezone-aware UTC timestamp."),
    svc: CalendarService = Depends(_calendar_service),
    _user: User = Depends(get_current_user),
) -> IsOpenOut:
    """Return whether the exchange is currently tradeable at ``ts_utc``."""
    mic = _normalize_or_400(exchange)
    ts = _require_utc(ts_utc)
    # Determine source by checking override presence — cheap extra query.
    override = await svc._override_for(mic, ts.date())  # noqa: SLF001 (intentional)
    is_op = await svc.is_market_open(mic, ts)
    source = "override" if override is not None else "library"
    return IsOpenOut(exchange=mic, ts_utc=ts, is_open=is_op, source=source)


@router.get("/session-hours", response_model=SessionHoursOut)
async def session_hours(
    exchange: str = Query(...),
    date: date_cls = Query(..., description="Session date (YYYY-MM-DD)."),
    svc: CalendarService = Depends(_calendar_service),
    _user: User = Depends(get_current_user),
) -> SessionHoursOut:
    """Return open/close for a session date."""
    mic = _normalize_or_400(exchange)
    hours = await svc.get_session_hours(mic, date)
    return SessionHoursOut(
        exchange=hours.exchange,
        session_date=hours.session_date,
        is_open=hours.is_open,
        open_utc=hours.open_utc,
        close_utc=hours.close_utc,
        open_local=hours.open_local,
        close_local=hours.close_local,
        is_half_day=hours.is_half_day,
        source=hours.source,
    )


@router.get("/next-close", response_model=NextCloseOut)
async def next_close(
    exchange: str = Query(...),
    ts_utc: datetime | None = Query(
        None,
        description="Reference timestamp (tz-aware UTC). Defaults to now.",
    ),
    svc: CalendarService = Depends(_calendar_service),
    _user: User = Depends(get_current_user),
) -> NextCloseOut:
    """Return the next session close at/after ``ts_utc`` (default: now)."""
    mic = _normalize_or_400(exchange)
    ts = _require_utc(ts_utc) if ts_utc is not None else datetime.now(UTC)
    try:
        next_close_utc = await svc.next_session_close(mic, ts)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    hours = await svc.get_session_hours(mic, next_close_utc.date())
    return NextCloseOut(
        exchange=mic,
        ts_utc=ts,
        next_close_utc=next_close_utc,
        is_half_day=hours.is_half_day,
    )
