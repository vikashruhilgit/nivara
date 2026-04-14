"""AI model invocation telemetry (runtime-populated, no seed data)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from backend.app.models.base import Base
from sqlalchemy import TIMESTAMP, Enum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

AiAnalysisStatusEnum = Enum(
    "success", "error", "timeout", name="ai_analysis_status_enum", native_enum=True
)


class AiAnalysisLog(Base):
    __tablename__ = "ai_analysis_log"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(AiAnalysisStatusEnum, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False, index=True
    )
