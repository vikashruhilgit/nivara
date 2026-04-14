"""Tests for :mod:`backend.app.analysis.technical`.

Exercises the 6-indicator pipeline, composite scoring, action mapping,
insufficient-data handling, and Redis caching semantics. All tests run with
synthetic OHLCV frames so they don't depend on the yfinance/DB path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import fakeredis.aioredis
import numpy as np
import pandas as pd
import pytest
import pytest_asyncio
from backend.app.analysis.technical import (
    _ACTION_THRESHOLDS,
    analyze_technical,
    analyze_with_cache,
    cache_indicators,
    load_cached_indicators,
)

# ---- Fixtures --------------------------------------------------------------


def _build_ohlcv(
    n: int = 252,
    start_price: float = 100.0,
    trend: float = 0.0,
    volatility: float = 0.01,
    volume: float = 1_000_000,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate a deterministic synthetic OHLCV frame.

    ``trend`` is per-bar drift (e.g. 0.001 = 0.1% per day).
    ``volatility`` is per-bar stddev of the random walk.
    """
    rng = np.random.default_rng(seed)
    rets = rng.normal(loc=trend, scale=volatility, size=n)
    close = start_price * np.cumprod(1.0 + rets)
    # Build OHLC around close with a small intrabar range.
    high = close * (1.0 + np.abs(rng.normal(0, volatility / 2, n)))
    low = close * (1.0 - np.abs(rng.normal(0, volatility / 2, n)))
    open_ = np.concatenate([[start_price], close[:-1]])
    vol = rng.normal(loc=volume, scale=volume * 0.2, size=n).clip(min=volume * 0.1)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(high, np.maximum(open_, close)),
            "low": np.minimum(low, np.minimum(open_, close)),
            "close": close,
            "volume": vol,
        },
        index=idx,
    )


@pytest_asyncio.fixture
async def redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


# ---- Basic pipeline --------------------------------------------------------


def test_analyze_full_year_returns_all_indicators():
    df = _build_ohlcv(n=252)
    out = analyze_technical(df)
    # Every indicator should score (252 bars > all minimums).
    for name in ("rsi", "macd", "ma_alignment", "bollinger", "volume", "atr"):
        ind = getattr(out, name)
        assert not ind.insufficient_data, f"{name} should have enough data"
        assert ind.value is not None
        assert -1.0 <= ind.value <= 1.0
        assert ind.raw is not None
    assert out.composite_score is not None
    assert -1.0 <= out.composite_score <= 1.0
    assert out.action in {"strong_sell", "sell", "hold", "buy", "strong_buy"}
    assert out.bars_analyzed == 252
    assert out.insufficient_data_flags == []


def test_action_mapping_thresholds():
    """Action boundaries must match AC #2: <-0.6 SS, -0.6..-0.2 S, -0.2..0.2 H, 0.2..0.6 B, >0.6 SB."""
    # Threshold table structure.
    assert _ACTION_THRESHOLDS[0] == (-0.6, "strong_sell")
    assert _ACTION_THRESHOLDS[1] == (-0.2, "sell")
    assert _ACTION_THRESHOLDS[2] == (0.2, "hold")
    assert _ACTION_THRESHOLDS[3] == (0.6, "buy")

    # Unit-test the mapping function with exact boundary values.
    from backend.app.analysis.technical import _action_for

    assert _action_for(-0.9) == "strong_sell"
    assert _action_for(-0.6) == "sell"  # boundary: -0.6 is NOT < -0.6 → next bucket
    assert _action_for(-0.4) == "sell"
    assert _action_for(-0.2) == "hold"
    assert _action_for(0.0) == "hold"
    assert _action_for(0.2) == "buy"
    assert _action_for(0.5) == "buy"
    assert _action_for(0.6) == "strong_buy"
    assert _action_for(0.9) == "strong_buy"


# ---- Insufficient-data handling --------------------------------------------


def test_fewer_than_30_bars_short_circuits():
    df = _build_ohlcv(n=20)
    out = analyze_technical(df)
    assert out.composite_score is None
    assert out.action is None
    assert set(out.insufficient_data_flags) == {
        "rsi", "macd", "ma_alignment", "bollinger", "volume", "atr"
    }
    assert out.rsi.insufficient_data
    assert out.rsi.value is None


def test_partial_data_flags_only_long_window_indicators():
    """50 bars → RSI/BB/volume/ATR/MACD OK; MA-alignment (needs SMA200) flagged."""
    df = _build_ohlcv(n=50)
    out = analyze_technical(df)
    assert out.ma_alignment.insufficient_data is True
    assert "ma_alignment" in out.insufficient_data_flags
    # Others should be fine.
    assert not out.rsi.insufficient_data
    assert not out.macd.insufficient_data
    assert not out.bollinger.insufficient_data
    # Composite still computes from remaining 5 indicators.
    assert out.composite_score is not None


def test_missing_columns_raises():
    df = pd.DataFrame({"close": [1, 2, 3]})
    with pytest.raises(ValueError, match="missing columns"):
        analyze_technical(df)


# ---- Individual indicator behaviour ---------------------------------------


def test_rsi_signal_is_negative_in_uptrend():
    """Persistent uptrend → RSI drifts above 50 → signal negative (overbought bias)."""
    df = _build_ohlcv(n=60, trend=0.01, volatility=0.002, seed=7)
    out = analyze_technical(df)
    assert out.rsi.raw is not None
    assert out.rsi.raw > 50
    assert out.rsi.value is not None and out.rsi.value < 0


def test_ma_alignment_bullish_order():
    """SMA20 > SMA50 > SMA200 must score +1 (fully bullish)."""
    df = _build_ohlcv(n=250, trend=0.005, volatility=0.001, seed=11)
    out = analyze_technical(df)
    assert out.ma_alignment.value == pytest.approx(1.0)


def test_ma_alignment_bearish_order():
    df = _build_ohlcv(n=250, trend=-0.005, volatility=0.001, seed=13)
    out = analyze_technical(df)
    assert out.ma_alignment.value == pytest.approx(-1.0)


# ---- Caching ---------------------------------------------------------------


async def test_cache_roundtrip_preserves_indicators(redis):
    df = _build_ohlcv(n=252)
    instrument_id = uuid4()
    analysis = analyze_technical(df)
    await cache_indicators(redis, instrument_id, analysis)

    loaded = await load_cached_indicators(redis, instrument_id)
    assert set(loaded.keys()) == {"rsi", "macd", "ma_alignment", "bollinger", "volume", "atr"}
    for name, original in (
        ("rsi", analysis.rsi),
        ("macd", analysis.macd),
        ("ma_alignment", analysis.ma_alignment),
        ("bollinger", analysis.bollinger),
        ("volume", analysis.volume),
        ("atr", analysis.atr),
    ):
        assert loaded[name].value == pytest.approx(original.value)
        assert loaded[name].raw == pytest.approx(original.raw)
        assert loaded[name].insufficient_data is original.insufficient_data


async def test_cache_key_format_matches_brief(redis):
    df = _build_ohlcv(n=252)
    instrument_id = uuid4()
    analysis = analyze_technical(df)
    await cache_indicators(redis, instrument_id, analysis)
    # Per AC #3: key is tech:{instrument_id}:{name}
    for name in ("rsi", "macd", "ma_alignment", "bollinger", "volume", "atr"):
        key = f"tech:{instrument_id}:{name}"
        assert await redis.exists(key) == 1


async def test_cache_ttl_applied(redis):
    df = _build_ohlcv(n=252)
    instrument_id = uuid4()
    analysis = analyze_technical(df)
    await cache_indicators(redis, instrument_id, analysis, ttl_seconds=300)
    ttl = await redis.ttl(f"tech:{instrument_id}:rsi")
    # Allow small skew for fakeredis.
    assert 290 <= ttl <= 300


async def test_insufficient_indicators_not_cached(redis):
    """Indicators flagged as insufficient should NOT be cached (we'd rather retry)."""
    df = _build_ohlcv(n=50)  # ma_alignment will be insufficient
    instrument_id = uuid4()
    analysis = analyze_technical(df)
    await cache_indicators(redis, instrument_id, analysis)
    assert await redis.exists(f"tech:{instrument_id}:ma_alignment") == 0
    assert await redis.exists(f"tech:{instrument_id}:rsi") == 1


async def test_analyze_with_cache_full_hit_skips_compute(redis, monkeypatch):
    """When all 6 indicators are cached, analyze_with_cache rebuilds without recomputing."""
    df = _build_ohlcv(n=252)
    instrument_id = uuid4()
    analysis = analyze_technical(df)
    await cache_indicators(redis, instrument_id, analysis)

    # Sentinel: if analyze_technical gets called, we'd see the monkeypatched
    # exception. analyze_with_cache should NOT reach it on full cache hit.
    from backend.app.analysis import technical as tech_mod

    def _boom(_df: pd.DataFrame):
        raise AssertionError("analyze_technical should not be called on full cache hit")

    monkeypatch.setattr(tech_mod, "analyze_technical", _boom)

    out = await analyze_with_cache(redis, instrument_id, df)
    assert out.composite_score == pytest.approx(analysis.composite_score)


async def test_analyze_with_cache_miss_populates_cache(redis):
    df = _build_ohlcv(n=252)
    instrument_id = uuid4()
    # First call: cache empty → computes and writes.
    first = await analyze_with_cache(redis, instrument_id, df)
    assert first.composite_score is not None
    # Verify cache populated.
    assert await redis.exists(f"tech:{instrument_id}:rsi") == 1
    # Second call: cache hit → same composite.
    second = await analyze_with_cache(redis, instrument_id, df)
    assert second.composite_score == pytest.approx(first.composite_score)
