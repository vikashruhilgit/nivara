"""Tests for :mod:`backend.app.services.benchmark`."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal

import fakeredis.aioredis
import pandas as pd
import pytest
import pytest_asyncio
from backend.app.services.benchmark import (
    BENCHMARK_CACHE_TTL_SECONDS,
    NIFTY_SYMBOL,
    SP500_SYMBOL,
    BenchmarkService,
    benchmark_cache_key,
)


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[fakeredis.aioredis.FakeRedis, None]:
    client = fakeredis.aioredis.FakeRedis()
    try:
        yield client
    finally:
        await client.aclose()


def _fake_ticker(close_first: float, close_last: float, extra_bars: int = 3):
    """Return a class mimicking ``yfinance.Ticker`` with a fixed close series."""

    closes = [close_first] + [close_first] * extra_bars + [close_last]
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )

    class _Ticker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, *args: object, **kwargs: object) -> pd.DataFrame:
            return df

    return _Ticker


async def test_get_return_computes_total_return(
    redis_client: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """close_last / close_first - 1 over the window is returned."""
    import sys
    import types

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = _fake_ticker(100.0, 110.0)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    service = BenchmarkService(redis_client)
    result = await service.get_return(symbol=NIFTY_SYMBOL, period_days=30)

    assert result.symbol == NIFTY_SYMBOL
    assert result.currency == "INR"
    assert result.stale is False
    assert result.close_start == Decimal("100.0")
    assert result.close_end == Decimal("110.0")
    # (110/100) - 1 = 0.1
    assert float(result.total_return) == pytest.approx(0.1, abs=1e-6)


async def test_get_return_caches_result(
    redis_client: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second call within TTL reads from Redis and does NOT hit yfinance."""
    import sys
    import types

    calls = {"n": 0}

    def _counting_ticker(close_first: float, close_last: float):
        Base = _fake_ticker(close_first, close_last)

        class _T(Base):  # type: ignore[misc,valid-type]
            def history(self, *args: object, **kwargs: object) -> pd.DataFrame:
                calls["n"] += 1
                return super().history(*args, **kwargs)

        return _T

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = _counting_ticker(100.0, 105.0)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    service = BenchmarkService(redis_client)
    await service.get_return(symbol=SP500_SYMBOL, period_days=30)
    await service.get_return(symbol=SP500_SYMBOL, period_days=30)
    assert calls["n"] == 1

    # TTL set correctly.
    ttl = await redis_client.ttl(benchmark_cache_key(SP500_SYMBOL, 30))
    assert 0 < ttl <= BENCHMARK_CACHE_TTL_SECONDS


async def test_get_return_fallback_on_fetch_failure(
    redis_client: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On yfinance exception, return stale=True with zero total_return."""
    import sys
    import types

    class _BrokenTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, *args: object, **kwargs: object) -> pd.DataFrame:
            raise RuntimeError("upstream down")

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = _BrokenTicker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    service = BenchmarkService(redis_client)
    result = await service.get_return(symbol=NIFTY_SYMBOL, period_days=30)

    assert result.stale is True
    assert result.total_return == Decimal("0")
    assert result.close_start is None
    assert result.close_end is None


async def test_get_return_empty_frame_falls_back(
    redis_client: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty DataFrame from yfinance → stale=True fallback."""
    import sys
    import types

    class _EmptyTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, *args: object, **kwargs: object) -> pd.DataFrame:
            return pd.DataFrame()

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = _EmptyTicker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    service = BenchmarkService(redis_client)
    result = await service.get_return(symbol=SP500_SYMBOL, period_days=30)
    assert result.stale is True


def test_benchmark_cache_key_format() -> None:
    assert benchmark_cache_key("^NSEI", 30) == "benchmark:^NSEI:30d"
