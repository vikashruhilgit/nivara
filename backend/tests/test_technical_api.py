"""HTTP-layer tests for GET /api/analysis/{symbol}/technical.

The price_history table is Postgres-partitioned (RANGE on ``timestamp``),
which SQLite cannot render. Rather than maintaining a parallel non-
partitioned schema for tests, we monkeypatch ``load_ohlcv_from_db`` to
return a synthetic OHLCV frame directly. This keeps the API surface under
test (routing, auth, instrument lookup, response shape) without dragging in
partition DDL.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

import fakeredis.aioredis
import numpy as np
import pandas as pd
import pytest
import pytest_asyncio
from backend.app.api import analysis as analysis_module
from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.main import app
from backend.app.models.instruments import Instrument
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


def _build_ohlcv(n: int = 252, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.01, n)
    close = 100.0 * np.cumprod(1.0 + rets)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": np.concatenate([[100.0], close[:-1]]),
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


@pytest_asyncio.fixture
async def api_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sc: Instrument.__table__.create(sc))
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def fake_redis() -> AsyncGenerator[fakeredis.aioredis.FakeRedis, None]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def api_client(
    api_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    dummy_user = User(email="t@example.com", password_hash="x", is_active=True)

    async def _session_override() -> AsyncGenerator[AsyncSession, None]:
        yield api_session

    async def _user_override() -> User:
        return dummy_user

    def _redis_override() -> fakeredis.aioredis.FakeRedis:
        return fake_redis

    # Replace the DB loader with a synthetic OHLCV producer. The API only
    # cares that it gets a usable frame; the DB path itself is covered by
    # the PriceHistory model tests (when they exist for M1.2).
    async def _fake_load(_sess, instrument_id: UUID, bars: int = 252) -> pd.DataFrame:
        # A missing instrument is signalled with an empty frame; real rows
        # always come back sorted ascending with the expected columns.
        return _build_ohlcv(n=bars)

    monkeypatch.setattr(analysis_module, "load_ohlcv_from_db", _fake_load)

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_redis] = _redis_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_technical_endpoint_returns_all_indicators(
    api_session: AsyncSession, api_client: AsyncClient
) -> None:
    inst = Instrument(
        symbol="AAPL",
        exchange="NASDAQ",
        name="Apple Inc.",
        currency="USD",
        asset_class="equity",
    )
    api_session.add(inst)
    await api_session.flush()

    resp = await api_client.get("/api/analysis/AAPL/technical", params={"exchange": "NASDAQ"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert body["exchange"] == "NASDAQ"
    assert body["bars_analyzed"] == 252
    # All 6 indicators present.
    for name in ("rsi", "macd", "ma_alignment", "bollinger", "volume", "atr"):
        assert name in body, f"missing indicator: {name}"
        assert "value" in body[name]
        assert "raw" in body[name]
        assert "insufficient_data" in body[name]
    assert -1.0 <= body["composite_score"] <= 1.0
    assert body["action"] in {"strong_sell", "sell", "hold", "buy", "strong_buy"}


async def test_technical_endpoint_404_for_unknown_instrument(
    api_client: AsyncClient,
) -> None:
    resp = await api_client.get("/api/analysis/NOSUCH/technical", params={"exchange": "NASDAQ"})
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


async def test_technical_endpoint_404_for_empty_price_history(
    api_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If price_history is empty for a valid instrument we return 404 with a clear message."""
    dummy_user = User(email="t@example.com", password_hash="x", is_active=True)
    inst = Instrument(
        symbol="EMPTY", exchange="NASDAQ", name="Empty", currency="USD", asset_class="equity"
    )
    api_session.add(inst)
    await api_session.flush()

    fake_redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _session_override() -> AsyncGenerator[AsyncSession, None]:
        yield api_session

    async def _user_override() -> User:
        return dummy_user

    def _redis_override() -> fakeredis.aioredis.FakeRedis:
        return fake_redis_client

    async def _empty_load(_sess, _id, bars: int = 252) -> pd.DataFrame:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    monkeypatch.setattr(analysis_module, "load_ohlcv_from_db", _empty_load)
    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_redis] = _redis_override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/analysis/EMPTY/technical", params={"exchange": "NASDAQ"})
        assert resp.status_code == 404
        assert "no price history" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()
        await fake_redis_client.aclose()


async def test_technical_endpoint_caches_on_second_call(
    api_session: AsyncSession, api_client: AsyncClient, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    inst = Instrument(
        symbol="AAPL",
        exchange="NASDAQ",
        name="Apple Inc.",
        currency="USD",
        asset_class="equity",
    )
    api_session.add(inst)
    await api_session.flush()

    r1 = await api_client.get("/api/analysis/AAPL/technical", params={"exchange": "NASDAQ"})
    assert r1.status_code == 200
    # Cache key should be populated.
    cache_key = f"tech:{inst.id}:rsi"
    assert await fake_redis.exists(cache_key) == 1

    r2 = await api_client.get("/api/analysis/AAPL/technical", params={"exchange": "NASDAQ"})
    assert r2.status_code == 200
    assert r2.json()["composite_score"] == pytest.approx(r1.json()["composite_score"])
