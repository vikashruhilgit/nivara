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


# --- Cross-market helpers (M4-23 S1) -----------------------------------------


from datetime import UTC, datetime, timedelta  # noqa: E402

from backend.app.schemas.benchmark import BenchmarkReturn  # noqa: E402
from backend.app.services.benchmark import (  # noqa: E402
    benchmark_for_venue,
    benchmark_return_in_base,
    blended_portfolio_return,
)


def test_benchmark_for_venue_maps_correctly() -> None:
    assert benchmark_for_venue("XNSE") == (NIFTY_SYMBOL, "INR")
    assert benchmark_for_venue("xnas") == (SP500_SYMBOL, "USD")
    assert benchmark_for_venue("XLON") is None


class _StaticFx:
    """Minimal FxConverter: returns a fixed rate regardless of as_of."""

    def __init__(self, rate_map: dict[tuple[str, str], Decimal]) -> None:
        self._rates = rate_map

    async def get_rate(
        self,
        *,
        base: str,
        quote: str,
        as_of: datetime | None = None,
    ) -> Decimal:
        b, q = base.upper(), quote.upper()
        if b == q:
            return Decimal("1")
        return self._rates[(b, q)]


def _obs(symbol: str, ccy: str, close_start: str, close_end: str) -> BenchmarkReturn:
    end = datetime.now(UTC)
    start = end - timedelta(days=30)
    cs = Decimal(close_start)
    ce = Decimal(close_end)
    return BenchmarkReturn(
        symbol=symbol,
        currency=ccy,
        period_days=30,
        period_start=start,
        period_end=end,
        close_start=cs,
        close_end=ce,
        total_return=(ce / cs) - Decimal("1"),
        stale=False,
    )


async def test_benchmark_return_in_base_same_currency_passthrough() -> None:
    obs = _obs(NIFTY_SYMBOL, "INR", "100", "110")
    fx = _StaticFx({})
    result = await benchmark_return_in_base(obs, base_currency="INR", fx_service=fx)
    assert result == obs.total_return


async def test_benchmark_return_in_base_converts_usd_to_inr() -> None:
    # S&P 500 up 10% in USD. USD/INR flat at 83 → INR return = 10%.
    obs = _obs(SP500_SYMBOL, "USD", "100", "110")
    fx = _StaticFx({("USD", "INR"): Decimal("83")})
    result = await benchmark_return_in_base(obs, base_currency="INR", fx_service=fx)
    assert float(result) == pytest.approx(0.1, abs=1e-9)


async def test_benchmark_return_in_base_adds_fx_impact() -> None:
    # S&P 500 up 10% USD; USD strengthens from 80→88 INR (+10%).
    # INR return = (110*88)/(100*80) - 1 = 9680/8000 - 1 = 0.21
    obs = _obs(SP500_SYMBOL, "USD", "100", "110")

    class _AsOfFx:
        async def get_rate(
            self,
            *,
            base: str,
            quote: str,
            as_of: datetime | None = None,
        ) -> Decimal:
            assert base == "USD" and quote == "INR"
            assert as_of is not None
            # Use period_end vs period_start to return different rates.
            if as_of == obs.period_end:
                return Decimal("88")
            return Decimal("80")

    result = await benchmark_return_in_base(obs, base_currency="INR", fx_service=_AsOfFx())
    assert float(result) == pytest.approx(0.21, abs=1e-9)


async def test_benchmark_return_in_base_stale_passthrough() -> None:
    end = datetime.now(UTC)
    obs = BenchmarkReturn(
        symbol=SP500_SYMBOL,
        currency="USD",
        period_days=30,
        period_start=end - timedelta(days=30),
        period_end=end,
        close_start=None,
        close_end=None,
        total_return=Decimal("0"),
        stale=True,
    )
    fx = _StaticFx({})
    result = await benchmark_return_in_base(obs, base_currency="INR", fx_service=fx)
    assert result == Decimal("0")


async def test_blended_portfolio_return_weights_by_venue(
    redis_client: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """60% IN (Nifty +10% INR) + 40% US (S&P +5% USD, flat FX at 83) in INR base.

    Expected: 0.6 * 0.10 + 0.4 * 0.05 = 0.08.
    """
    import sys
    import types

    # yfinance fake returns different bars per symbol.
    class _MultiTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, *args: object, **kwargs: object) -> pd.DataFrame:
            if self.symbol == NIFTY_SYMBOL:
                closes = [100.0, 100.0, 100.0, 110.0]
            else:
                closes = [200.0, 200.0, 200.0, 210.0]
            idx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
            return pd.DataFrame(
                {
                    "Open": closes,
                    "High": closes,
                    "Low": closes,
                    "Close": closes,
                    "Volume": [1] * len(closes),
                },
                index=idx,
            )

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = _MultiTicker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    service = BenchmarkService(redis_client)
    fx = _StaticFx({("USD", "INR"): Decimal("83")})
    blended = await blended_portfolio_return(
        weights_by_venue={"XNSE": Decimal("0.6"), "XNAS": Decimal("0.4")},
        base_currency="INR",
        benchmark_service=service,
        fx_service=fx,
        period_days=30,
    )
    assert float(blended) == pytest.approx(0.08, abs=1e-9)


async def test_blended_portfolio_return_ignores_unknown_venue(
    redis_client: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys
    import types

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = _fake_ticker(100.0, 110.0)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    service = BenchmarkService(redis_client)
    fx = _StaticFx({("USD", "INR"): Decimal("83")})
    blended = await blended_portfolio_return(
        weights_by_venue={"XLON": Decimal("1.0")},  # not mapped
        base_currency="INR",
        benchmark_service=service,
        fx_service=fx,
        period_days=30,
    )
    assert blended == Decimal("0")
