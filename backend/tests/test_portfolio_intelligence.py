"""Tests for Portfolio Intelligence engine + API (:mod:`backend.app.intelligence.portfolio`)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import fakeredis.aioredis
import pytest
import pytest_asyncio
from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.intelligence.portfolio import (
    DISCLAIMER_TEXT,
    SECTOR_CONCENTRATION_THRESHOLD,
    PortfolioIntelligenceService,
)
from backend.app.main import app
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.fx_rates import FxRate
from backend.app.models.instruments import Instrument
from backend.app.models.positions import Position
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from backend.app.schemas.benchmark import BenchmarkReturn
from backend.app.services.benchmark import NIFTY_SYMBOL, SP500_SYMBOL, BenchmarkService
from backend.app.services.fx import FxService
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---- DB fixture: SQLite with only the tables we need ---------------------


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sc: Instrument.__table__.create(sc))
        await conn.run_sync(lambda sc: BrokerConnection.__table__.create(sc))
        await conn.run_sync(lambda sc: Position.__table__.create(sc))
        await conn.run_sync(lambda sc: FxRate.__table__.create(sc))
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_instrument(
    db: AsyncSession,
    *,
    symbol: str,
    exchange: str,
    currency: str,
    sector: str | None = None,
) -> Instrument:
    inst = Instrument(
        id=uuid4(),
        symbol=symbol,
        exchange=exchange,
        name=symbol,
        currency=currency,
        asset_class="equity",
    )
    # The engine uses getattr(instrument, "sector", None) so we can attach
    # sector as a plain attribute for tests without an ORM migration.
    if sector is not None:
        inst.sector = sector  # type: ignore[attr-defined]
    db.add(inst)
    await db.flush()
    return inst


async def _seed_position(
    db: AsyncSession,
    *,
    conn_id: UUID,
    instrument_id: UUID,
    qty: str,
    price: str,
    currency: str,
    as_of: datetime | None = None,
) -> None:
    db.add(
        Position(
            id=uuid4(),
            broker_connection_id=conn_id,
            instrument_id=instrument_id,
            quantity=Decimal(qty),
            avg_cost=Decimal(price),
            currency=currency,
            as_of=as_of or datetime.now(UTC),
        )
    )
    await db.flush()


async def _seed_connection(db: AsyncSession, *, user_id: UUID) -> BrokerConnection:
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
    db.add(conn)
    await db.flush()
    return conn


async def _seed_fx(
    db: AsyncSession,
    *,
    base: str,
    quote: str,
    rate: str,
    as_of: datetime,
) -> None:
    db.add(
        FxRate(
            id=uuid4(),
            base_currency=base,
            quote_currency=quote,
            rate=Decimal(rate),
            as_of=as_of,
        )
    )
    await db.flush()


def _stub_benchmark_service(
    nifty_return: float = 0.0, sp500_return: float = 0.0
) -> BenchmarkService:
    """Return a BenchmarkService whose get_return is monkeypatched to stubs."""

    class _Stub(BenchmarkService):
        def __init__(self) -> None:  # type: ignore[override]
            # no redis needed
            pass

        async def get_return(  # type: ignore[override]
            self, *, symbol: str, period_days: int = 30
        ) -> BenchmarkReturn:
            now = datetime.now(UTC)
            start = now - timedelta(days=period_days)
            if symbol == NIFTY_SYMBOL:
                ret = Decimal(str(nifty_return))
                ccy = "INR"
            elif symbol == SP500_SYMBOL:
                ret = Decimal(str(sp500_return))
                ccy = "USD"
            else:
                ret = Decimal("0")
                ccy = "USD"
            return BenchmarkReturn(
                symbol=symbol,
                currency=ccy,
                period_days=period_days,
                period_start=start,
                period_end=now,
                close_start=Decimal("100"),
                close_end=Decimal("100") * (Decimal("1") + ret),
                total_return=ret,
                stale=False,
            )

    return _Stub()


# ---- Engine tests ---------------------------------------------------------


async def test_mixed_portfolio_sector_allocation_both_markets(db: AsyncSession) -> None:
    """AC #1: AAPL (US) + RELIANCE (IN) → sector allocation per market."""
    user_id = uuid4()
    conn = await _seed_connection(db, user_id=user_id)
    aapl = await _seed_instrument(
        db, symbol="AAPL", exchange="NASDAQ", currency="USD", sector="Technology"
    )
    reliance = await _seed_instrument(
        db, symbol="RELIANCE", exchange="NSE", currency="INR", sector="Energy"
    )
    await _seed_position(
        db, conn_id=conn.id, instrument_id=aapl.id, qty="10", price="200", currency="USD"
    )
    await _seed_position(
        db,
        conn_id=conn.id,
        instrument_id=reliance.id,
        qty="5",
        price="2000",
        currency="INR",
    )
    # USD base: need INR->USD rate.
    await _seed_fx(db, base="INR", quote="USD", rate="0.012", as_of=datetime.now(UTC))

    service = PortfolioIntelligenceService(
        session=db,
        fx=FxService(db),
        benchmark_service=_stub_benchmark_service(),
    )
    result = await service.compute(user_id=user_id, base_currency="USD")

    assert "US" in result.sector_allocation
    assert "IN" in result.sector_allocation
    us_sectors = {e.sector for e in result.sector_allocation["US"]}
    in_sectors = {e.sector for e in result.sector_allocation["IN"]}
    assert us_sectors == {"Technology"}
    assert in_sectors == {"Energy"}


async def test_diversification_hhi_and_geography(db: AsyncSession) -> None:
    """AC #2: diversification reports HHI + geography split summing to ~1."""
    user_id = uuid4()
    conn = await _seed_connection(db, user_id=user_id)
    a = await _seed_instrument(
        db, symbol="A", exchange="NASDAQ", currency="USD", sector="Technology"
    )
    b = await _seed_instrument(db, symbol="B", exchange="NSE", currency="INR", sector="Energy")
    # $1000 in A (USD); 10000 INR * 0.1 USD/INR = $1000 in B → 50/50 geo split.
    await _seed_position(
        db, conn_id=conn.id, instrument_id=a.id, qty="10", price="100", currency="USD"
    )
    await _seed_position(
        db, conn_id=conn.id, instrument_id=b.id, qty="100", price="100", currency="INR"
    )
    await _seed_fx(db, base="INR", quote="USD", rate="0.1", as_of=datetime.now(UTC))

    service = PortfolioIntelligenceService(
        session=db, fx=FxService(db), benchmark_service=_stub_benchmark_service()
    )
    result = await service.compute(user_id=user_id, base_currency="USD")

    # Two equal-weight sectors → HHI = 0.5^2 + 0.5^2 = 0.5
    assert result.diversification.hhi == pytest.approx(0.5, abs=1e-6)
    assert result.diversification.geography["US"] == pytest.approx(0.5, abs=1e-6)
    assert result.diversification.geography["IN"] == pytest.approx(0.5, abs=1e-6)


async def test_concentrated_sector_triggers_rebalancing_with_disclaimer(
    db: AsyncSession,
) -> None:
    """AC #7 + #9: >40% sector → rebalancing suggestion WITH disclaimer."""
    user_id = uuid4()
    conn = await _seed_connection(db, user_id=user_id)
    # 90% of the portfolio in Technology.
    big = await _seed_instrument(
        db, symbol="BIG", exchange="NASDAQ", currency="USD", sector="Technology"
    )
    small = await _seed_instrument(
        db, symbol="SML", exchange="NASDAQ", currency="USD", sector="Energy"
    )
    await _seed_position(
        db, conn_id=conn.id, instrument_id=big.id, qty="90", price="100", currency="USD"
    )
    await _seed_position(
        db, conn_id=conn.id, instrument_id=small.id, qty="10", price="100", currency="USD"
    )

    service = PortfolioIntelligenceService(
        session=db, fx=FxService(db), benchmark_service=_stub_benchmark_service()
    )
    result = await service.compute(user_id=user_id, base_currency="USD")

    assert len(result.rebalancing_suggestions) >= 1
    tech_sugg = next(s for s in result.rebalancing_suggestions if s.sector == "Technology")
    assert tech_sugg.type == "sector_concentration"
    assert tech_sugg.current_pct is not None
    assert tech_sugg.current_pct > SECTOR_CONCENTRATION_THRESHOLD
    assert tech_sugg.disclaimer == DISCLAIMER_TEXT
    assert "not investment advice" in tech_sugg.disclaimer.lower()


async def test_empty_portfolio_returns_zeros(db: AsyncSession) -> None:
    """AC handling: empty portfolio → zeros and empty lists, no crash."""
    user_id = uuid4()
    service = PortfolioIntelligenceService(
        session=db, fx=FxService(db), benchmark_service=_stub_benchmark_service()
    )
    result = await service.compute(user_id=user_id, base_currency="USD")

    assert result.sector_allocation == {}
    assert result.diversification.hhi == 0.0
    assert result.diversification.geography == {}
    assert result.per_market_alpha == []
    assert result.blended_benchmark_return == 0.0
    assert result.portfolio_return == 0.0
    assert result.portfolio_alpha == 0.0
    # Empty portfolio is conservatively flagged stale: no return was computed.
    assert result.portfolio_return_stale is True
    assert result.unclassified_markets == []
    assert result.rebalancing_suggestions == []


async def test_per_market_alpha_uses_native_benchmarks(db: AsyncSession) -> None:
    """AC #3, #4: IN holdings → ^NSEI/INR; US holdings → ^GSPC/USD, no FX."""
    user_id = uuid4()
    conn = await _seed_connection(db, user_id=user_id)
    us = await _seed_instrument(
        db, symbol="US1", exchange="NASDAQ", currency="USD", sector="Technology"
    )
    inn = await _seed_instrument(db, symbol="IN1", exchange="NSE", currency="INR", sector="Energy")
    await _seed_position(
        db, conn_id=conn.id, instrument_id=us.id, qty="1", price="100", currency="USD"
    )
    await _seed_position(
        db, conn_id=conn.id, instrument_id=inn.id, qty="1", price="100", currency="INR"
    )
    await _seed_fx(db, base="INR", quote="USD", rate="0.012", as_of=datetime.now(UTC))

    service = PortfolioIntelligenceService(
        session=db,
        fx=FxService(db),
        benchmark_service=_stub_benchmark_service(nifty_return=0.05, sp500_return=0.03),
    )
    result = await service.compute(user_id=user_id, base_currency="USD")

    alpha_by_market = {a.market: a for a in result.per_market_alpha}
    assert alpha_by_market["IN"].benchmark_symbol == NIFTY_SYMBOL
    assert alpha_by_market["IN"].benchmark_currency == "INR"
    assert alpha_by_market["IN"].benchmark_return == pytest.approx(0.05)
    assert alpha_by_market["US"].benchmark_symbol == SP500_SYMBOL
    assert alpha_by_market["US"].benchmark_currency == "USD"
    assert alpha_by_market["US"].benchmark_return == pytest.approx(0.03)
    # Portfolio return is a placeholder today — both per-market entries and
    # the top-level response must flag stale until the price pipeline lands.
    assert alpha_by_market["IN"].portfolio_return_stale is True
    assert alpha_by_market["US"].portfolio_return_stale is True
    assert result.portfolio_return_stale is True
    # All positions are NSE/NASDAQ → no unclassified markets.
    assert result.unclassified_markets == []


async def test_unclassified_exchange_bucketed_as_other(db: AsyncSession) -> None:
    """LSE position → OTHER bucket: counted in geography, excluded from alpha."""
    user_id = uuid4()
    conn = await _seed_connection(db, user_id=user_id)
    us = await _seed_instrument(
        db, symbol="US1", exchange="NASDAQ", currency="USD", sector="Technology"
    )
    lse = await _seed_instrument(db, symbol="LSE1", exchange="LSE", currency="USD", sector="Energy")
    await _seed_position(
        db, conn_id=conn.id, instrument_id=us.id, qty="1", price="100", currency="USD"
    )
    await _seed_position(
        db, conn_id=conn.id, instrument_id=lse.id, qty="1", price="100", currency="USD"
    )

    service = PortfolioIntelligenceService(
        session=db,
        fx=FxService(db),
        benchmark_service=_stub_benchmark_service(nifty_return=0.0, sp500_return=0.03),
    )
    result = await service.compute(user_id=user_id, base_currency="USD")

    # Geography split includes a third OTHER bucket > 0.
    assert "OTHER" in result.diversification.geography
    assert result.diversification.geography["OTHER"] > 0
    # Per-market alpha excludes OTHER — only US should be present here.
    assert {a.market for a in result.per_market_alpha} == {"US"}
    # Unclassified raw exchange codes are surfaced for observability.
    assert result.unclassified_markets == ["LSE"]
    # LSE contributes to sector allocation (Energy → OTHER bucket).
    assert "OTHER" in result.sector_allocation
    other_sectors = {e.sector for e in result.sector_allocation["OTHER"]}
    assert other_sectors == {"Energy"}


# ---- API tests -----------------------------------------------------------


@pytest_asyncio.fixture
async def api_client(
    db: AsyncSession,
) -> AsyncGenerator[tuple[AsyncClient, User], None]:
    dummy_user = User(id=uuid4(), email="t@example.com", password_hash="x", is_active=True)
    fake_redis = fakeredis.aioredis.FakeRedis()

    async def _session_override() -> AsyncGenerator[AsyncSession, None]:
        yield db

    async def _user_override() -> User:
        return dummy_user

    def _redis_override() -> fakeredis.aioredis.FakeRedis:
        return fake_redis

    # Stub yfinance so the real BenchmarkService in the API returns quickly
    # without hitting the network. fakeredis will then cache the result.
    import sys
    import types

    import pandas as pd

    class _StubTicker:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def history(self, *args: object, **kwargs: object) -> pd.DataFrame:
            idx = pd.date_range("2024-01-01", periods=5, freq="D")
            closes = [100.0, 100.0, 100.0, 100.0, 103.0]
            return pd.DataFrame(
                {
                    "Open": closes,
                    "High": closes,
                    "Low": closes,
                    "Close": closes,
                    "Volume": [1_000_000] * 5,
                },
                index=idx,
            )

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = _StubTicker  # type: ignore[attr-defined]
    sys.modules["yfinance"] = fake_yf

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_redis] = _redis_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, dummy_user
    app.dependency_overrides.clear()
    await fake_redis.aclose()


async def test_get_intelligence_returns_expected_fields(
    db: AsyncSession, api_client: tuple[AsyncClient, User]
) -> None:
    """AC #8: GET /api/portfolio/intelligence → 200 with documented fields."""
    client, user = api_client
    conn = await _seed_connection(db, user_id=user.id)
    inst = await _seed_instrument(
        db, symbol="AAPL", exchange="NASDAQ", currency="USD", sector="Technology"
    )
    await _seed_position(
        db, conn_id=conn.id, instrument_id=inst.id, qty="5", price="100", currency="USD"
    )

    resp = await client.get("/api/portfolio/intelligence")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    for key in (
        "base_currency",
        "sector_allocation",
        "diversification",
        "per_market_alpha",
        "blended_benchmark_return",
        "portfolio_return",
        "portfolio_alpha",
        "portfolio_return_stale",
        "unclassified_markets",
        "rebalancing_suggestions",
    ):
        assert key in body
    assert "hhi" in body["diversification"]
    assert "geography" in body["diversification"]
    # All NASDAQ position → no unclassified markets; placeholder return → stale.
    assert body["unclassified_markets"] == []
    assert body["portfolio_return_stale"] is True


async def test_get_intelligence_requires_auth() -> None:
    """Unauthenticated request → 401."""
    # Build a client without the get_current_user override.
    transport = ASGITransport(app=app)
    # Ensure no residual overrides from a prior fixture.
    app.dependency_overrides.pop(get_current_user, None)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/portfolio/intelligence")
    assert resp.status_code == 401
