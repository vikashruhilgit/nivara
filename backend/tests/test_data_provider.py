"""Contract tests for the :class:`DataProvider` base layer.

Covers:
* Error hierarchy shape (all concrete errors inherit from DataProviderError).
* Pydantic v2 schemas (OHLCVBar, Quote, Fundamentals) round-trip correctly.
* Redis cache helpers hit/miss semantics and corrupt-payload tolerance.
* :func:`resolve_yahoo_symbol` convention for NASDAQ/NSE/BSE.

These tests do **not** hit Yahoo's network. See ``test_yahoo_provider.py`` for
provider-level behaviour with upstream mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import fakeredis.aioredis
import pytest
from backend.app.data.base import DataProvider, Fundamentals, OHLCVBar, Quote
from backend.app.data.cache import (
    FUNDAMENTALS_TTL_SECONDS,
    OHLCV_TTL_SECONDS,
    fundamentals_key,
    get_model,
    get_model_list,
    invalidate,
    invalidate_symbol,
    ohlcv_key,
    set_model,
    set_model_list,
)
from backend.app.data.errors import (
    DataProviderError,
    RateLimitError,
    SymbolNotFoundError,
    UpstreamUnavailableError,
)
from backend.app.data.yahoo import resolve_yahoo_symbol

# ---- Error hierarchy -------------------------------------------------------


def test_all_errors_inherit_from_data_provider_error() -> None:
    for cls in (SymbolNotFoundError, RateLimitError, UpstreamUnavailableError):
        assert issubclass(cls, DataProviderError)


def test_rate_limit_error_carries_retry_hint() -> None:
    err = RateLimitError("slow down", provider="yahoo", retry_after_seconds=5)
    assert err.provider == "yahoo"
    assert err.retry_after_seconds == 5


def test_data_provider_error_default_provider() -> None:
    err = DataProviderError("boom")
    assert err.provider == "unknown"
    assert "boom" in str(err)


# ---- Pydantic schemas ------------------------------------------------------


def test_ohlcv_bar_round_trip() -> None:
    bar = OHLCVBar(
        timestamp=datetime(2026, 1, 2, 15, 30, tzinfo=UTC),
        open=Decimal("100.50000000"),
        high=Decimal("101.00000000"),
        low=Decimal("99.00000000"),
        close=Decimal("100.75000000"),
        volume=1_234_567,
    )
    payload = bar.model_dump_json()
    restored = OHLCVBar.model_validate_json(payload)
    assert restored == bar
    # Decimal preserved exactly (not float) through JSON.
    assert restored.open == Decimal("100.50000000")


def test_quote_defaults_delay_to_15_minutes() -> None:
    q = Quote(
        symbol="AAPL",
        price=Decimal("180.00"),
        timestamp=datetime.now(UTC),
        currency="USD",
    )
    assert q.delay_minutes == 15


def test_fundamentals_tolerates_missing_fields() -> None:
    f = Fundamentals(symbol="AAPL", currency="USD", fetched_at=datetime.now(UTC))
    assert f.market_cap is None
    assert f.pe_ratio is None


# ---- Symbol resolution -----------------------------------------------------


@pytest.mark.parametrize(
    ("exchange", "symbol", "expected"),
    [
        ("NASDAQ", "AAPL", "AAPL"),
        ("NYSE", "IBM", "IBM"),
        ("nyse", "ibm", "IBM"),
        ("NSE", "RELIANCE", "RELIANCE.NS"),
        ("BSE", "RELIANCE", "RELIANCE.BO"),
    ],
)
def test_resolve_yahoo_symbol_known_exchanges(exchange: str, symbol: str, expected: str) -> None:
    instrument = SimpleNamespace(symbol=symbol, exchange=exchange)
    assert resolve_yahoo_symbol(instrument) == expected  # type: ignore[arg-type]


def test_resolve_yahoo_symbol_unknown_exchange_raises() -> None:
    instrument = SimpleNamespace(symbol="FOO", exchange="LSE")
    with pytest.raises(DataProviderError) as exc:
        resolve_yahoo_symbol(instrument)  # type: ignore[arg-type]
    assert "LSE" in str(exc.value)


# ---- Cache helpers ---------------------------------------------------------


@pytest.fixture
async def fake_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def test_cache_keys_are_stable() -> None:
    assert ohlcv_key("yahoo", "AAPL", 252) == "data:yahoo:ohlcv:AAPL:252"
    assert fundamentals_key("yahoo", "AAPL") == "data:yahoo:fundamentals:AAPL"


async def test_cache_set_and_get_single_model(fake_redis) -> None:
    f = Fundamentals(symbol="AAPL", currency="USD", fetched_at=datetime.now(UTC))
    key = fundamentals_key("yahoo", "AAPL")
    await set_model(fake_redis, key, f, ttl=FUNDAMENTALS_TTL_SECONDS)
    restored = await get_model(fake_redis, key, Fundamentals)
    assert restored is not None
    assert restored.symbol == "AAPL"


async def test_cache_miss_returns_none(fake_redis) -> None:
    assert (await get_model(fake_redis, fundamentals_key("yahoo", "GHOST"), Fundamentals)) is None


async def test_cache_corrupt_payload_returns_none(fake_redis) -> None:
    key = fundamentals_key("yahoo", "AAPL")
    await fake_redis.set(key, "not-json-at-all")
    # Must not raise — caller treats corrupt cache as a miss.
    assert await get_model(fake_redis, key, Fundamentals) is None


async def test_cache_set_and_get_list(fake_redis) -> None:
    bars = [
        OHLCVBar(
            timestamp=datetime(2026, 1, d, tzinfo=UTC),
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("1"),
            close=Decimal("2"),
            volume=100,
        )
        for d in range(1, 4)
    ]
    key = ohlcv_key("yahoo", "AAPL", 252)
    await set_model_list(fake_redis, key, bars, ttl=OHLCV_TTL_SECONDS)
    restored = await get_model_list(fake_redis, key, OHLCVBar)
    assert restored == bars


async def test_cache_list_corrupt_returns_none(fake_redis) -> None:
    key = ohlcv_key("yahoo", "AAPL", 252)
    await fake_redis.set(key, "{ not a list }")
    assert await get_model_list(fake_redis, key, OHLCVBar) is None


async def test_invalidate_deletes_keys(fake_redis) -> None:
    f = Fundamentals(symbol="AAPL", currency="USD", fetched_at=datetime.now(UTC))
    key = fundamentals_key("yahoo", "AAPL")
    await set_model(fake_redis, key, f, ttl=60)
    assert await invalidate(fake_redis, key) == 1
    assert await fake_redis.get(key) is None


async def test_invalidate_symbol_removes_all_provider_keys(fake_redis) -> None:
    f = Fundamentals(symbol="AAPL", currency="USD", fetched_at=datetime.now(UTC))
    await set_model(fake_redis, fundamentals_key("yahoo", "AAPL"), f, ttl=60)
    await set_model(fake_redis, fundamentals_key("yahoo", "AAPL"), f, ttl=60)
    # Keep one unrelated key to ensure selective delete.
    other = Fundamentals(symbol="MSFT", currency="USD", fetched_at=datetime.now(UTC))
    await set_model(fake_redis, fundamentals_key("yahoo", "MSFT"), other, ttl=60)

    deleted = await invalidate_symbol(fake_redis, "yahoo", "AAPL")
    assert deleted >= 1
    assert await fake_redis.get(fundamentals_key("yahoo", "MSFT")) is not None


# ---- Abstract base contract ------------------------------------------------


async def test_data_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        DataProvider()  # type: ignore[abstract]
