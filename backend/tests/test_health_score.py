"""Tests for the Portfolio Health Score engine and API endpoint."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio
from backend.app.analysis.health_score import (
    compute_diversification,
    compute_fundamental,
    compute_health_score,
    compute_risk_adjusted,
    compute_technical,
)
from backend.app.api import health_score as health_score_module
from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.main import app
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.instruments import Instrument
from backend.app.models.positions import Position
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# See note in test_risk_meter.py: no module-level asyncio marker because this
# file mixes sync engine tests with async API tests.


# ---- Engine unit tests -----------------------------------------------------


def test_diversification_scales_with_holdings() -> None:
    single = compute_diversification([1.0])
    many = compute_diversification([1.0] * 20)
    assert single.score == 0.0
    assert many.score is not None
    assert many.score >= 95.0


def test_fundamental_averages_non_none_only() -> None:
    component = compute_fundamental([80.0, None, 60.0])
    assert component.score == 70.0
    assert component.detail["scored_holdings"] == 2


def test_fundamental_all_none_returns_none() -> None:
    component = compute_fundamental([None, None])
    assert component.score is None


def test_technical_rescales_to_0_100() -> None:
    component = compute_technical([0.0, 0.0])
    assert component.score == 50.0
    neg = compute_technical([-1.0])
    assert neg.score == 0.0
    pos = compute_technical([1.0])
    assert pos.score == 100.0


def test_risk_adjusted_none_without_benchmark() -> None:
    component = compute_risk_adjusted(pd.Series(np.random.randn(100)), None)
    assert component.score is None


def test_risk_adjusted_returns_score_with_benchmark() -> None:
    rng = np.random.default_rng(1)
    port = pd.Series(rng.normal(0.001, 0.01, 200))
    bench = pd.Series(rng.normal(0.0, 0.01, 200))
    component = compute_risk_adjusted(port, bench)
    assert component.score is not None
    assert 0.0 <= component.score <= 100.0


def test_health_score_overall_shape() -> None:
    """AC #9: overall 0-100 with 4 component breakdown."""
    result = compute_health_score(
        holding_weights=[0.5, 0.5],
        fundamental_scores=[80.0, 60.0],
        technical_scores=[0.5, -0.2],
        portfolio_returns=pd.Series(dtype=float),
        benchmark_returns=None,
    )
    assert 0 <= result.overall_score <= 100
    names = {c.name for c in result.components}
    assert names == {"diversification", "fundamental", "technical", "risk_adjusted"}


# ---- API fixtures ----------------------------------------------------------


@pytest_asyncio.fixture
async def api_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sc: Instrument.__table__.create(sc))
        await conn.run_sync(lambda sc: BrokerConnection.__table__.create(sc))
        await conn.run_sync(lambda sc: Position.__table__.create(sc))
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _build_close(n: int = 252, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.015, n)
    close = 100.0 * np.cumprod(1.0 + rets)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.Series(close, index=idx)


@pytest_asyncio.fixture
async def api_client(
    api_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    import fakeredis.aioredis

    dummy_user = User(id=uuid4(), email="t@example.com", password_hash="x", is_active=True)

    async def _session_override() -> AsyncGenerator[AsyncSession, None]:
        yield api_session

    async def _user_override() -> User:
        return dummy_user

    async def _fake_load(_sess, instrument_id: UUID, bars: int = 252) -> pd.DataFrame:
        seed = int(instrument_id.int % 2**32)
        return pd.DataFrame({"close": _build_close(n=bars, seed=seed)})

    monkeypatch.setattr(health_score_module, "load_ohlcv_from_db", _fake_load)

    fake_redis = fakeredis.aioredis.FakeRedis()

    def _redis_override() -> fakeredis.aioredis.FakeRedis:
        return fake_redis

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_redis] = _redis_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await fake_redis.aclose()


async def _seed(session: AsyncSession, user_id: UUID, *, as_of: datetime | None = None) -> None:
    conn = BrokerConnection(
        id=uuid4(),
        user_id=user_id,
        broker="alpaca",
        account_id="acct-1",
        status="active",
        access_token_encrypted=b"x",
        refresh_token_encrypted=None,
        token_expires_at=None,
    )
    session.add(conn)
    await session.flush()
    ts = as_of or datetime.now(UTC)
    for sym in ["AAA", "BBB"]:
        inst = Instrument(
            id=uuid4(),
            symbol=sym,
            exchange="NASDAQ",
            name=sym,
            currency="USD",
            asset_class="equity",
        )
        session.add(inst)
        await session.flush()
        session.add(
            Position(
                id=uuid4(),
                broker_connection_id=conn.id,
                instrument_id=inst.id,
                quantity=Decimal("1"),
                avg_cost=Decimal("100"),
                currency="USD",
                as_of=ts,
            )
        )
    await session.flush()


# ---- API tests -------------------------------------------------------------


async def test_health_score_endpoint_returns_components(
    api_session: AsyncSession, api_client: AsyncClient
) -> None:
    """AC #10: endpoint returns overall score + 4 component scores."""
    from backend.app.auth.dependencies import get_current_user as _get_user

    user = await app.dependency_overrides[_get_user]()
    await _seed(api_session, user.id)

    resp = await api_client.get("/api/portfolio/health-score")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert 0 <= body["overall_score"] <= 100
    names = {c["name"] for c in body["components"]}
    assert names == {"diversification", "fundamental", "technical", "risk_adjusted"}


async def test_health_score_daily_cache(api_session: AsyncSession, api_client: AsyncClient) -> None:
    """AC #11: results are cached daily (not recomputed on every request)."""
    from backend.app.auth.dependencies import get_current_user as _get_user

    user = await app.dependency_overrides[_get_user]()
    await _seed(api_session, user.id)

    first = (await api_client.get("/api/portfolio/health-score")).json()
    second = (await api_client.get("/api/portfolio/health-score")).json()
    # Cached payload implies identical computed_at timestamp (recompute would
    # produce a different ISO string since we advance the clock naturally).
    assert first["computed_at"] == second["computed_at"]


async def test_health_score_stale_warning_over_24h(
    api_session: AsyncSession, api_client: AsyncClient
) -> None:
    """AC #14: data > 24h old → 'Data outdated' warning flag."""
    from backend.app.auth.dependencies import get_current_user as _get_user

    user = await app.dependency_overrides[_get_user]()
    await _seed(api_session, user.id, as_of=datetime.now(UTC) - timedelta(hours=30))
    resp = await api_client.get("/api/portfolio/health-score")
    body = resp.json()
    assert body["staleness"] == "very_stale"
    assert body["stale_warning"] is not None
    assert "outdated" in body["stale_warning"].lower()
