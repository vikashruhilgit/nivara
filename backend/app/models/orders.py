"""Broker order records (submitted via API, mirrors broker state)."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, TimestampMixin

OrderSideEnum = Enum("buy", "sell", name="order_side_enum", native_enum=True)
OrderTypeEnum = Enum("market", "limit", name="order_type_enum", native_enum=True)
OrderStatusEnum = Enum(
    "pending",
    "submitted",
    "filled",
    "partial",
    "cancelled",
    "rejected",
    name="order_status_enum",
    native_enum=True,
)


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    broker_connection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("broker_connections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    side: Mapped[str] = mapped_column(OrderSideEnum, nullable=False)
    order_type: Mapped[str] = mapped_column(OrderTypeEnum, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    status: Mapped[str] = mapped_column(OrderStatusEnum, nullable=False, default="pending")
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
