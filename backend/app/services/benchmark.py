"""Benchmark service — Yahoo-backed index returns for portfolio intelligence.

Responsibilities
----------------
* Fetch the period total return of a Yahoo index symbol (``^NSEI`` = Nifty 50,
  ``^GSPC`` = S&P 500) for a given lookback window.
* Cache the computed :class:`backend.app.schemas.benchmark.BenchmarkReturn`
  in Redis for 24 h under ``benchmark:{symbol}:{period}d`` so we don't hit
  Yahoo once per intelligence request.
* Degrade gracefully: on fetch failure return a ``stale=True`` zero-return
  observation, log via :func:`logging.Logger.exception`, and let the caller
  surface the flag.

Why not reuse :class:`backend.app.data.yahoo.YahooProvider`?
-----------------------------------------------------------
``YahooProvider.get_ohlcv`` expects a tradable ``Instrument`` symbol (it
routes through canonical symbol → Yahoo mapping and caches under
``data:yahoo:ohlcv:...``). Index symbols start with ``^`` and aren't
instruments we track. We call ``yfinance.Ticker`` directly here using the
exact same thread-off-loop pattern (:func:`asyncio.to_thread`) to keep the
pattern consistent.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final

from backend.app.schemas.benchmark import BenchmarkReturn
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

#: Yahoo symbol for the Nifty 50 index (Indian equities benchmark, INR).
NIFTY_SYMBOL: Final[str] = "^NSEI"
#: Yahoo symbol for the S&P 500 index (US equities benchmark, USD).
SP500_SYMBOL: Final[str] = "^GSPC"

#: Cache TTL for benchmark returns — 1 day (Yahoo EOD cadence).
BENCHMARK_CACHE_TTL_SECONDS: Final[int] = 24 * 60 * 60

#: Default lookback window for period returns (30 calendar days).
DEFAULT_PERIOD_DAYS: Final[int] = 30


def benchmark_cache_key(symbol: str, period_days: int) -> str:
    """Redis key for a cached :class:`BenchmarkReturn`."""
    return f"benchmark:{symbol}:{period_days}d"


def _symbol_currency(symbol: str) -> str:
    """Return the native currency of a supported benchmark symbol."""
    if symbol == NIFTY_SYMBOL:
        return "INR"
    if symbol == SP500_SYMBOL:
        return "USD"
    # Default to USD; callers passing new symbols should extend the map.
    return "USD"


class BenchmarkService:
    """Async service for period returns of benchmark indices."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get_return(
        self,
        *,
        symbol: str,
        period_days: int = DEFAULT_PERIOD_DAYS,
    ) -> BenchmarkReturn:
        """Return the period total return for ``symbol``.

        Cached for 24 h in Redis. On fetch failure, returns a ``stale=True``
        observation with ``total_return=0`` so callers can continue.
        """
        key = benchmark_cache_key(symbol, period_days)

        cached = await self._read_cache(key)
        if cached is not None:
            return cached

        now = datetime.now(UTC)
        period_start = now - timedelta(days=period_days)
        try:
            close_start, close_end = await asyncio.to_thread(
                self._fetch_endpoints_sync, symbol, period_days
            )
        except Exception:
            logger.exception("benchmark fetch failed for %s (%dd)", symbol, period_days)
            return BenchmarkReturn(
                symbol=symbol,
                currency=_symbol_currency(symbol),
                period_days=period_days,
                period_start=period_start,
                period_end=now,
                close_start=None,
                close_end=None,
                total_return=Decimal("0"),
                stale=True,
            )

        total_return = (
            (close_end / close_start) - Decimal("1") if close_start > Decimal("0") else Decimal("0")
        )
        observation = BenchmarkReturn(
            symbol=symbol,
            currency=_symbol_currency(symbol),
            period_days=period_days,
            period_start=period_start,
            period_end=now,
            close_start=close_start,
            close_end=close_end,
            total_return=total_return,
            stale=False,
        )

        await self._write_cache(key, observation)
        return observation

    # ------------------------------------------------------------------ internals

    async def _read_cache(self, key: str) -> BenchmarkReturn | None:
        try:
            raw = await self._redis.get(key)
        except Exception:
            logger.exception("benchmark cache read failed for key=%s", key)
            return None
        if raw is None:
            return None
        try:
            return BenchmarkReturn.model_validate_json(raw)
        except Exception:
            logger.exception("benchmark cache payload invalid for key=%s", key)
            return None

    async def _write_cache(self, key: str, value: BenchmarkReturn) -> None:
        try:
            await self._redis.set(key, value.model_dump_json(), ex=BENCHMARK_CACHE_TTL_SECONDS)
        except Exception:
            logger.exception("benchmark cache write failed for key=%s", key)

    def _fetch_endpoints_sync(self, symbol: str, period_days: int) -> tuple[Decimal, Decimal]:
        """Fetch first and last daily close in the window via ``yfinance``.

        Returns ``(close_first, close_last)`` as :class:`~decimal.Decimal`.
        Raises on any upstream failure; caller logs and falls back to stale.
        """
        import yfinance as yf  # local import: avoid cold-start cost

        ticker = yf.Ticker(symbol)
        end = datetime.now(UTC)
        # Pad the start slightly to account for weekends/holidays at the edge.
        start = end - timedelta(days=period_days + 5)
        df = ticker.history(start=start, end=end, interval="1d", auto_adjust=False)
        if df is None or df.empty:
            raise RuntimeError(f"no OHLCV returned for {symbol}")

        close_series = df["Close"].dropna()
        if len(close_series) < 2:
            raise RuntimeError(f"insufficient bars ({len(close_series)}) for {symbol}")

        first = Decimal(str(float(close_series.iloc[0])))
        last = Decimal(str(float(close_series.iloc[-1])))
        return first, last


#: Map of MIC venue → (benchmark symbol, native currency).
_VENUE_BENCHMARK: Final[dict[str, tuple[str, str]]] = {
    "XNSE": (NIFTY_SYMBOL, "INR"),
    "XBOM": (NIFTY_SYMBOL, "INR"),
    "XNAS": (SP500_SYMBOL, "USD"),
    "XNYS": (SP500_SYMBOL, "USD"),
}


def benchmark_for_venue(venue: str) -> tuple[str, str] | None:
    """Return the ``(yahoo_symbol, native_currency)`` for a MIC venue, or None."""
    return _VENUE_BENCHMARK.get(venue.upper())


class FxConverter:  # pragma: no cover — protocol-like marker
    """Minimal protocol implemented by :class:`backend.app.services.fx.FxService`."""

    async def get_rate(self, *, base: str, quote: str, as_of: datetime | None = None) -> Decimal:
        raise NotImplementedError


async def benchmark_return_in_base(
    observation: BenchmarkReturn,
    *,
    base_currency: str,
    fx_service: FxConverter,
) -> Decimal:
    """Return the benchmark's period total return expressed in ``base_currency``.

    Uses daily-close FX at period end vs period start to convert the index
    levels, then computes ``close_end_base / close_start_base - 1``. When the
    index is already in the base currency, or when close endpoints are missing
    (``stale=True``), returns ``observation.total_return`` unchanged.
    """
    if observation.stale or observation.close_start is None or observation.close_end is None:
        return observation.total_return
    native = observation.currency.upper()
    base = base_currency.upper()
    if native == base:
        return observation.total_return

    fx_end = await fx_service.get_rate(base=native, quote=base, as_of=observation.period_end)
    fx_start = await fx_service.get_rate(base=native, quote=base, as_of=observation.period_start)
    start_base = observation.close_start * fx_start
    end_base = observation.close_end * fx_end
    if start_base <= Decimal("0"):
        return Decimal("0")
    return (end_base / start_base) - Decimal("1")


async def blended_portfolio_return(
    *,
    weights_by_venue: dict[str, Decimal],
    base_currency: str,
    benchmark_service: BenchmarkService,
    fx_service: FxConverter,
    period_days: int = DEFAULT_PERIOD_DAYS,
) -> Decimal:
    """Allocation-weighted blended benchmark return in ``base_currency``.

    ``weights_by_venue`` maps MIC venue (``XNSE``, ``XNAS``, ...) to allocation
    share (0..1). Venues not in the benchmark map contribute 0. Weights that
    don't sum to 1 are used as-is (caller owns normalization).
    """
    total = Decimal("0")
    seen: set[str] = set()
    for venue, weight in weights_by_venue.items():
        mapping = benchmark_for_venue(venue)
        if mapping is None:
            continue
        symbol, _ccy = mapping
        if symbol in seen:
            # Same benchmark already counted — accumulate via weight only
            # (weights from distinct venues sharing a symbol are additive).
            observation = await benchmark_service.get_return(symbol=symbol, period_days=period_days)
        else:
            observation = await benchmark_service.get_return(symbol=symbol, period_days=period_days)
            seen.add(symbol)
        base_return = await benchmark_return_in_base(
            observation, base_currency=base_currency, fx_service=fx_service
        )
        total += weight * base_return
    return total


__all__ = [
    "BENCHMARK_CACHE_TTL_SECONDS",
    "BenchmarkService",
    "DEFAULT_PERIOD_DAYS",
    "FxConverter",
    "NIFTY_SYMBOL",
    "SP500_SYMBOL",
    "benchmark_cache_key",
    "benchmark_for_venue",
    "benchmark_return_in_base",
    "blended_portfolio_return",
]
