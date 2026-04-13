"""User broker OAuth / API connections."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from backend.app.models.base import Base, TimestampMixin
from backend.app.models.symbol_mappings import BrokerEnum  # reuse
from sqlalchemy import TIMESTAMP, Enum, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

BrokerConnStatusEnum = Enum(
    "active", "expired", "revoked", name="broker_conn_status_enum", native_enum=True
)


class BrokerConnection(Base, TimestampMixin):
    __tablename__ = "broker_connections"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    broker: Mapped[str] = mapped_column(BrokerEnum, nullable=False)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    access_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(BrokerConnStatusEnum, nullable=False, default="active")
