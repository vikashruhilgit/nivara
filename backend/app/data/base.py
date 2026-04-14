"""Abstract :class:`DataProvider` interface plus Pydantic v2 payload schemas.

Per TechSpec v1.3 §9 the MVP ships with a Yahoo Finance implementation
(:class:`backend.app.data.yahoo.YahooProvider`), but all analysis consumers
depend only on this abstract base so swapping to Polygon.io requires no
changes outside :mod:`backend.app.data`.

Design notes
------------
* OHLCV bars are returned as a list of :class:`OHLCVBar` (not a raw
  ``pandas.DataFrame``) so the contract is serialisable and easy to mock.
  The Yahoo implementation converts its internal DataFrame at the boundary.
* All timestamps are timezone-aware UTC.
* All monetary values use :class:`decimal.Decimal` to avoid float drift; the
  Yahoo implementation rounds to 8 decimal places matching the
  ``price_history.open``/``close`` ``Numeric(20, 8)`` DB columns.
* :meth:`DataProvider.get_quote` returns the provider's latest tick with an
  explicit ``delay_minutes`` attribute — Yahoo is delayed ~15 minutes and we
  refuse to silently present that as real-time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OHLCVBar(BaseModel):
    """Single OHLCV observation for an instrument at a point in time."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(..., description="Bar timestamp, timezone-aware UTC.")
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(..., ge=0)


class Quote(BaseModel):
    """Latest-price snapshot for an instrument."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    price: Decimal
    timestamp: datetime = Field(..., description="Quote timestamp, timezone-aware UTC.")
    delay_minutes: int = Field(
        default=15,
        ge=0,
        description=(
            "Delay vs real-time trade in minutes. Yahoo Finance is delayed "
            "~15 minutes; callers MUST surface this disclaimer to end users."
        ),
    )
    currency: str = Field(..., min_length=3, max_length=3)


class Fundamentals(BaseModel):
    """Point-in-time fundamentals snapshot.

    Field set is deliberately minimal (what the analysis engine needs for the
    initial fundamental score). Providers may leave any field ``None`` when
    unavailable; consumers must tolerate partial data.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    currency: str
    market_cap: Decimal | None = None
    pe_ratio: Decimal | None = None
    pb_ratio: Decimal | None = None
    dividend_yield: Decimal | None = None
    beta: Decimal | None = None
    eps: Decimal | None = None
    revenue_ttm: Decimal | None = None
    fetched_at: datetime


class DataProvider(ABC):
    """Abstract base class every market-data provider must implement.

    Implementations are expected to be async, side-effect-aware (external HTTP
    or SDK calls), and safe for use in a shared process-wide singleton.
    Caching and DB persistence are *composed* around providers — not baked in
    here — so this class stays thin and easy to mock in tests.
    """

    #: Short machine-readable identifier used in logs, cache keys, and errors.
    name: str = "abstract"

    @abstractmethod
    async def get_ohlcv(
        self,
        symbol: str,
        *,
        lookback_days: int,
    ) -> list[OHLCVBar]:
        """Return daily OHLCV bars for ``symbol`` covering the last ``lookback_days``.

        Parameters
        ----------
        symbol:
            Provider-specific symbol (e.g. ``"AAPL"`` for Yahoo US, ``"RELIANCE.NS"``
            for Yahoo India). Call sites are expected to resolve canonical
            instrument → provider symbol before calling.
        lookback_days:
            Number of calendar days of history to request. Providers may return
            fewer bars on non-trading days.

        Raises
        ------
        SymbolNotFoundError
            The provider does not recognise the symbol.
        UpstreamUnavailableError
            The provider returned empty/invalid data or is unreachable.
        RateLimitError
            The provider is rate-limiting the caller.
        """

    @abstractmethod
    async def get_fundamentals(self, symbol: str) -> Fundamentals:
        """Return point-in-time fundamentals for ``symbol``."""

    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote:
        """Return the latest quote for ``symbol`` with delay disclosure."""


__all__ = [
    "DataProvider",
    "Fundamentals",
    "OHLCVBar",
    "Quote",
]
