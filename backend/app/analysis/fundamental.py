"""Fundamental scoring engine.

Produces a 0-100 score per fundamental metric used by the recommendation
composite (Month 3). The weightings below come from TechSpec v1.3 §Scoring:

* Revenue Growth: 25%
* Earnings Trend: 25%
* Debt Health: 20%
* P/E Valuation: 15%
* Cash Flow: 15%

Absolute thresholds, not sector peers
-------------------------------------
The brief originally asked for sector-peer percentile scoring, but the MVP
:class:`backend.app.models.instruments.Instrument` has no ``sector`` column
(verified on 2026-04-14). Adding sector data is a separate job (instruments
enrichment). Until then we use **absolute thresholds** calibrated off S&P 500
medians — this is strictly weaker than peer percentiles but keeps the
recommendation engine unblocked. The thresholds are centralised in
:data:`_THRESHOLDS` and can be tuned without changing the scoring API.

Nullability
-----------
Every input metric may legitimately be ``None`` — e.g. unprofitable issuers
have no meaningful P/E, newly-public companies have no prior-year revenue.
When a component cannot be scored we return ``None`` for that component
and exclude its weight from the composite (re-normalising the remainder).
This preserves the 0-100 scale even under partial data. If no components
are scorable we return a composite of ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.data.edgar import EdgarFundamentals

# ---- Thresholds ------------------------------------------------------------

# (lower_bound, upper_bound, ascending)
# A value at lower_bound scores 0; at upper_bound scores 100 (or inverted if
# ascending=False). Values outside the range clamp.
_THRESHOLDS: dict[str, tuple[float, float, bool]] = {
    # Revenue YoY growth: -10% → 30%
    "revenue_growth": (-0.10, 0.30, True),
    # Earnings YoY growth: -20% → 30%
    "earnings_trend": (-0.20, 0.30, True),
    # Debt/Equity: inverted — 0.0 scores 100, 2.0 scores 0
    "debt_health": (0.0, 2.0, False),
    # P/E: inverted — P/E of 10 scores 100, P/E of 40 scores 0
    "pe_valuation": (10.0, 40.0, False),
    # Free cash flow / revenue: 0% → 20%
    "cash_flow": (0.0, 0.20, True),
}

_WEIGHTS: dict[str, float] = {
    "revenue_growth": 0.25,
    "earnings_trend": 0.25,
    "debt_health": 0.20,
    "pe_valuation": 0.15,
    "cash_flow": 0.15,
}


@dataclass(frozen=True)
class FundamentalScore:
    """Per-metric scores (0-100) plus weighted composite.

    Any component may be ``None`` when insufficient data is available. The
    composite re-normalises the remaining weights so partial data still yields
    a comparable 0-100 score.
    """

    revenue_growth: int | None
    earnings_trend: int | None
    debt_health: int | None
    pe_valuation: int | None
    cash_flow: int | None
    composite: int | None


def _score_from_range(value: float, lower: float, upper: float, ascending: bool) -> int:
    """Map ``value`` onto 0-100 against the ``[lower, upper]`` window.

    ``ascending=True`` means higher value → higher score; ``False`` inverts.
    Values outside the window clamp to 0 or 100.
    """
    if upper == lower:
        return 50
    pct = (value - lower) / (upper - lower)
    pct = max(0.0, min(1.0, pct))
    score = pct * 100.0 if ascending else (1.0 - pct) * 100.0
    return int(round(score))


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> float | None:
    """Safely compute ``numerator / denominator`` as float.

    Returns ``None`` when either input is missing or the denominator is zero.
    """
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float(numerator) / float(denominator)


def _yoy_growth(latest: Decimal | None, prior: Decimal | None) -> float | None:
    """Year-over-year growth rate.

    Using ``abs(prior)`` in the denominator handles the case where prior
    earnings are negative: a swing from -100 to +50 reports growth of
    ``(50 - (-100)) / 100 = +150%`` rather than a misleading -150%.
    """
    if latest is None or prior is None or prior == 0:
        return None
    return float(latest - prior) / float(abs(prior))


def score_fundamentals(
    fundamentals: EdgarFundamentals,
    *,
    price: Decimal | None = None,
) -> FundamentalScore:
    """Compute per-metric and composite fundamental scores.

    ``price`` is optional — if supplied with ``eps``, we derive the P/E
    component (EDGAR does not publish prices). Without it, the P/E component
    is ``None`` and its weight is dropped from the composite.
    """
    components: dict[str, int | None] = {}

    # Revenue growth (YoY).
    rev_growth = _yoy_growth(fundamentals.revenue_ttm, fundamentals.revenue_prior_ttm)
    components["revenue_growth"] = (
        None
        if rev_growth is None
        else _score_from_range(rev_growth, *_THRESHOLDS["revenue_growth"])
    )

    # Earnings trend (YoY).
    earn_growth = _yoy_growth(fundamentals.earnings_ttm, fundamentals.earnings_prior_ttm)
    components["earnings_trend"] = (
        None
        if earn_growth is None
        else _score_from_range(earn_growth, *_THRESHOLDS["earnings_trend"])
    )

    # Debt health (debt/equity, inverted).
    if fundamentals.debt_to_equity is None:
        components["debt_health"] = None
    else:
        components["debt_health"] = _score_from_range(
            float(fundamentals.debt_to_equity), *_THRESHOLDS["debt_health"]
        )

    # P/E valuation (inverted).
    pe: float | None = None
    if fundamentals.pe_ratio is not None:
        pe = float(fundamentals.pe_ratio)
    elif price is not None and fundamentals.eps is not None and fundamentals.eps != 0:
        pe = float(price) / float(fundamentals.eps)
    if pe is None or pe <= 0:
        # Negative or zero P/E is undefined (loss-making firms).
        components["pe_valuation"] = None
    else:
        components["pe_valuation"] = _score_from_range(pe, *_THRESHOLDS["pe_valuation"])

    # Cash flow quality: free cash flow / revenue.
    fcf_margin = _ratio(fundamentals.free_cash_flow, fundamentals.revenue_ttm)
    components["cash_flow"] = (
        None if fcf_margin is None else _score_from_range(fcf_margin, *_THRESHOLDS["cash_flow"])
    )

    # Weighted composite with re-normalisation.
    scored = {k: v for k, v in components.items() if v is not None}
    if not scored:
        composite: int | None = None
    else:
        total_weight = sum(_WEIGHTS[k] for k in scored)
        weighted = sum(scored[k] * _WEIGHTS[k] for k in scored)
        composite = int(round(weighted / total_weight))

    return FundamentalScore(
        revenue_growth=components["revenue_growth"],
        earnings_trend=components["earnings_trend"],
        debt_health=components["debt_health"],
        pe_valuation=components["pe_valuation"],
        cash_flow=components["cash_flow"],
        composite=composite,
    )


__all__ = ["FundamentalScore", "score_fundamentals"]
