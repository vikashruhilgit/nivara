"""Pydantic schemas for the market calendar API.

The internal service layer works with MIC codes (``XNYS``, ``XNAS``, ``XBOM``)
since that is what ``exchange_calendars`` speaks. API requests and responses
use the same canonical MIC form; callers that only know the seed-style codes
(``NYSE``/``NASDAQ``/``BSE``) can normalise via the service.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field


class IsOpenOut(BaseModel):
    """Result of ``is_market_open`` — whether the exchange is tradeable now."""

    model_config = ConfigDict(from_attributes=True)

    exchange: str = Field(..., description="MIC code, e.g. XNYS / XNAS / XBOM.")
    ts_utc: datetime = Field(..., description="The evaluated timestamp (UTC).")
    is_open: bool
    source: str = Field(
        ...,
        description="Which source decided the result: 'override' or 'library'.",
    )


class SessionHoursOut(BaseModel):
    """Open/close times for a given session date."""

    model_config = ConfigDict(from_attributes=True)

    exchange: str
    session_date: date_cls
    is_open: bool
    open_utc: datetime | None = None
    close_utc: datetime | None = None
    open_local: time | None = None
    close_local: time | None = None
    is_half_day: bool = False
    source: str = Field(..., description="'override' | 'library' | 'closed'")


class NextCloseOut(BaseModel):
    """Next session close time for an exchange."""

    model_config = ConfigDict(from_attributes=True)

    exchange: str
    ts_utc: datetime = Field(..., description="Reference timestamp used for the lookup.")
    next_close_utc: datetime
    is_half_day: bool = False
