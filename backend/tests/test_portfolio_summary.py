"""Tests for :mod:`backend.app.services.portfolio_summary` and :mod:`fx`.

Covers:
* AC-5: summary returns total value in user's base currency.
* AC-6: positions endpoint returns fields in native AND base currency.
* AC-8: positions older than the stale threshold flip ``is_stale=True`` with
  reduced confidence.
* FX conversion arithmetic (USD↔INR round-trip, inverse lookup fallback).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.fx_rates import FxRate
from backend.app.models.instruments import Instrument
from backend.app.models.positions import Position
from backend.app.services.fx import FxRateNotFoundError, FxService
from backend.app.services.portfolio_summary import (
    STALE_CONFIDENCE,
    STALE_THRESHOLD,
    PortfolioSummaryService,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sc: Instrument.__table__.create(sc))
        await conn.run_sync(lambda sc: BrokerConnection.__table__.create(sc))
        await conn.run_sync(lambda sc: Position.__table__.create(sc))
        await conn.run_sync(lambda sc: FxRate.__table__.create(sc))
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# ------------------------------------------------------------------ FX tests


async def test_fx_same_currency_returns_one(session: AsyncSession) -> None:
    fx = FxService(session)
    rate = await fx.get_rate(base="USD", quote="USD")
    assert rate == Decimal("1")


async def test_fx_direct_rate_lookup(session: AsyncSession) -> None:
    session.add(
        FxRate(
            base_currency="USD",
            quote_currency="INR",
            rate=Decimal("83.50"),
            as_of=datetime.now(UTC),
        )
    )
    await session.flush()
    fx = FxService(session)
    rate = await fx.get_rate(base="USD", quote="INR")
    assert rate == Decimal("83.50")


async def test_fx_inverse_fallback(session: AsyncSession) -> None:
    """If USD->INR missing but INR->USD exists, fx inverts it."""
    session.add(
        FxRate(
            base_currency="INR",
            quote_currency="USD",
            rate=Decimal("0.012"),
            as_of=datetime.now(UTC),
        )
    )
    await session.flush()
    fx = FxService(session)
    rate = await fx.get_rate(base="USD", quote="INR")
    # 1 / 0.012 ≈ 83.333...
    assert abs(rate - (Decimal("1") / Decimal("0.012"))) < Decimal("1e-8")


async def test_fx_missing_rate_raises(session: AsyncSession) -> None:
    fx = FxService(session)
    with pytest.raises(FxRateNotFoundError):
        await fx.get_rate(base="USD", quote="INR")


# ------------------------------------------------------------------ helpers


async def _seed_portfolio(
    session: AsyncSession, *, position_as_of: datetime
) -> tuple[str, Instrument]:
    user_id = uuid4()
    conn = BrokerConnection(
        user_id=user_id,
        broker="alpaca",
        account_id="a",
        access_token_encrypted=b"x" * 48,
    )
    inst = Instrument(
        symbol="AAPL",
        exchange="NASDAQ",
        name="Apple",
        currency="USD",
        asset_class="equity",
    )
    session.add_all([conn, inst])
    await session.flush()
    session.add(
        Position(
            broker_connection_id=conn.id,
            instrument_id=inst.id,
            quantity=Decimal("10"),
            avg_cost=Decimal("150"),
            currency="USD",
            as_of=position_as_of,
        )
    )
    session.add(
        FxRate(
            base_currency="USD",
            quote_currency="INR",
            rate=Decimal("80"),
            as_of=datetime.now(UTC),
        )
    )
    await session.flush()
    return str(user_id), inst


# ------------------------------------------------------------------ AC-5 + AC-6


async def test_summary_aggregates_in_base_currency(session: AsyncSession) -> None:
    """AC-5: summary returns total value converted to base currency."""
    user_id_str, _inst = await _seed_portfolio(session, position_as_of=datetime.now(UTC))
    from uuid import UUID as _UUID

    svc = PortfolioSummaryService(session=session, fx=FxService(session))
    summary = await svc.summary(user_id=_UUID(user_id_str), base_currency="INR")

    # 10 * 150 = 1500 USD; * 80 = 120_000 INR.
    assert summary.base_currency == "INR"
    assert summary.total_value == Decimal("120000")
    assert summary.position_count == 1
    assert summary.is_stale is False
    assert summary.confidence == Decimal("1.0")


async def test_positions_list_has_dual_currency_fields(session: AsyncSession) -> None:
    """AC-6: positions endpoint emits native AND base currency fields."""
    user_id_str, inst = await _seed_portfolio(session, position_as_of=datetime.now(UTC))
    from uuid import UUID as _UUID

    svc = PortfolioSummaryService(session=session, fx=FxService(session))
    result = await svc.list_positions(user_id=_UUID(user_id_str), base_currency="INR")

    assert len(result.positions) == 1
    p = result.positions[0]
    assert p.instrument_id == inst.id
    assert p.currency == "USD"
    assert p.market_value_native == Decimal("1500")
    assert p.base_currency == "INR"
    assert p.market_value_base == Decimal("120000")
    assert p.fx_rate == Decimal("80")


# ------------------------------------------------------------------ AC-8


async def test_stale_positions_flip_confidence(session: AsyncSession) -> None:
    """AC-8: position older than threshold → is_stale=True + reduced confidence."""
    stale_ts = datetime.now(UTC) - (STALE_THRESHOLD + timedelta(minutes=5))
    user_id_str, _inst = await _seed_portfolio(session, position_as_of=stale_ts)
    from uuid import UUID as _UUID

    svc = PortfolioSummaryService(session=session, fx=FxService(session))
    summary = await svc.summary(user_id=_UUID(user_id_str), base_currency="INR")

    assert summary.is_stale is True
    assert summary.confidence == STALE_CONFIDENCE
