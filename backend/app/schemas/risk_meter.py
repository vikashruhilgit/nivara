"""Pydantic response schemas for the Risk Meter API.

Mirrors the dataclasses in :mod:`backend.app.analysis.risk_meter`. The
engine stays Pydantic-free so it's reusable from Celery tasks; the API
layer projects onto these models for serialisation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RiskMeterComponentOut(BaseModel):
    """A single sub-score with its weight and any supporting detail fields."""

    name: str
    score: float | None = Field(None, ge=0, le=100)
    weight: float = Field(..., ge=0, le=1)
    detail: dict[str, float | int | str | None] = Field(default_factory=dict)


class RiskMeterResponse(BaseModel):
    """GET /api/portfolio/risk-meter response body.

    ``staleness`` mirrors the portfolio-summary flag set: ``fresh`` when the
    underlying price / analysis data is < 4 h old, ``stale`` between 4 and
    24 h, and ``very_stale`` past 24 h (AC #12-13).
    """

    overall_score: float = Field(..., ge=0, le=100)
    color: str = Field(..., description="green | yellow | red")
    staleness: str = Field("fresh", description="fresh | stale | very_stale")
    stale_reason: str | None = Field(
        None,
        description=("Human-readable reason for the staleness flag (e.g. 'price data 6 h old')."),
    )


class RiskMeterDrilldownResponse(BaseModel):
    """GET /api/portfolio/risk-meter/drilldown response body."""

    overall_score: float = Field(..., ge=0, le=100)
    color: str
    staleness: str = "fresh"
    stale_reason: str | None = None
    components: list[RiskMeterComponentOut]


__all__ = [
    "RiskMeterComponentOut",
    "RiskMeterDrilldownResponse",
    "RiskMeterResponse",
]
