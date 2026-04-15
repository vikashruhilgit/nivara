"""Pydantic v2 schemas for the recommendation API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class EngineScores(BaseModel):
    """Normalised ``[-1, +1]`` per-engine contributions to the composite.

    ``None`` means the engine was unavailable for this recommendation and its
    weight was redistributed across the remaining engines (see
    :func:`backend.app.intelligence.synthesizer.synthesize`).
    """

    technical: float | None = None
    fundamental: float | None = None
    sentiment: float | None = None
    risk: float | None = None


class RecommendationRequest(BaseModel):
    instrument_id: UUID


class RecommendationResponse(BaseModel):
    status: Literal["ok", "stale"]
    action: Literal["strong_buy", "buy", "hold", "sell", "strong_sell"] | None = None
    confidence: float | None = Field(default=None, description="0-100")
    composite_score: float | None = Field(default=None, description="-1..+1 weighted blend")
    engine_scores: EngineScores
    rationale: str | None = None
    expires_at: datetime | None = None
    computed_at: datetime
    reason: str | None = None
    explainer_used: str | None = None
    ai_blended: bool = False


__all__ = [
    "EngineScores",
    "RecommendationRequest",
    "RecommendationResponse",
]
