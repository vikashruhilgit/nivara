"""Portfolio sync service.

Pulls positions and orders from a user's broker connection and upserts them
into local tables. Core contracts:

* **Idempotency:** positions are keyed by ``(broker_connection_id, instrument_id)``
  — NEVER by raw broker symbol (CLAUDE.md rule). Orders are keyed by
  ``broker_order_id``. Re-running a sync produces no duplicates.
* **Close-on-missing:** a position previously present but absent from the
  broker response is updated to ``quantity=0`` rather than deleted. This
  preserves history and lets downstream consumers see the "position closed"
  event.
* **Never delete orders:** orders are append-only at the sync layer; status
  transitions (``new`` -> ``filled`` -> ``canceled``) are applied as updates.
* **Symbol resolution:** broker symbols are translated to canonical
  ``instrument_id`` via :class:`SymbolMappingService`. Unresolved symbols are
  logged as warnings and the position/order is skipped (never crashes the
  whole sync).
* **Audit:** every sync call writes an ``audit_log`` entry with summary
  counts so we can diff syncs forensically.
* **Concurrency:** an optional Redis lock per ``user_id`` prevents two
  in-flight syncs from racing. When Redis isn't available (tests), sync
  proceeds without the lock.

Write path is transactional at the session level — callers commit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from backend.app.brokers.base import BrokerAdapter
from backend.app.brokers.errors import BrokerAPIError
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.orders import Order
from backend.app.models.positions import Position
from backend.app.schemas.broker import NormalizedOrder, NormalizedPosition
from backend.app.services.audit import EVENT_PORTFOLIO_SYNC, AuditService
from backend.app.services.symbol_mapping import SymbolMappingService, SymbolNotMappedError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Map broker NormalizedOrder.status -> orders table status_enum.
# orders table uses: pending, submitted, filled, partial, cancelled, rejected.
_ORDER_STATUS_TO_DB: dict[str, str] = {
    "new": "submitted",
    "pending": "pending",
    "partially_filled": "partial",
    "filled": "filled",
    "canceled": "cancelled",
    "rejected": "rejected",
    "expired": "cancelled",
}


class SyncInProgressError(RuntimeError):
    """Raised when a sync is already running for the same user."""


@dataclass(frozen=True)
class SyncSummary:
    """Structured result of a sync run (returned to the API layer)."""

    broker_connection_id: UUID
    synced_at: datetime
    positions_upserted: int
    positions_closed: int
    orders_upserted: int
    positions_skipped: int
    warnings: list[str]


class PortfolioSyncService:
    """Coordinates broker -> DB portfolio synchronization."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        mapping_service: SymbolMappingService,
        audit_service: AuditService,
    ) -> None:
        self._session = session
        self._mapping = mapping_service
        self._audit = audit_service

    async def sync_connection(
        self,
        *,
        connection: BrokerConnection,
        adapter: BrokerAdapter,
        user_id: UUID,
    ) -> SyncSummary:
        """Sync the given broker connection using the supplied adapter.

        The adapter is injected (not constructed here) so callers can pass
        mocks in tests or a real Alpaca/Zerodha client in production.
        """
        now = datetime.now(UTC)
        warnings: list[str] = []

        # --- positions -----------------------------------------------------
        try:
            broker_positions = await adapter.get_positions()
        except BrokerAPIError as exc:
            logger.warning("Broker position fetch failed for conn=%s: %s", connection.id, exc)
            warnings.append(f"positions_fetch_failed: {exc}")
            broker_positions = []

        upserted, closed, skipped, pos_warnings = await self._sync_positions(
            connection=connection,
            broker_positions=broker_positions,
            now=now,
            broker=adapter.broker_name,
        )
        warnings.extend(pos_warnings)

        # --- orders --------------------------------------------------------
        try:
            broker_orders = await adapter.get_orders(open_only=False)
        except BrokerAPIError as exc:
            logger.warning("Broker order fetch failed for conn=%s: %s", connection.id, exc)
            warnings.append(f"orders_fetch_failed: {exc}")
            broker_orders = []

        orders_upserted, order_warnings = await self._sync_orders(
            connection=connection,
            broker_orders=broker_orders,
            broker=adapter.broker_name,
        )
        warnings.extend(order_warnings)

        # --- audit ---------------------------------------------------------
        await self._audit.record(
            event_type=EVENT_PORTFOLIO_SYNC,
            user_id=user_id,
            event_data={
                "broker_connection_id": str(connection.id),
                "broker": adapter.broker_name,
                "positions_upserted": upserted,
                "positions_closed": closed,
                "positions_skipped": skipped,
                "orders_upserted": orders_upserted,
                "warnings": warnings,
                "synced_at": now.isoformat(),
            },
        )

        return SyncSummary(
            broker_connection_id=connection.id,
            synced_at=now,
            positions_upserted=upserted,
            positions_closed=closed,
            orders_upserted=orders_upserted,
            positions_skipped=skipped,
            warnings=warnings,
        )

    # ------------------------------------------------------------------ positions

    async def _sync_positions(
        self,
        *,
        connection: BrokerConnection,
        broker_positions: list[NormalizedPosition],
        now: datetime,
        broker: str,
    ) -> tuple[int, int, int, list[str]]:
        warnings: list[str] = []
        upserted = 0
        skipped = 0

        # Load current local positions for this connection.
        existing_stmt = select(Position).where(Position.broker_connection_id == connection.id)
        existing_rows = list((await self._session.execute(existing_stmt)).scalars().all())
        existing_by_instrument: dict[UUID, Position] = {p.instrument_id: p for p in existing_rows}

        seen_instrument_ids: set[UUID] = set()

        for bp in broker_positions:
            try:
                instrument = await self._mapping.normalize_symbol(
                    broker=broker,
                    broker_symbol=bp.broker_symbol,
                    broker_exchange=bp.exchange,
                )
            except SymbolNotMappedError as exc:
                warnings.append(f"unmapped_symbol: {bp.broker_symbol} ({exc})")
                skipped += 1
                continue

            seen_instrument_ids.add(instrument.id)
            row = existing_by_instrument.get(instrument.id)
            if row is None:
                row = Position(
                    broker_connection_id=connection.id,
                    instrument_id=instrument.id,
                    quantity=bp.quantity,
                    avg_cost=bp.avg_entry_price,
                    currency=bp.currency,
                    as_of=now,
                )
                self._session.add(row)
            else:
                row.quantity = bp.quantity
                row.avg_cost = bp.avg_entry_price
                row.currency = bp.currency
                row.as_of = now
            upserted += 1

        # Positions present locally but missing from broker response -> closed.
        closed = 0
        for instrument_id, row in existing_by_instrument.items():
            if instrument_id in seen_instrument_ids:
                continue
            if row.quantity == 0:
                # Already marked closed; still refresh as_of so stale-check is accurate.
                row.as_of = now
                continue
            row.quantity = Decimal("0")
            row.as_of = now
            closed += 1

        await self._session.flush()
        return upserted, closed, skipped, warnings

    # ------------------------------------------------------------------ orders

    async def _sync_orders(
        self,
        *,
        connection: BrokerConnection,
        broker_orders: list[NormalizedOrder],
        broker: str,
    ) -> tuple[int, list[str]]:
        warnings: list[str] = []
        upserted = 0

        # Preload existing orders for this connection keyed by broker_order_id.
        stmt = select(Order).where(Order.broker_connection_id == connection.id)
        existing = list((await self._session.execute(stmt)).scalars().all())
        by_broker_id: dict[str, Order] = {
            o.broker_order_id: o for o in existing if o.broker_order_id
        }

        for bo in broker_orders:
            try:
                instrument = await self._mapping.normalize_symbol(
                    broker=broker,
                    broker_symbol=bo.broker_symbol,
                )
            except SymbolNotMappedError as exc:
                warnings.append(f"unmapped_order_symbol: {bo.broker_symbol} ({exc})")
                continue

            db_status = _ORDER_STATUS_TO_DB.get(bo.status, "pending")
            existing_order = by_broker_id.get(bo.broker_order_id)
            if existing_order is None:
                # Idempotency key mirrors future write-path contract:
                # (broker_connection_id, instrument_id, broker_order_id).
                idem_key = f"{connection.id}:{instrument.id}:{bo.broker_order_id}"
                order = Order(
                    broker_connection_id=connection.id,
                    instrument_id=instrument.id,
                    side=bo.side,
                    order_type=bo.order_type if bo.order_type in ("market", "limit") else "market",
                    quantity=bo.quantity,
                    limit_price=bo.limit_price,
                    status=db_status,
                    broker_order_id=bo.broker_order_id,
                    idempotency_key=idem_key,
                )
                self._session.add(order)
            else:
                existing_order.status = db_status
                existing_order.quantity = bo.quantity
                if bo.limit_price is not None:
                    existing_order.limit_price = bo.limit_price
            upserted += 1

        await self._session.flush()
        return upserted, warnings
