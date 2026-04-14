"""Portfolio aggregation / read service.

Reads positions from the DB, enriches each with native + base currency
valuation (via :class:`FxService`), and returns either a flat list or an
aggregated summary.

Staleness
---------
A position's ``as_of`` timestamp acts as the last-sync marker. If the most
recent position is older than :data:`STALE_THRESHOLD`, the response carries
``is_stale=True`` and a reduced ``confidence`` so UIs can warn users.

Pricing
-------
We store ``avg_cost`` (native), but not a live "current price" on the
``positions`` table. Market value is computed using ``avg_cost`` as a
conservative placeholder until the price pipeline ships (follow-up
milestone). This keeps P&L aggregates deterministic for now; the shape of
the response is forward-compatible with adding a ``last_price`` column.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.instruments import Instrument
from backend.app.models.positions import Position
from backend.app.schemas.portfolio import (
    PortfolioSummaryOut,
    PositionOut,
    PositionsList,
)
from backend.app.services.fx import FxRateNotFoundError, FxService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

STALE_THRESHOLD = timedelta(hours=2)
STALE_CONFIDENCE = Decimal("0.5")


class PortfolioSummaryService:
    """Aggregates DB positions into user-facing responses."""

    def __init__(self, *, session: AsyncSession, fx: FxService) -> None:
        self._session = session
        self._fx = fx

    async def list_positions(
        self,
        *,
        user_id: UUID,
        base_currency: str = "USD",
    ) -> PositionsList:
        positions, is_stale, as_of = await self._enriched_positions(
            user_id=user_id, base_currency=base_currency
        )
        return PositionsList(
            positions=positions,
            base_currency=base_currency,
            as_of=as_of,
            is_stale=is_stale,
        )

    async def summary(
        self,
        *,
        user_id: UUID,
        base_currency: str = "USD",
    ) -> PortfolioSummaryOut:
        positions, is_stale, as_of = await self._enriched_positions(
            user_id=user_id, base_currency=base_currency
        )
        total_value = sum((p.market_value_base for p in positions), Decimal("0"))
        total_cost = sum((p.avg_cost * p.quantity * p.fx_rate for p in positions), Decimal("0"))
        total_unrealized = sum((p.unrealized_pl_base for p in positions), Decimal("0"))
        confidence = STALE_CONFIDENCE if is_stale else Decimal("1.0")
        return PortfolioSummaryOut(
            base_currency=base_currency,
            total_value=total_value,
            total_cost_basis=total_cost,
            total_unrealized_pl=total_unrealized,
            daily_pl=Decimal("0"),  # requires price-history; seeded as 0 for MVP
            position_count=sum(1 for p in positions if p.quantity != 0),
            as_of=as_of,
            is_stale=is_stale,
            confidence=confidence,
        )

    # ------------------------------------------------------------------ internals

    async def _enriched_positions(
        self,
        *,
        user_id: UUID,
        base_currency: str,
    ) -> tuple[list[PositionOut], bool, datetime]:
        # Join positions -> broker_connections filter by user_id.
        stmt = (
            select(Position, Instrument)
            .join(
                BrokerConnection,
                BrokerConnection.id == Position.broker_connection_id,
            )
            .join(Instrument, Instrument.id == Position.instrument_id)
            .where(BrokerConnection.user_id == user_id)
        )
        rows = list((await self._session.execute(stmt)).all())

        now = datetime.now(UTC)
        latest_as_of = now
        newest: datetime | None = None
        enriched: list[PositionOut] = []

        for position, instrument in rows:
            native = position.currency
            # Market value in native currency (placeholder = qty * avg_cost).
            mv_native = position.quantity * position.avg_cost
            unrealized_native = Decimal("0")  # price feed not wired yet

            try:
                fx_rate = await self._fx.get_rate(base=native, quote=base_currency)
            except FxRateNotFoundError:
                # Fail closed on unknown pairs: emit the position in native and
                # mark fx_rate=0 so the UI can render "—" for base columns. We
                # do NOT silently default to 1.0 (would misreport aggregates).
                fx_rate = Decimal("0")

            mv_base = mv_native * fx_rate
            unrealized_base = unrealized_native * fx_rate

            enriched.append(
                PositionOut(
                    instrument_id=instrument.id,
                    symbol=instrument.symbol,
                    exchange=instrument.exchange,
                    quantity=position.quantity,
                    avg_cost=position.avg_cost,
                    currency=native,
                    market_value_native=mv_native,
                    unrealized_pl_native=unrealized_native,
                    base_currency=base_currency,
                    market_value_base=mv_base,
                    unrealized_pl_base=unrealized_base,
                    fx_rate=fx_rate,
                    as_of=position.as_of,
                )
            )

            if newest is None or position.as_of > newest:
                newest = position.as_of

        if newest is not None:
            latest_as_of = newest

        is_stale = False
        if newest is None:
            # No positions: not stale (nothing to be stale about).
            is_stale = False
        else:
            # Compare in UTC; tolerate naive timestamps from SQLite by treating
            # them as UTC.
            comparable = newest if newest.tzinfo else newest.replace(tzinfo=UTC)
            is_stale = (now - comparable) > STALE_THRESHOLD

        return enriched, is_stale, latest_as_of
