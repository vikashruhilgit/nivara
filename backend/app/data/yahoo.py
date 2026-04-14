"""Yahoo Finance :class:`DataProvider` implementation backed by ``yfinance``.

Caveats
-------
* Yahoo has **no official public API**; ``yfinance`` scrapes Yahoo's internal
  JSON endpoints. Expect breakage on Yahoo UI changes. This is acceptable
  risk for the MVP and is explicitly recorded in the m2-9 brief's risk
  assessment. The :class:`backend.app.data.DataProvider` abstraction exists
  so that we can swap to Polygon.io ($29/mo) without changes outside
  :mod:`backend.app.data`.
* Yahoo data is **delayed ~15 minutes**. :meth:`get_quote` returns
  ``delay_minutes=15`` so callers can surface the disclaimer.
* Yahoo ToS prohibits automated scraping. We mitigate via aggressive Redis
  caching (1h OHLCV, 24h fundamentals — see
  :mod:`backend.app.data.cache`).

Threading / event loop
----------------------
``yfinance`` is synchronous. We wrap calls with :func:`asyncio.to_thread` so
they don't block the FastAPI event loop. The concurrency ceiling is governed
by the default thread pool; callers that need tight control should add a
semaphore.

Symbol resolution (AC #4)
-------------------------
Callers pass the **Yahoo symbol directly** (e.g. ``"AAPL"``, ``"RELIANCE.NS"``,
``"INFY.NS"``). Mapping a canonical
:class:`backend.app.models.instruments.Instrument` → Yahoo symbol happens at
the call site via :func:`resolve_yahoo_symbol`, which applies the convention:

* US listings: ``symbol`` as-is (``"AAPL"``).
* NSE India: ``{symbol}.NS`` (``"RELIANCE.NS"``).
* BSE India: ``{symbol}.BO`` (``"RELIANCE.BO"``).

The :class:`backend.app.models.symbol_mappings.SymbolMapping` table is
*broker*-oriented (alpaca/zerodha enum) and is **not** used here — the
Yahoo symbol is a function of exchange and canonical symbol, which we derive
deterministically.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from backend.app.data.base import DataProvider, Fundamentals, OHLCVBar, Quote
from backend.app.data.cache import (
    FUNDAMENTALS_TTL_SECONDS,
    OHLCV_TTL_SECONDS,
    QUOTE_TTL_SECONDS,
    fundamentals_key,
    get_model,
    get_model_list,
    ohlcv_key,
    quote_key,
    set_model,
    set_model_list,
)
from backend.app.data.errors import (
    DataProviderError,
    SymbolNotFoundError,
    UpstreamUnavailableError,
)

if TYPE_CHECKING:
    from backend.app.models.instruments import Instrument
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_PROVIDER_NAME = "yahoo"

#: Yahoo's public disclosure — quotes are delayed ~15 minutes for free users.
YAHOO_DELAY_MINUTES = 15


def resolve_yahoo_symbol(instrument: Instrument) -> str:
    """Return the Yahoo Finance symbol for a canonical ``Instrument``.

    Convention::

        exchange=NASDAQ / NYSE / ARCA / AMEX / BATS  → symbol as-is
        exchange=NSE                                 → f"{symbol}.NS"
        exchange=BSE                                 → f"{symbol}.BO"

    Anything else raises :class:`DataProviderError` so we fail loudly rather
    than silently hitting Yahoo with a malformed ticker.
    """
    exchange = (instrument.exchange or "").upper()
    symbol = instrument.symbol.upper()
    if exchange in {"NASDAQ", "NYSE", "ARCA", "AMEX", "BATS", "NYSEARCA"}:
        return symbol
    if exchange == "NSE":
        return f"{symbol}.NS"
    if exchange == "BSE":
        return f"{symbol}.BO"
    raise DataProviderError(
        f"unsupported exchange {exchange!r} for Yahoo provider",
        provider=_PROVIDER_NAME,
    )


def _decimal(value: Any) -> Decimal:
    """Convert yfinance float/numpy values to ``Decimal`` safely.

    yfinance returns ``numpy.float64`` which ``Decimal()`` refuses. Stringify
    first to get an exact base-10 representation, then quantise to 8 decimal
    places matching the ``Numeric(20, 8)`` DB columns.
    """
    if value is None:
        raise UpstreamUnavailableError(
            "missing numeric field from Yahoo payload", provider=_PROVIDER_NAME
        )
    return Decimal(str(float(value))).quantize(Decimal("0.00000001"))


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # yfinance returns NaN for missing fundamentals.
    if f != f:  # noqa: PLR0124  (NaN check)
        return None
    return Decimal(str(f))


class YahooProvider(DataProvider):
    """Yahoo-Finance-backed :class:`DataProvider`.

    Wraps ``yfinance`` (sync SDK) in :func:`asyncio.to_thread` and caches
    results in Redis per TTLs defined in :mod:`backend.app.data.cache`.
    """

    name = _PROVIDER_NAME

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    # ---- OHLCV ---------------------------------------------------------

    async def get_ohlcv(
        self,
        symbol: str,
        *,
        lookback_days: int,
    ) -> list[OHLCVBar]:
        if lookback_days <= 0:
            raise DataProviderError("lookback_days must be positive", provider=_PROVIDER_NAME)

        key = ohlcv_key(_PROVIDER_NAME, symbol, lookback_days)
        cached = await get_model_list(self._redis, key, OHLCVBar)
        if cached is not None:
            logger.debug("cache hit: %s", key)
            return cached

        logger.debug("cache miss: %s — fetching from Yahoo", key)
        bars = await asyncio.to_thread(self._fetch_ohlcv_sync, symbol, lookback_days)
        await set_model_list(self._redis, key, bars, ttl=OHLCV_TTL_SECONDS)
        return bars

    def _fetch_ohlcv_sync(self, symbol: str, lookback_days: int) -> list[OHLCVBar]:
        """Synchronous yfinance call — executed in a worker thread."""
        import yfinance as yf  # local import keeps cold-start / import cost down

        try:
            ticker = yf.Ticker(symbol)
            end = datetime.now(UTC)
            start = end - timedelta(days=lookback_days)
            df = ticker.history(start=start, end=end, interval="1d", auto_adjust=False)
        except Exception as exc:  # yfinance raises opaque Exceptions
            raise UpstreamUnavailableError(
                f"Yahoo OHLCV fetch failed for {symbol}: {exc}",
                provider=_PROVIDER_NAME,
            ) from exc

        if df is None or df.empty:
            # yfinance returns an empty DataFrame both for unknown symbols
            # and for temporary upstream failures. We bias towards
            # SymbolNotFoundError only when we can be certain (e.g. empty
            # .info dict) — otherwise UpstreamUnavailableError is safer.
            raise UpstreamUnavailableError(
                f"Yahoo returned no OHLCV data for {symbol}",
                provider=_PROVIDER_NAME,
            )

        bars: list[OHLCVBar] = []
        for ts, row in df.iterrows():
            # pandas Timestamp → UTC-aware datetime
            py_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            py_ts = py_ts.replace(tzinfo=UTC) if py_ts.tzinfo is None else py_ts.astimezone(UTC)
            bars.append(
                OHLCVBar(
                    timestamp=py_ts,
                    open=_decimal(row["Open"]),
                    high=_decimal(row["High"]),
                    low=_decimal(row["Low"]),
                    close=_decimal(row["Close"]),
                    volume=int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
                )
            )
        return bars

    # ---- Fundamentals --------------------------------------------------

    async def get_fundamentals(self, symbol: str) -> Fundamentals:
        key = fundamentals_key(_PROVIDER_NAME, symbol)
        cached = await get_model(self._redis, key, Fundamentals)
        if cached is not None:
            logger.debug("cache hit: %s", key)
            return cached

        logger.debug("cache miss: %s — fetching from Yahoo", key)
        fundamentals = await asyncio.to_thread(self._fetch_fundamentals_sync, symbol)
        await set_model(self._redis, key, fundamentals, ttl=FUNDAMENTALS_TTL_SECONDS)
        return fundamentals

    def _fetch_fundamentals_sync(self, symbol: str) -> Fundamentals:
        import yfinance as yf

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
        except Exception as exc:
            raise UpstreamUnavailableError(
                f"Yahoo fundamentals fetch failed for {symbol}: {exc}",
                provider=_PROVIDER_NAME,
            ) from exc

        if not info or info.get("symbol") is None and info.get("shortName") is None:
            raise SymbolNotFoundError(
                f"Yahoo has no fundamentals for {symbol}",
                provider=_PROVIDER_NAME,
            )

        return Fundamentals(
            symbol=symbol,
            currency=(info.get("currency") or "USD").upper()[:3],
            market_cap=_decimal_or_none(info.get("marketCap")),
            pe_ratio=_decimal_or_none(info.get("trailingPE")),
            pb_ratio=_decimal_or_none(info.get("priceToBook")),
            dividend_yield=_decimal_or_none(info.get("dividendYield")),
            beta=_decimal_or_none(info.get("beta")),
            eps=_decimal_or_none(info.get("trailingEps")),
            revenue_ttm=_decimal_or_none(info.get("totalRevenue")),
            fetched_at=datetime.now(UTC),
        )

    # ---- Quote ---------------------------------------------------------

    async def get_quote(self, symbol: str) -> Quote:
        key = quote_key(_PROVIDER_NAME, symbol)
        cached = await get_model(self._redis, key, Quote)
        if cached is not None:
            return cached

        quote = await asyncio.to_thread(self._fetch_quote_sync, symbol)
        await set_model(self._redis, key, quote, ttl=QUOTE_TTL_SECONDS)
        return quote

    def _fetch_quote_sync(self, symbol: str) -> Quote:
        import yfinance as yf

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
        except Exception as exc:
            raise UpstreamUnavailableError(
                f"Yahoo quote fetch failed for {symbol}: {exc}",
                provider=_PROVIDER_NAME,
            ) from exc

        price = (
            info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")
        )
        if price is None:
            raise UpstreamUnavailableError(
                f"Yahoo returned no price for {symbol}", provider=_PROVIDER_NAME
            )

        return Quote(
            symbol=symbol,
            price=_decimal(price),
            timestamp=datetime.now(UTC),
            delay_minutes=YAHOO_DELAY_MINUTES,
            currency=(info.get("currency") or "USD").upper()[:3],
        )


__all__ = ["YAHOO_DELAY_MINUTES", "YahooProvider", "resolve_yahoo_symbol"]
