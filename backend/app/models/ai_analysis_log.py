"""AI model invocation telemetry (runtime-populated, no seed data).

Extended by migration ``003_recommendation_actions_and_ai_analysis`` to add
the columns required by MODE 4 shadow-mode logging:

* ``shadow_mode`` — whether this result was suppressed from the composite.
* ``instrument_id`` — target of the analysis (nullable for non-instrument
  prompts, e.g. system health probes).
* ``result_json`` — full validated provider output.
* ``ai_score`` — collapsed scalar ``[-1, +1]`` (see
  :func:`backend.app.schemas.ai_analysis.ai_score_from_output`).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from backend.app.models.base import Base
from sqlalchemy import TIMESTAMP, Boolean, Enum, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
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
    shadow_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    instrument_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("instruments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ai_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False, index=True
    )
