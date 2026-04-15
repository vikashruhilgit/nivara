"""Tests for the Risk Meter engine and API endpoints.

Covers all acceptance criteria for Job M3-16. Uses the same SQLite +
monkeypatch pattern as :mod:`backend.tests.test_risk_api` so we can run
without Postgres partitioning.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio
from backend.app.analysis.risk_meter import (
    compute_concentration,
    compute_drawdown,
    compute_events,
    compute_risk_meter,
    compute_volatility_var,
)
from backend.app.api import health_score as health_score_module
from backend.app.api import risk_meter as risk_meter_module
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

# asyncio_mode = auto in pyproject.toml runs async tests automatically; we do
# not set a module-level `pytestmark` here because several tests in this file
# are plain sync functions (engine unit tests) and the module-wide marker
# emits spurious warnings for them.


# ---- Engine unit tests -----------------------------------------------------


def test_concentration_single_holding_is_100() -> None:
    """AC #1: single holding → concentration component = 100 (HHI max)."""
    component = compute_concentration([1.0])
    assert component.score == 100.0
    assert component.detail["hhi"] == 1.0


def test_concentration_twenty_equal_weight_is_low() -> None:
    """AC #2: 20 equal-weight holdings → concentration component ~ 5."""
    component = compute_concentration([1.0] * 20)
    assert component.score is not None
    assert 4.5 <= component.score <= 5.5
    # HHI for 20 equal-weight = 1/20 = 0.05.
    assert component.detail["hhi"] == pytest.approx(0.05, abs=0.001)


def test_concentration_empty_weights_returns_none() -> None:
    component = compute_concentration([])
    assert component.score is None


def test_volatility_var_insufficient_data_returns_none() -> None:
    short_series = pd.Series(np.linspace(100, 105, 10))
    component = compute_volatility_var({"X": 1.0}, {"X": short_series})
    assert component.score is None


def test_volatility_var_saturates_at_5pct() -> None:
    """Highly volatile series should saturate the VaR component toward 100."""
    rng = np.random.default_rng(7)
    noise = rng.normal(0.0, 0.08, 200)
    prices = 100.0 * np.cumprod(1.0 + noise)
    series = pd.Series(prices)
    component = compute_volatility_var({"X": 1.0}, {"X": series})
    assert component.score is not None
    assert component.score >= 80.0


def test_drawdown_on_monotonic_series_is_zero() -> None:
    series = pd.Series(np.linspace(100, 150, 100))
    component = compute_drawdown({"X": 1.0}, {"X": series})
    assert component.score == 0.0


def test_drawdown_on_peaked_series() -> None:
    prices = np.concatenate([np.linspace(100, 200, 50), np.linspace(200, 140, 50)])
    series = pd.Series(prices)
    component = compute_drawdown({"X": 1.0}, {"X": series})
    assert component.score is not None
    assert component.score > 50.0  # 30% drawdown / 40% saturation ≈ 75


def test_events_no_calendar_returns_zero() -> None:
    """AC #8 / risk mitigation: None upcoming events → component = 0."""
    component = compute_events(None, today=date(2026, 4, 15))
    assert component.score == 0.0


def test_events_proximity_weighted() -> None:
    today = date(2026, 4, 15)
    events = [today, today + timedelta(days=1), today + timedelta(days=10)]
    component = compute_events(events, today=today)
    # Today event contributes 5/5 = 1.0 raw → saturated at 1.0 → 100.
    assert component.score == 100.0
    assert component.detail["upcoming"] == 2  # events within 5d window


def test_classification_bands() -> None:
    """AC #3, #4, #5: 0-30 green, 31-60 yellow, 61-100 red."""
    # Directly synthesise component outputs by driving the classifier via
    # the orchestrator with tailored inputs.
    # Low concentration (many equal weights), no price data, no events.
    green = compute_risk_meter(
        holding_weights=[1.0] * 20,
        weights_by_symbol={},
        price_series={},
        upcoming_events=None,
        today=date(2026, 4, 15),
    )
    assert green.color == "green"
    assert green.overall_score <= 30

    # Mid: two-holding portfolio, no price data, one event in 3 days.
    today = date(2026, 4, 15)
    yellow = compute_risk_meter(
        holding_weights=[0.5, 0.5],
        weights_by_symbol={},
        price_series={},
        upcoming_events=[today + timedelta(days=3)],
        today=today,
    )
    assert 31 <= yellow.overall_score <= 60
    assert yellow.color == "yellow"

    # High: single holding + event tomorrow.
    red = compute_risk_meter(
        holding_weights=[1.0],
        weights_by_symbol={},
        price_series={},
        upcoming_events=[today + timedelta(days=1)],
        today=today,
    )
    assert red.overall_score > 60
    assert red.color == "red"


# ---- API fixtures ----------------------------------------------------------


@pytest_asyncio.fixture
async def api_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # Create minimal tables needed by these routes. We bypass Postgres
        # JSONB-heavy tables (audit_log, etc.) and price_history (partitioned)
        # by monkeypatching the price loader below.
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

    async def _fake_bulk(
        _sess, instrument_ids: list[UUID], bars: int = 252
    ) -> dict[UUID, pd.Series]:
        # Deterministic per-instrument series so requests are stable.
        return {iid: _build_close(n=bars, seed=int(iid.int % 2**32)) for iid in instrument_ids}

    monkeypatch.setattr(risk_meter_module, "load_close_series_bulk", _fake_bulk)
    monkeypatch.setattr(health_score_module, "load_close_series_bulk", _fake_bulk)

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


async def _seed_portfolio(
    session: AsyncSession,
    user_id: UUID,
    symbols: list[tuple[str, Decimal]],
    *,
    as_of: datetime | None = None,
) -> None:
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
    for symbol, qty in symbols:
        inst = Instrument(
            id=uuid4(),
            symbol=symbol,
            exchange="NASDAQ",
            name=symbol,
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
                quantity=qty,
                avg_cost=Decimal("100"),
                currency="USD",
                as_of=ts,
            )
        )
    await session.flush()


# ---- API tests -------------------------------------------------------------


async def test_risk_meter_endpoint_returns_overall_and_color(
    api_session: AsyncSession, api_client: AsyncClient
) -> None:
    """AC #6: GET /api/portfolio/risk-meter returns overall score + color."""
    # Pull the current_user from the dependency override by invoking /health
    # first — not strictly necessary, but confirms app wiring.
    from backend.app.auth.dependencies import get_current_user as _get_user

    user = await app.dependency_overrides[_get_user]()
    await _seed_portfolio(
        api_session,
        user.id,
        [("AAA", Decimal("10")), ("BBB", Decimal("5")), ("CCC", Decimal("3"))],
    )

    resp = await api_client.get("/api/portfolio/risk-meter")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert 0 <= body["overall_score"] <= 100
    assert body["color"] in {"green", "yellow", "red"}
    assert body["staleness"] == "fresh"


async def test_risk_meter_drilldown_returns_four_components(
    api_session: AsyncSession, api_client: AsyncClient
) -> None:
    """AC #7: drill-down returns all 4 components with individual scores and weights."""
    from backend.app.auth.dependencies import get_current_user as _get_user

    user = await app.dependency_overrides[_get_user]()
    await _seed_portfolio(api_session, user.id, [("AAA", Decimal("1")), ("BBB", Decimal("1"))])

    resp = await api_client.get("/api/portfolio/risk-meter/drilldown")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    names = {c["name"] for c in body["components"]}
    assert names == {"concentration", "volatility_var", "drawdown", "events"}
    weights = sum(c["weight"] for c in body["components"])
    assert weights == pytest.approx(1.0, abs=0.001)


async def test_risk_meter_stale_flags(api_session: AsyncSession, api_client: AsyncClient) -> None:
    """AC #12, #13: 4-24h data → stale, >24h → very_stale."""
    from backend.app.auth.dependencies import get_current_user as _get_user

    user = await app.dependency_overrides[_get_user]()
    stale_ts = datetime.now(UTC) - timedelta(hours=6)
    await _seed_portfolio(api_session, user.id, [("AAA", Decimal("1"))], as_of=stale_ts)
    resp = await api_client.get("/api/portfolio/risk-meter")
    body = resp.json()
    assert body["staleness"] == "stale"
    assert body["stale_reason"] is not None

    # Nuke and re-seed with very-stale timestamp.
    from sqlalchemy import delete

    await api_session.execute(delete(Position))
    await api_session.execute(delete(BrokerConnection))
    await api_session.execute(delete(Instrument))
    await api_session.flush()
    very_stale_ts = datetime.now(UTC) - timedelta(hours=30)
    await _seed_portfolio(api_session, user.id, [("AAA", Decimal("1"))], as_of=very_stale_ts)
    resp2 = await api_client.get("/api/portfolio/risk-meter")
    body2 = resp2.json()
    assert body2["staleness"] == "very_stale"
