"""Portfolio Health Score (0-100) — daily, four equal-weight components.

The Health Score sits beside the Risk Meter on the dashboard. Where the Risk
Meter answers "how risky is this book today?", the Health Score answers "how
well-constructed is this book?". They are intentionally independent: a high
health score and a high risk score are not contradictory (a concentrated bet
on a high-quality name can be simultaneously healthy and risky).

Four equal-weight components (25 % each):

1. **Diversification** — inverse of the HHI, rescaled. 20+ equal-weight
   holdings ≈ 100; single holding = 0.
2. **Fundamental strength** — average of per-holding fundamental composite
   scores (produced by :mod:`backend.app.analysis.fundamental`). Holdings
   without a score are skipped rather than imputed.
3. **Technical alignment** — average of per-holding technical composite
   scores rescaled from the engine's native -1..+1 onto 0..100.
4. **Risk-adjusted return vs benchmark** — simple Sharpe-like ratio of
   portfolio return over a benchmark, mapped onto 0..100. When no benchmark
   series is available the component returns ``None`` and the overall
   renormalises across the remaining three.

Daily update contract (AC #11): the engine itself is pure; the API layer is
responsible for caching the output with a daily TTL. We don't put caching
here so the engine stays importable from tests / CLI without a Redis
dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_WEIGHT = 0.25
_TRADING_DAYS_PER_YEAR = 252

# Diversification saturation: 20 equal-weight holdings give HHI = 0.05 →
# diversification score = (1 - 0.05) / 0.95 = ~100 via the linear map below.
_DIVERSIFICATION_FLOOR_HHI = 0.05
# Risk-adjusted score saturates at Sharpe = +2 (portfolio return 2× std-dev
# above benchmark) and floors at Sharpe = -1.
_SHARPE_FLOOR = -1.0
_SHARPE_CAP = 2.0


@dataclass(frozen=True)
class HealthScoreComponent:
    name: str
    score: float | None
    weight: float
    detail: dict[str, float | int | str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthScoreResult:
    overall_score: float
    components: list[HealthScoreComponent]


# ---- Component: diversification -------------------------------------------


def compute_diversification(weights: list[float]) -> HealthScoreComponent:
    """HHI-based diversification score (higher = more diversified).

    We compute HHI on the normalised weight vector, then linearly rescale
    ``(1 - HHI)`` onto 0-100 so a single-holding book scores 0 and a
    fully-diversified book approaches 100.
    """
    if not weights:
        return HealthScoreComponent(
            name="diversification",
            score=None,
            weight=_WEIGHT,
            detail={"hhi": None, "holdings": 0},
        )
    total = float(sum(abs(w) for w in weights))
    if total <= 0:
        return HealthScoreComponent(
            name="diversification",
            score=None,
            weight=_WEIGHT,
            detail={"hhi": None, "holdings": len(weights)},
        )
    normalized = [abs(w) / total for w in weights]
    hhi = float(sum(w * w for w in normalized))
    # HHI ∈ [1/N, 1]. Map to 0..100 via (1-HHI)/(1-floor), clamped.
    if hhi >= 1.0:
        score = 0.0
    else:
        raw = (1.0 - hhi) / (1.0 - _DIVERSIFICATION_FLOOR_HHI)
        score = round(max(0.0, min(1.0, raw)) * 100.0, 1)
    return HealthScoreComponent(
        name="diversification",
        score=score,
        weight=_WEIGHT,
        detail={"hhi": round(hhi, 4), "holdings": len(weights)},
    )


# ---- Component: fundamental strength --------------------------------------


def compute_fundamental(fundamental_scores: list[float | None]) -> HealthScoreComponent:
    """Average of per-holding fundamental composite scores (None = skipped)."""
    present = [s for s in fundamental_scores if s is not None]
    if not present:
        return HealthScoreComponent(
            name="fundamental",
            score=None,
            weight=_WEIGHT,
            detail={"scored_holdings": 0, "total_holdings": len(fundamental_scores)},
        )
    avg = float(np.mean(present))
    return HealthScoreComponent(
        name="fundamental",
        score=round(max(0.0, min(100.0, avg)), 1),
        weight=_WEIGHT,
        detail={
            "scored_holdings": len(present),
            "total_holdings": len(fundamental_scores),
        },
    )


# ---- Component: technical alignment ---------------------------------------


def compute_technical(technical_scores: list[float | None]) -> HealthScoreComponent:
    """Average of per-holding technical composite scores, mapped -1..+1 → 0..100."""
    present = [s for s in technical_scores if s is not None]
    if not present:
        return HealthScoreComponent(
            name="technical",
            score=None,
            weight=_WEIGHT,
            detail={"scored_holdings": 0, "total_holdings": len(technical_scores)},
        )
    avg_native = float(np.mean(present))  # expected in [-1, +1]
    # Clamp first in case the engine returns something slightly out of band.
    clamped = max(-1.0, min(1.0, avg_native))
    score = round((clamped + 1.0) / 2.0 * 100.0, 1)
    return HealthScoreComponent(
        name="technical",
        score=score,
        weight=_WEIGHT,
        detail={
            "scored_holdings": len(present),
            "total_holdings": len(technical_scores),
            "avg_native": round(avg_native, 4),
        },
    )


# ---- Component: risk-adjusted return vs benchmark -------------------------


def compute_risk_adjusted(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series | None,
) -> HealthScoreComponent:
    """Sharpe-like ratio of excess returns vs benchmark, mapped to 0-100.

    We do not subtract a risk-free rate — for a directional "is this
    portfolio beating its benchmark on a per-unit-of-risk basis?" signal
    the excess return over the benchmark is the more relevant numerator.
    """
    if benchmark_returns is None or benchmark_returns.empty or portfolio_returns.empty:
        return HealthScoreComponent(
            name="risk_adjusted",
            score=None,
            weight=_WEIGHT,
            detail={"sharpe": None, "observations": int(portfolio_returns.shape[0])},
        )
    aligned = pd.concat(
        [portfolio_returns.rename("port"), benchmark_returns.rename("bench")],
        axis=1,
    ).dropna()
    if aligned.shape[0] < 30:
        return HealthScoreComponent(
            name="risk_adjusted",
            score=None,
            weight=_WEIGHT,
            detail={"sharpe": None, "observations": int(aligned.shape[0])},
        )
    excess = aligned["port"] - aligned["bench"]
    std = float(excess.std(ddof=1))
    if std <= 0:
        return HealthScoreComponent(
            name="risk_adjusted",
            score=None,
            weight=_WEIGHT,
            detail={"sharpe": None, "observations": int(aligned.shape[0])},
        )
    sharpe = float(excess.mean() / std) * float(np.sqrt(_TRADING_DAYS_PER_YEAR))
    # Linear map on [floor, cap] → [0, 100]; clamp the tails.
    clipped = max(_SHARPE_FLOOR, min(_SHARPE_CAP, sharpe))
    score = round((clipped - _SHARPE_FLOOR) / (_SHARPE_CAP - _SHARPE_FLOOR) * 100.0, 1)
    return HealthScoreComponent(
        name="risk_adjusted",
        score=score,
        weight=_WEIGHT,
        detail={"sharpe": round(sharpe, 4), "observations": int(aligned.shape[0])},
    )


# ---- Orchestrator ---------------------------------------------------------


def compute_health_score(
    *,
    holding_weights: list[float],
    fundamental_scores: list[float | None],
    technical_scores: list[float | None],
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series | None,
) -> HealthScoreResult:
    """Blend the four components into the overall Health Score.

    Missing components renormalise the remaining weights so one unavailable
    signal doesn't artificially deflate the score.
    """
    components = [
        compute_diversification(holding_weights),
        compute_fundamental(fundamental_scores),
        compute_technical(technical_scores),
        compute_risk_adjusted(portfolio_returns, benchmark_returns),
    ]
    weighted = 0.0
    weight_sum = 0.0
    for c in components:
        if c.score is None:
            continue
        weighted += c.score * c.weight
        weight_sum += c.weight
    overall = 0.0 if weight_sum == 0 else weighted / weight_sum
    overall_rounded = round(max(0.0, min(100.0, overall)), 1)
    return HealthScoreResult(overall_score=overall_rounded, components=components)


__all__ = [
    "HealthScoreComponent",
    "HealthScoreResult",
    "compute_diversification",
    "compute_fundamental",
    "compute_health_score",
    "compute_risk_adjusted",
    "compute_technical",
]
