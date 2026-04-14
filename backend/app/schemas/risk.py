"""Pydantic response schemas for the risk API.

These mirror the dataclasses in :mod:`backend.app.analysis.risk` but are
Pydantic v2 models so FastAPI can serialise them directly. Keeping the
schemas separate from the analysis dataclasses lets the computation layer
stay free of Pydantic / FastAPI imports and makes the engine reusable from
non-HTTP callers (Celery tasks, CLI tools, tests).

All numeric fields are optional because the engine returns ``None`` whenever
it has too few observations to compute a given metric honestly. Callers
should check the accompanying status/flag fields rather than assume numbers
are present.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VaRResult(BaseModel):
    """Historical-simulation Value at Risk at 95 % and 99 % confidence.

    ``status`` disambiguates the three outcomes the engine can produce:

    * ``"ok"`` — both percentiles are populated.
    * ``"insufficient_data"`` — fewer than the minimum lookback returns;
      both percentiles are ``None``.
    * ``"empty"`` — no returns at all (e.g. brand-new instrument).
    """

    status: str = Field(..., description="ok | insufficient_data | empty")
    var_95: float | None = Field(
        None, description="95% historical-simulation VaR as a positive loss fraction."
    )
    var_99: float | None = Field(
        None, description="99% historical-simulation VaR as a positive loss fraction."
    )
    lookback_days: int = Field(..., description="Number of return observations actually used.")


class VolatilityResult(BaseModel):
    """Annualised volatility over 30- and 90-day windows."""

    vol_30d: float | None = Field(
        None, description="Annualised std dev of daily log returns (30d)."
    )
    vol_90d: float | None = Field(
        None, description="Annualised std dev of daily log returns (90d)."
    )
    estimated: bool = Field(
        False,
        description=(
            "True when computed from fewer than the full 30-day minimum, "
            "meaning the value is a best-effort estimate rather than a "
            "statistically meaningful figure."
        ),
    )


class DrawdownResult(BaseModel):
    """Current peak-to-trough drawdown."""

    drawdown: float | None = Field(
        None,
        description="Fraction below the running peak (0.15 = 15% below peak). None if no data.",
    )
    peak_price: float | None = None
    current_price: float | None = None


class RiskScoreResult(BaseModel):
    """Composite 0-100 risk score.

    Higher = riskier. When the instrument has insufficient history we fall
    back to a sector-average proxy and flip ``proxy_based`` to ``True`` so
    the UI can render an appropriate caveat.
    """

    score: int = Field(..., ge=0, le=100)
    proxy_based: bool = Field(
        False,
        description="True if a sector-average proxy was used instead of the instrument's own history.",
    )
    sector: str | None = Field(
        None, description="Sector used for the proxy fallback, if applicable."
    )


class DataQuality(BaseModel):
    """Data-quality signals surfaced to the caller."""

    observations: int = Field(..., description="Number of daily return observations available.")
    forward_filled_days: int = Field(
        0, description="Count of single-day gaps forward-filled before analysis."
    )
    excluded_from_correlation: bool = Field(
        False,
        description=(
            "True if the series had a gap longer than the forward-fill threshold; "
            "such series are dropped from correlation pools to avoid biasing the matrix."
        ),
    )
    notes: list[str] = Field(default_factory=list)


class RiskAnalysisResponse(BaseModel):
    """GET /api/analysis/{symbol}/risk response body."""

    symbol: str
    exchange: str
    bars_analyzed: int
    var: VaRResult
    volatility: VolatilityResult
    drawdown: DrawdownResult
    risk_score: RiskScoreResult
    data_quality: DataQuality


__all__ = [
    "DataQuality",
    "DrawdownResult",
    "RiskAnalysisResponse",
    "RiskScoreResult",
    "VaRResult",
    "VolatilityResult",
]
