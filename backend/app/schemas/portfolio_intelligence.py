"""Pydantic response schemas for Portfolio Intelligence (Mode D).

Shape summary::

    {
      "base_currency": "USD",
      "sector_allocation": {
          "US": [{"sector": "Technology", "pct": 0.6}, ...],
          "IN": [...]
      },
      "diversification": {"hhi": 0.42, "geography": {"US": 0.7, "IN": 0.3}},
      "per_market_alpha": [
          {"market": "US", "benchmark_symbol": "^GSPC",
           "benchmark_currency": "USD", "portfolio_return": 0.05,
           "benchmark_return": 0.03, "alpha": 0.02, "stale_benchmark": false},
          ...
      ],
      "blended_benchmark_return": 0.031,
      "portfolio_return": 0.045,
      "portfolio_alpha": 0.014,
      "portfolio_return_stale": false,
      "unclassified_markets": [],
      "rebalancing_suggestions": [
          {"type": "sector_concentration", "sector": "Technology",
           "current_pct": 0.61,
           "suggestion": "Consider reducing exposure to Technology.",
           "disclaimer": "For informational purposes only. Not investment advice."}
      ]
    }

All percentages are fractions in ``[0, 1]``; the mobile client formats them
for display.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SectorAllocationEntry(BaseModel):
    """One sector's share of market value within a single market."""

    model_config = ConfigDict(from_attributes=True)

    sector: str
    pct: float = Field(..., ge=0, le=1)


class DiversificationOut(BaseModel):
    """Concentration (HHI) + geography weights."""

    model_config = ConfigDict(from_attributes=True)

    hhi: float = Field(..., ge=0, le=1, description="Herfindahl-Hirschman index over sectors.")
    geography: dict[str, float] = Field(
        default_factory=dict,
        description="Market -> fraction of total base-currency value. Sums to ~1.",
    )


class PerMarketAlpha(BaseModel):
    """Per-market portfolio vs benchmark comparison, in the market's native ccy."""

    model_config = ConfigDict(from_attributes=True)

    market: str = Field(..., description="'IN' or 'US'")
    benchmark_symbol: str
    benchmark_currency: str
    portfolio_return: float
    benchmark_return: float
    alpha: float = Field(..., description="portfolio_return - benchmark_return (native ccy).")
    stale_benchmark: bool = False
    portfolio_return_stale: bool = Field(
        default=True,
        description=(
            "True when portfolio_return is a placeholder (0.0) because the"
            " per-position price pipeline is not yet wired. Callers MUST"
            " suppress alpha rendering when this flag is True."
        ),
    )


class RebalancingSuggestion(BaseModel):
    """Display-only rebalancing nudge. Must always carry the disclaimer."""

    model_config = ConfigDict(from_attributes=True)

    type: str
    sector: str | None = None
    current_pct: float | None = None
    suggestion: str
    disclaimer: str


class PortfolioIntelligenceResponse(BaseModel):
    """Top-level response for ``GET /api/portfolio/intelligence``."""

    model_config = ConfigDict(from_attributes=True)

    base_currency: str
    sector_allocation: dict[str, list[SectorAllocationEntry]] = Field(default_factory=dict)
    diversification: DiversificationOut
    per_market_alpha: list[PerMarketAlpha] = Field(default_factory=list)
    blended_benchmark_return: float = 0.0
    portfolio_return: float = 0.0
    portfolio_alpha: float = 0.0
    portfolio_return_stale: bool = Field(
        default=True,
        description=(
            "True when portfolio_return (and therefore portfolio_alpha) is a"
            " placeholder (0.0) because the per-position price pipeline is not"
            " yet wired, OR when the portfolio is empty. Callers MUST suppress"
            " alpha rendering when this flag is True."
        ),
    )
    unclassified_markets: list[str] = Field(
        default_factory=list,
        description=(
            "Exchange codes of positions that did not map to a recognised"
            " market (IN/US) and were bucketed as OTHER. Empty when all"
            " positions mapped cleanly."
        ),
    )
    rebalancing_suggestions: list[RebalancingSuggestion] = Field(default_factory=list)


__all__ = [
    "DiversificationOut",
    "PerMarketAlpha",
    "PortfolioIntelligenceResponse",
    "RebalancingSuggestion",
    "SectorAllocationEntry",
]
