"""Unit tests for the symbol mapping service.

Covers AC #3 (``normalize_symbol`` maps Zerodha ``RELIANCE`` on NSE to the
canonical ``(RELIANCE, NSE)`` instrument) and AC #4 (``data_symbol`` returns
``RELIANCE.NS`` for Yahoo Finance).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from backend.app.models.instruments import Instrument
from backend.app.models.symbol_mappings import SymbolMapping
from backend.app.services.symbol_mapping import (
    SymbolMappingService,
    SymbolNotMappedError,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    """Fresh in-memory SQLite with instruments + symbol_mappings tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Instrument.__table__.create(sync_conn))
        await conn.run_sync(lambda sync_conn: SymbolMapping.__table__.create(sync_conn))
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed_reliance(session: AsyncSession) -> Instrument:
    inst = Instrument(
        symbol="RELIANCE",
        exchange="NSE",
        name="Reliance Industries Limited",
        currency="INR",
        asset_class="equity",
    )
    session.add(inst)
    mapping = SymbolMapping(
        instrument_id=None,  # filled after flush
        broker="zerodha",
        broker_symbol="RELIANCE",
        broker_exchange="NSE",
    )
    await session.flush()
    mapping.instrument_id = inst.id
    session.add(mapping)
    await session.flush()
    return inst


async def _seed_aapl(session: AsyncSession) -> Instrument:
    inst = Instrument(
        symbol="AAPL",
        exchange="NASDAQ",
        name="Apple Inc.",
        currency="USD",
        asset_class="equity",
    )
    session.add(inst)
    await session.flush()
    mapping = SymbolMapping(
        instrument_id=inst.id,
        broker="alpaca",
        broker_symbol="AAPL",
        broker_exchange="NASDAQ",
    )
    session.add(mapping)
    await session.flush()
    return inst


async def test_normalize_symbol_zerodha_reliance_maps_to_nse(session: AsyncSession) -> None:
    """AC #3: RELIANCE from Zerodha → canonical (RELIANCE, NSE)."""
    seeded = await _seed_reliance(session)
    svc = SymbolMappingService(session)

    result = await svc.normalize_symbol(
        broker="zerodha", broker_symbol="RELIANCE", broker_exchange="NSE"
    )

    assert result.id == seeded.id
    assert result.symbol == "RELIANCE"
    assert result.exchange == "NSE"


async def test_data_symbol_yahoo_reliance_ns(session: AsyncSession) -> None:
    """AC #4: RELIANCE on NSE → RELIANCE.NS for Yahoo Finance."""
    inst = await _seed_reliance(session)
    svc = SymbolMappingService(session)

    assert await svc.data_symbol(inst, provider="yahoo") == "RELIANCE.NS"


async def test_data_symbol_yahoo_us_ticker_no_suffix(session: AsyncSession) -> None:
    inst = await _seed_aapl(session)
    svc = SymbolMappingService(session)

    assert await svc.data_symbol(inst, provider="yahoo") == "AAPL"


async def test_data_symbol_unknown_provider_raises(session: AsyncSession) -> None:
    inst = await _seed_aapl(session)
    svc = SymbolMappingService(session)

    with pytest.raises(ValueError):
        await svc.data_symbol(inst, provider="bloomberg")


async def test_normalize_symbol_inference_creates_mapping(session: AsyncSession) -> None:
    """No mapping row exists but an instrument with matching symbol/exchange does.

    The service should infer the match and persist a mapping for next time.
    """
    inst = Instrument(
        symbol="INFY",
        exchange="NSE",
        name="Infosys Limited",
        currency="INR",
        asset_class="equity",
    )
    session.add(inst)
    await session.flush()
    svc = SymbolMappingService(session)

    result = await svc.normalize_symbol(
        broker="zerodha", broker_symbol="INFY", broker_exchange="NSE"
    )
    assert result.id == inst.id

    # Second call must hit the cached mapping (not re-infer).
    mappings = await svc.list_for_instrument(inst.id)
    assert len(mappings) == 1
    assert mappings[0].broker == "zerodha"
    assert mappings[0].broker_symbol == "INFY"


async def test_normalize_symbol_unknown_raises(session: AsyncSession) -> None:
    svc = SymbolMappingService(session)

    with pytest.raises(SymbolNotMappedError):
        await svc.normalize_symbol(
            broker="alpaca", broker_symbol="DOESNOTEXIST", broker_exchange="NASDAQ"
        )


async def test_normalize_symbol_accepts_mic_exchange(session: AsyncSession) -> None:
    """Zerodha-style NSE exchange code and MIC code ``XNSE`` both resolve."""
    inst = Instrument(
        symbol="TCS",
        exchange="NSE",
        name="Tata Consultancy Services",
        currency="INR",
        asset_class="equity",
    )
    session.add(inst)
    await session.flush()
    svc = SymbolMappingService(session)

    # MIC code on the broker side still resolves via inference fallback.
    result = await svc.normalize_symbol(
        broker="zerodha", broker_symbol="TCS", broker_exchange="XNSE"
    )
    assert result.id == inst.id
