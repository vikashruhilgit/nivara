"""Historical OHLCV price data — declaratively partitioned monthly by timestamp.

Partition boundaries are created by migration ``001_initial`` (and extended by
a scheduled job in production). The ORM model does not manage partitions — it
only declares the parent table with the ``RANGE (timestamp)`` partitioning
strategy. Autogenerate will NOT emit partition DDL; the initial migration does
so manually using ``op.execute``.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import TIMESTAMP, BigInteger, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = {"postgresql_partition_by": "RANGE (timestamp)"}

    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True, nullable=False
    )
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
