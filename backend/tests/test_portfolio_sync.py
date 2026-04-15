"""Tests for :mod:`backend.app.services.portfolio_sync`.

Covers acceptance criteria:

* AC-1: positions from broker appear in DB with correct instrument_id.
* AC-2: re-running sync is idempotent (no duplicates by
  ``(broker_connection_id, instrument_id)``).
* AC-3: position removed from broker → local quantity set to 0.
* AC-4: orders upserted by ``broker_order_id``; status updates applied.
* AC-7: audit entry recorded for each sync.

AuditService is mocked (AuditLog uses Postgres JSONB/INET — not SQLite-compatible).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from backend.app.brokers.base import BrokerAdapter, BrokerFeatures
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.instruments import Instrument
from backend.app.models.orders import Order
from backend.app.models.positions import Position
from backend.app.models.symbol_mappings import SymbolMapping
from backend.app.schemas.broker import NormalizedBalance, NormalizedOrder, NormalizedPosition
from backend.app.services.portfolio_sync import PortfolioSyncService
from backend.app.services.symbol_mapping import SymbolMappingService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


# ------------------------------------------------------------------ fixtures


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    """In-memory SQLite with the tables needed for sync tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sc: Instrument.__table__.create(sc))
        await conn.run_sync(lambda sc: SymbolMapping.__table__.create(sc))
        # broker_connections uses TimestampMixin + LargeBinary; SQLite renders OK.
        # We create it with minimal reflection — just call __table__.create.
        await conn.run_sync(lambda sc: BrokerConnection.__table__.create(sc))
        await conn.run_sync(lambda sc: Position.__table__.create(sc))
        await conn.run_sync(lambda sc: Order.__table__.create(sc))
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed_instruments_and_connection(
    session: AsyncSession,
) -> tuple[Instrument, Instrument, BrokerConnection, UUID]:
    aapl = Instrument(
        symbol="AAPL", exchange="NASDAQ", name="Apple", currency="USD", asset_class="equity"
    )
    tsla = Instrument(
        symbol="TSLA", exchange="NASDAQ", name="Tesla", currency="USD", asset_class="equity"
    )
    session.add_all([aapl, tsla])
    await session.flush()
    for inst in (aapl, tsla):
        session.add(
            SymbolMapping(
                instrument_id=inst.id,
                broker="alpaca",
                broker_symbol=inst.symbol,
                broker_exchange="NASDAQ",
            )
        )
    user_id = uuid4()
    conn = BrokerConnection(
        user_id=user_id,
        broker="alpaca",
        account_id="test-acct",
        access_token_encrypted=b"x" * 48,
    )
    session.add(conn)
    await session.flush()
    return aapl, tsla, conn, user_id


class _StubAdapter(BrokerAdapter):
    """In-memory broker adapter for sync tests."""

    broker_name = "alpaca"

    def __init__(
        self,
        positions: list[NormalizedPosition],
        orders: list[NormalizedOrder] | None = None,
    ) -> None:
        self._positions = positions
        self._orders = orders or []

    @property
    def features(self) -> BrokerFeatures:
        return BrokerFeatures(
            supports_positions=True,
            supports_balances=True,
            supports_orders=True,
            supports_place_order=False,
            supports_oauth=True,
        )

    async def get_positions(self) -> list[NormalizedPosition]:
        return list(self._positions)

    async def get_balances(self) -> NormalizedBalance:
        return NormalizedBalance(
            cash=Decimal("0"), equity=Decimal("0"), currency="USD", account_id="test"
        )

    async def get_orders(self, *, open_only: bool = False) -> list[NormalizedOrder]:
        return list(self._orders)

    def normalize_symbol(self, broker_symbol: str) -> str:
        return broker_symbol.upper()

    async def place_order(self, **kwargs: object) -> NormalizedOrder:  # pragma: no cover
        raise NotImplementedError


def _make_sync_service(session: AsyncSession) -> tuple[PortfolioSyncService, AsyncMock]:
    audit = AsyncMock()
    audit.record = AsyncMock()
    svc = PortfolioSyncService(
        session=session,
        mapping_service=SymbolMappingService(session),
        audit_service=audit,
    )
    return svc, audit


# ------------------------------------------------------------------ AC-1 + AC-2


async def test_sync_upserts_positions_with_instrument_resolution(
    session: AsyncSession,
) -> None:
    """AC-1: positions appear in DB keyed by resolved instrument_id."""
    aapl, _tsla, conn, user_id = await _seed_instruments_and_connection(session)

    adapter = _StubAdapter(
        positions=[
            NormalizedPosition(
                broker_symbol="AAPL",
                quantity=Decimal("10"),
                avg_entry_price=Decimal("150.00"),
                current_price=Decimal("175.00"),
                market_value=Decimal("1750.00"),
                unrealized_pl=Decimal("250.00"),
                currency="USD",
                exchange="NASDAQ",
            )
        ]
    )
    svc, audit = _make_sync_service(session)

    result = await svc.sync_connection(connection=conn, adapter=adapter, user_id=user_id)

    assert result.positions_upserted == 1
    assert result.positions_closed == 0
    assert result.positions_skipped == 0
    # AC-7: audit recorded
    assert audit.record.await_count == 1

    rows = (
        (await session.execute(select(Position).where(Position.broker_connection_id == conn.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].instrument_id == aapl.id
    assert rows[0].quantity == Decimal("10")
    assert rows[0].avg_cost == Decimal("150.00")


async def test_sync_is_idempotent(session: AsyncSession) -> None:
    """AC-2: re-running produces no duplicate rows."""
    _aapl, _tsla, conn, user_id = await _seed_instruments_and_connection(session)

    positions = [
        NormalizedPosition(
            broker_symbol="AAPL",
            quantity=Decimal("10"),
            avg_entry_price=Decimal("150.00"),
            current_price=Decimal("175.00"),
            market_value=Decimal("1750.00"),
            unrealized_pl=Decimal("250.00"),
            currency="USD",
            exchange="NASDAQ",
        )
    ]
    svc, _audit = _make_sync_service(session)

    await svc.sync_connection(
        connection=conn, adapter=_StubAdapter(positions=positions), user_id=user_id
    )
    # Run again — same data. Should NOT create a second row.
    await svc.sync_connection(
        connection=conn, adapter=_StubAdapter(positions=positions), user_id=user_id
    )

    rows = (
        (await session.execute(select(Position).where(Position.broker_connection_id == conn.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1, "duplicate position row created on second sync"


# ------------------------------------------------------------------ AC-3


async def test_position_removed_from_broker_marked_closed(session: AsyncSession) -> None:
    """AC-3: position in DB but absent from broker response → quantity=0."""
    aapl, _tsla, conn, user_id = await _seed_instruments_and_connection(session)

    # Seed an existing position locally.
    session.add(
        Position(
            broker_connection_id=conn.id,
            instrument_id=aapl.id,
            quantity=Decimal("5"),
            avg_cost=Decimal("100"),
            currency="USD",
            as_of=datetime.now(UTC),
        )
    )
    await session.flush()

    # Broker now reports no positions.
    svc, _audit = _make_sync_service(session)
    result = await svc.sync_connection(
        connection=conn, adapter=_StubAdapter(positions=[]), user_id=user_id
    )

    assert result.positions_closed == 1
    row = (
        await session.execute(select(Position).where(Position.instrument_id == aapl.id))
    ).scalar_one()
    assert row.quantity == Decimal("0")


# ------------------------------------------------------------------ AC-4


async def test_orders_upserted_by_broker_order_id(session: AsyncSession) -> None:
    """AC-4: orders keyed by broker_order_id; status updates applied, never deleted."""
    _aapl, _tsla, conn, user_id = await _seed_instruments_and_connection(session)

    order_new = NormalizedOrder(
        broker_order_id="brkr-001",
        broker_symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=Decimal("5"),
        filled_quantity=Decimal("0"),
        status="new",
        submitted_at=datetime.now(UTC),
        currency="USD",
    )
    svc, _audit = _make_sync_service(session)

    # First sync — creates the order.
    await svc.sync_connection(
        connection=conn,
        adapter=_StubAdapter(positions=[], orders=[order_new]),
        user_id=user_id,
    )
    row = (
        await session.execute(select(Order).where(Order.broker_order_id == "brkr-001"))
    ).scalar_one()
    assert row.status == "submitted"  # normalized "new" -> DB "submitted"

    # Second sync — broker now reports it filled. Same broker_order_id.
    order_filled = NormalizedOrder(
        broker_order_id="brkr-001",
        broker_symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=Decimal("5"),
        filled_quantity=Decimal("5"),
        status="filled",
        submitted_at=datetime.now(UTC),
        currency="USD",
    )
    await svc.sync_connection(
        connection=conn,
        adapter=_StubAdapter(positions=[], orders=[order_filled]),
        user_id=user_id,
    )

    rows = (await session.execute(select(Order))).scalars().all()
    assert len(rows) == 1, "order duplicated instead of upserted"
    assert rows[0].status == "filled"


# ------------------------------------------------------------------ skip unresolved symbol


# ------------------------------------------------------------------ _build_adapter branching


def test_build_adapter_constructs_zerodha_adapter_for_zerodha_connection() -> None:
    """M4-22 heal: sync path must construct ZerodhaAdapter for broker='zerodha'.

    Previously the branch did not exist and sync would 501. We stub out the
    settings + encryption + rate-limiter singletons so the test doesn't need
    Redis or a real master key.
    """
    import base64
    import os
    from unittest.mock import MagicMock

    from backend.app.api import portfolio as portfolio_module
    from backend.app.brokers.zerodha import ZerodhaAdapter
    from backend.app.config import Settings
    from backend.app.services import encryption as enc_module

    user_id = uuid4()
    master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    settings = Settings(
        master_encryption_key=master_key,
        zerodha_api_key="zd-key",
        zerodha_api_secret="zd-secret",
    )
    orig_portfolio_settings = portfolio_module.get_settings
    orig_enc_settings = enc_module.get_settings
    portfolio_module.get_settings = lambda: settings  # type: ignore[assignment]
    enc_module.get_settings = lambda: settings  # type: ignore[assignment]
    enc_module.reset_master_key_cache()

    orig_limiter = portfolio_module.get_zerodha_rate_limiter
    portfolio_module.get_zerodha_rate_limiter = lambda: MagicMock()  # type: ignore[assignment]

    try:
        access_token = "kite-access-token-XYZ"
        encrypted = enc_module.encrypt_token(access_token, user_id=user_id)
        conn = BrokerConnection(
            user_id=user_id,
            broker="zerodha",
            account_id="ZD-acct",
            access_token_encrypted=encrypted,
            status="active",
        )

        adapter = portfolio_module._build_adapter(conn, user_id.bytes)
        assert isinstance(adapter, ZerodhaAdapter)
        # Secrets wired through from Settings (not hardcoded).
        assert adapter._api_key == "zd-key"
        assert adapter._api_secret == "zd-secret"
        assert adapter._access_token == access_token
        assert adapter._rate_limiter is not None
    finally:
        portfolio_module.get_settings = orig_portfolio_settings  # type: ignore[assignment]
        enc_module.get_settings = orig_enc_settings  # type: ignore[assignment]
        portfolio_module.get_zerodha_rate_limiter = orig_limiter  # type: ignore[assignment]
        enc_module.reset_master_key_cache()


async def test_unresolved_symbol_skipped_with_warning(session: AsyncSession) -> None:
    """A broker symbol we can't map must skip the position, not crash."""
    _aapl, _tsla, conn, user_id = await _seed_instruments_and_connection(session)

    adapter = _StubAdapter(
        positions=[
            NormalizedPosition(
                broker_symbol="UNKNOWN_TICKER",
                quantity=Decimal("1"),
                avg_entry_price=Decimal("1"),
                current_price=Decimal("1"),
                market_value=Decimal("1"),
                unrealized_pl=Decimal("0"),
                currency="USD",
                exchange="NASDAQ",
            )
        ]
    )
    svc, _audit = _make_sync_service(session)
    result = await svc.sync_connection(connection=conn, adapter=adapter, user_id=user_id)

    assert result.positions_upserted == 0
    assert result.positions_skipped == 1
    assert any("unmapped_symbol" in w for w in result.warnings)
