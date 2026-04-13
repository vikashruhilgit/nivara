"""Broker-specific symbol aliases mapped to canonical instruments."""
from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base

BrokerEnum = Enum("alpaca", "zerodha", name="broker_enum", native_enum=True)


class SymbolMapping(Base):
    __tablename__ = "symbol_mappings"
    __table_args__ = (
        UniqueConstraint(
            "broker", "broker_symbol", "broker_exchange", name="uq_symbol_mappings_broker_triplet"
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    broker: Mapped[str] = mapped_column(BrokerEnum, nullable=False)
    broker_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    broker_exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)
