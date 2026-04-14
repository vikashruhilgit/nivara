"""Behavioural tests for :class:`YahooProvider`.

Yahoo's network is fully mocked via ``unittest.mock.patch`` on the ``yfinance``
module attribute referenced inside the provider. We verify:

* AC #1: ``get_ohlcv`` returns OHLCVBar list on success and the data is
  cacheable.
* AC #2: second call with cache warm does **not** invoke yfinance.
* AC #3: upstream failure raises :class:`UpstreamUnavailableError` (subclass
  of :class:`DataProviderError`).
* AC #5: cached fundamentals return without re-fetching.
* AC #6: ``get_quote`` returns a Quote with ``delay_minutes=15``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import fakeredis.aioredis
import pytest
from backend.app.data.base import OHLCVBar
from backend.app.data.errors import (
    DataProviderError,
    UpstreamUnavailableError,
)
from backend.app.data.yahoo import YAHOO_DELAY_MINUTES, YahooProvider

# ---- Fixtures --------------------------------------------------------------


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def fake_ohlcv_df():
    """Return a minimal pandas-like DataFrame with 3 daily bars."""
    import pandas as pd

    idx = pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-06"], utc=True)
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.5, 100.5, 101.5],
            "Close": [100.75, 101.5, 102.25],
            "Volume": [1_000_000, 1_100_000, 1_200_000],
        },
        index=idx,
    )


# ---- OHLCV -----------------------------------------------------------------


async def test_get_ohlcv_returns_bars_and_caches(redis, fake_ohlcv_df) -> None:
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.history.return_value = fake_ohlcv_df

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        provider = YahooProvider(redis)
        bars = await provider.get_ohlcv("AAPL", lookback_days=30)

    assert len(bars) == 3
    assert all(isinstance(b, OHLCVBar) for b in bars)
    assert bars[0].close > 0
    # All timestamps are UTC-aware.
    for b in bars:
        assert b.timestamp.tzinfo is not None

    # Cache populated for the same (symbol, lookback).
    assert await redis.get("data:yahoo:ohlcv:AAPL:30") is not None


async def test_get_ohlcv_second_call_uses_cache(redis, fake_ohlcv_df) -> None:
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.history.return_value = fake_ohlcv_df

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        provider = YahooProvider(redis)
        await provider.get_ohlcv("AAPL", lookback_days=30)
        first_calls = mock_yf.Ticker.call_count
        # Second call should hit cache, not yfinance.
        bars2 = await provider.get_ohlcv("AAPL", lookback_days=30)
        assert len(bars2) == 3
        assert mock_yf.Ticker.call_count == first_calls


async def test_get_ohlcv_upstream_empty_raises_unavailable(redis) -> None:
    import pandas as pd

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        provider = YahooProvider(redis)
        with pytest.raises(UpstreamUnavailableError) as exc:
            await provider.get_ohlcv("NOPE", lookback_days=30)

    assert isinstance(exc.value, DataProviderError)
    assert exc.value.provider == "yahoo"


async def test_get_ohlcv_upstream_exception_wrapped(redis) -> None:
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.history.side_effect = RuntimeError("yahoo down")

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        provider = YahooProvider(redis)
        with pytest.raises(UpstreamUnavailableError) as exc:
            await provider.get_ohlcv("AAPL", lookback_days=30)
    assert "yahoo down" in str(exc.value)


async def test_get_ohlcv_rejects_non_positive_lookback(redis) -> None:
    provider = YahooProvider(redis)
    with pytest.raises(DataProviderError):
        await provider.get_ohlcv("AAPL", lookback_days=0)


# ---- Fundamentals ----------------------------------------------------------


async def test_get_fundamentals_returns_model_and_caches(redis) -> None:
    info = {
        "symbol": "AAPL",
        "currency": "USD",
        "marketCap": 3_000_000_000_000,
        "trailingPE": 30.5,
        "priceToBook": 40.1,
        "dividendYield": 0.005,
        "beta": 1.2,
        "trailingEps": 6.5,
        "totalRevenue": 400_000_000_000,
    }
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.info = info

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        provider = YahooProvider(redis)
        f = await provider.get_fundamentals("AAPL")

    assert f.symbol == "AAPL"
    assert f.currency == "USD"
    assert f.market_cap is not None
    assert f.pe_ratio is not None
    assert await redis.get("data:yahoo:fundamentals:AAPL") is not None


async def test_get_fundamentals_second_call_uses_cache(redis) -> None:
    info = {"symbol": "AAPL", "currency": "USD", "trailingPE": 30.5}
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.info = info

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        provider = YahooProvider(redis)
        await provider.get_fundamentals("AAPL")
        before = mock_yf.Ticker.call_count
        await provider.get_fundamentals("AAPL")
        assert mock_yf.Ticker.call_count == before  # served from cache


# ---- Quote -----------------------------------------------------------------


async def test_get_quote_returns_price_with_delay_disclaimer(redis) -> None:
    info = {"regularMarketPrice": 180.25, "currency": "USD"}
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.info = info

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        provider = YahooProvider(redis)
        q = await provider.get_quote("AAPL")

    assert q.symbol == "AAPL"
    assert q.delay_minutes == YAHOO_DELAY_MINUTES == 15
    assert q.currency == "USD"
    assert q.timestamp.tzinfo is not None


async def test_get_quote_no_price_raises_unavailable(redis) -> None:
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.info = {"currency": "USD"}  # no price field

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        provider = YahooProvider(redis)
        with pytest.raises(UpstreamUnavailableError):
            await provider.get_quote("AAPL")


# ---- Symbol mapping integration (AC #4) ------------------------------------


def test_indian_stock_maps_to_ns_suffix() -> None:
    from backend.app.data.yahoo import resolve_yahoo_symbol

    instrument = SimpleNamespace(symbol="RELIANCE", exchange="NSE")
    assert resolve_yahoo_symbol(instrument) == "RELIANCE.NS"  # type: ignore[arg-type]


async def test_get_ohlcv_with_resolved_indian_symbol(redis, fake_ohlcv_df) -> None:
    """End-to-end: NSE instrument → resolve → get_ohlcv uses RELIANCE.NS."""
    from backend.app.data.yahoo import resolve_yahoo_symbol

    instrument = SimpleNamespace(symbol="RELIANCE", exchange="NSE")
    symbol = resolve_yahoo_symbol(instrument)  # type: ignore[arg-type]

    mock_yf = MagicMock()
    mock_yf.Ticker.return_value.history.return_value = fake_ohlcv_df

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        provider = YahooProvider(redis)
        bars = await provider.get_ohlcv(symbol, lookback_days=30)

    # yfinance.Ticker was called with the NS-suffixed symbol.
    mock_yf.Ticker.assert_called_with("RELIANCE.NS")
    assert len(bars) == 3


# ---- Storage pipeline (smoke) ---------------------------------------------


async def test_upsert_ohlcv_empty_list_returns_zero() -> None:
    """Storage function short-circuits on empty input without touching DB."""
    from backend.app.data.storage import upsert_ohlcv

    # session is never used when bars is empty; passing None is safe here.
    count = await upsert_ohlcv(
        session=None,  # type: ignore[arg-type]
        instrument_id=SimpleNamespace(),  # type: ignore[arg-type]
        bars=[],
    )
    assert count == 0


async def test_upsert_ohlcv_queues_rows() -> None:
    """upsert_ohlcv issues exactly one statement and reports row count."""
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from backend.app.data.storage import upsert_ohlcv

    session = MagicMock()
    session.execute = AsyncMock()

    bars = [
        OHLCVBar(
            timestamp=datetime(2026, 1, d, tzinfo=UTC),
            open=__import__("decimal").Decimal("1"),
            high=__import__("decimal").Decimal("2"),
            low=__import__("decimal").Decimal("1"),
            close=__import__("decimal").Decimal("2"),
            volume=100,
        )
        for d in range(1, 4)
    ]
    count = await upsert_ohlcv(session, uuid4(), bars)
    assert count == 3
    session.execute.assert_awaited_once()
