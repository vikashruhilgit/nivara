"""Exchange calendar overrides (holidays, half-days, emergency closures)."""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from backend.app.models.base import Base
from sqlalchemy import Boolean, Date, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class CalendarOverride(Base):
    __tablename__ = "calendar_overrides"
    __table_args__ = (
        UniqueConstraint("exchange", "date", name="uq_calendar_overrides_exchange_date"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
