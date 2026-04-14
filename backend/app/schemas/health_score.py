"""Pydantic response schemas for the Portfolio Health Score API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthScoreComponentOut(BaseModel):
    name: str
    score: float | None = Field(None, ge=0, le=100)
    weight: float = Field(..., ge=0, le=1)
    detail: dict[str, float | int | str | None] = Field(default_factory=dict)


class HealthScoreResponse(BaseModel):
    """GET /api/portfolio/health-score response body."""

    overall_score: float = Field(..., ge=0, le=100)
    components: list[HealthScoreComponentOut]
    staleness: str = Field("fresh", description="fresh | stale | very_stale")
    stale_warning: str | None = Field(
        None,
        description=(
            "AC #14: if underlying data is > 24 h old, this warning is set so the UI "
            "can annotate the displayed score."
        ),
    )
    computed_at: str = Field(..., description="ISO-8601 UTC timestamp of the computation.")


__all__ = [
    "HealthScoreComponentOut",
    "HealthScoreResponse",
]
