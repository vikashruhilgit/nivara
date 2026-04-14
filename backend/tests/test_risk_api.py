"""HTTP-layer tests for GET /api/analysis/{symbol}/risk.

Mirrors the pattern used by :mod:`backend.tests.test_technical_api`: we
monkeypatch ``load_ohlcv_from_db`` to return a synthetic OHLCV frame because
``price_history`` is Postgres-partitioned and not rendered by SQLite. This
keeps the API under test (routing, auth, instrument lookup, response shape,
error paths) without pulling in partition DDL.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

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
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


def _build_ohlcv(n: int = 252, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.015, n)
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
async def api_client(
    api_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    dummy_user = User(email="t@example.com", password_hash="x", is_active=True)

    async def _session_override() -> AsyncGenerator[AsyncSession, None]:
        yield api_session

    async def _user_override() -> User:
        return dummy_user

    async def _fake_load(_sess, instrument_id: UUID, bars: int = 252) -> pd.DataFrame:
        return _build_ohlcv(n=bars)

    monkeypatch.setattr(analysis_module, "load_ohlcv_from_db", _fake_load)

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = _user_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_risk_endpoint_returns_full_panel(
    api_session: AsyncSession, api_client: AsyncClient
) -> None:
    """AC #9: endpoint returns VaR, volatility (30d/90d), drawdown, risk score, data quality."""
    inst = Instrument(
        symbol="AAPL",
        exchange="NASDAQ",
        name="Apple Inc.",
        currency="USD",
        asset_class="equity",
    )
    api_session.add(inst)
    await api_session.flush()

    resp = await api_client.get("/api/analysis/AAPL/risk", params={"exchange": "NASDAQ"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["symbol"] == "AAPL"
    assert body["exchange"] == "NASDAQ"
    assert body["bars_analyzed"] == 252

    # VaR block: with 252 bars we expect full computation.
    assert body["var"]["status"] == "ok"
    assert body["var"]["var_95"] is not None
    assert body["var"]["var_99"] is not None
    assert body["var"]["var_99"] >= body["var"]["var_95"]
    assert body["var"]["lookback_days"] == 251  # 252 closes -> 251 returns

    # Volatility block.
    assert body["volatility"]["vol_30d"] is not None
    assert body["volatility"]["vol_90d"] is not None
    assert body["volatility"]["estimated"] is False

    # Drawdown block (may legitimately be 0 on synthetic monotonic segments).
    assert "drawdown" in body["drawdown"]
    assert body["drawdown"]["peak_price"] is not None
    assert body["drawdown"]["current_price"] is not None

    # Risk score block.
    assert 0 <= body["risk_score"]["score"] <= 100
    assert body["risk_score"]["proxy_based"] is False

    # Data quality block.
    assert body["data_quality"]["observations"] == 252
    assert body["data_quality"]["excluded_from_correlation"] is False


async def test_risk_endpoint_404_for_unknown_instrument(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/analysis/NOSUCH/risk", params={"exchange": "NASDAQ"})
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


async def test_risk_endpoint_404_for_empty_price_history(
    api_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty price_history for a valid instrument -> 404 with clear message."""
    dummy_user = User(email="t@example.com", password_hash="x", is_active=True)
    inst = Instrument(
        symbol="EMPTY", exchange="NASDAQ", name="Empty", currency="USD", asset_class="equity"
    )
    api_session.add(inst)
    await api_session.flush()

    async def _session_override() -> AsyncGenerator[AsyncSession, None]:
        yield api_session

    async def _user_override() -> User:
        return dummy_user

    async def _empty_load(_sess, _id, bars: int = 252) -> pd.DataFrame:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    monkeypatch.setattr(analysis_module, "load_ohlcv_from_db", _empty_load)
    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = _user_override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/analysis/EMPTY/risk", params={"exchange": "NASDAQ"})
        assert resp.status_code == 404
        assert "no price history" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


async def test_risk_endpoint_uses_sector_proxy_on_thin_history(
    api_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #4 over the wire: with <30 bars the engine proxies and flags it."""
    dummy_user = User(email="t@example.com", password_hash="x", is_active=True)
    inst = Instrument(
        symbol="NEW",
        exchange="NASDAQ",
        name="Newly listed",
        currency="USD",
        asset_class="equity",
    )
    api_session.add(inst)
    await api_session.flush()

    async def _session_override() -> AsyncGenerator[AsyncSession, None]:
        yield api_session

    async def _user_override() -> User:
        return dummy_user

    async def _short_load(_sess, _id, bars: int = 252) -> pd.DataFrame:
        # Endpoint enforces bars>=30, but we ignore that and return a shorter
        # frame to simulate a freshly-listed instrument with thin history.
        return _build_ohlcv(n=20)

    monkeypatch.setattr(analysis_module, "load_ohlcv_from_db", _short_load)
    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = _user_override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(
                "/api/analysis/NEW/risk",
                params={"exchange": "NASDAQ", "sector": "Technology"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["var"]["status"] == "insufficient_data"
        assert body["volatility"]["estimated"] is True
        assert body["risk_score"]["proxy_based"] is True
        assert body["risk_score"]["sector"] == "Technology"
    finally:
        app.dependency_overrides.clear()
