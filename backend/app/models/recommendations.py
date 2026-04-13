"""AI-generated investment recommendations surfaced to users."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import TIMESTAMP, Enum, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, TimestampMixin

RecommendationTypeEnum = Enum(
    "buy", "sell", "hold", name="recommendation_type_enum", native_enum=True
)
RecommendationStatusEnum = Enum(
    "pending",
    "accepted",
    "rejected",
    "expired",
    "executed",
    name="recommendation_status_enum",
    native_enum=True,
)


class Recommendation(Base, TimestampMixin):
    __tablename__ = "recommendations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    instrument_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    recommendation_type: Mapped[str] = mapped_column(RecommendationTypeEnum, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        RecommendationStatusEnum, nullable=False, default="pending"
    )
