"""Deterministic portfolio-level Risk Meter (0-100).

The Risk Meter is the dashboard's primary visual element: a single score with
a color classification plus a four-way drill-down. It intentionally does *not*
reuse the single-instrument risk engine in :mod:`backend.app.analysis.risk` —
at MVP the two live side-by-side so we can tune portfolio-level weights
without churning the per-instrument model (risk models are consumed elsewhere
by the recommendation engine). A later milestone may unify them.

Score composition
-----------------
Four weighted components, each mapped onto 0-100:

* **Concentration (30 %)** — Herfindahl-Hirschman Index (HHI) of holding
  weights, rescaled. Single-holding portfolio = 100; 20 equal-weight holdings
  ≈ 5.
* **Volatility / VaR (30 %)** — portfolio-level historical-simulation VaR at
  95 %, mapped to 0-100 with a saturating ceiling at 5 % daily VaR. Computed
  from a weighted combination of per-holding close series when available; if
  no price series are provided the component returns ``None`` and the overall
  score renormalises across the remaining components.
* **Drawdown (20 %)** — current peak-to-trough drawdown of the portfolio's
  weighted close series, mapped linearly. 0 % drawdown = 0; ≥ 40 % drawdown
  = 100.
* **Events (20 %)** — proximity-weighted count of upcoming earnings /
  ex-dividend dates within a 5-trading-day window. No calendar data at MVP →
  component is 0 (handled as "no events" rather than "unknown" so the score
  is not artificially inflated when earnings data is simply unavailable).

Classification bands (AC #3-5)
------------------------------
* 0-30 → ``green`` (calm)
* 31-60 → ``yellow`` (moderate)
* 61-100 → ``red`` (elevated)

Determinism
-----------
Outputs are rounded to 1 decimal place for display (AC mitigation: floating
point differences across platforms). Weights are explicit constants so the
"why" of a given score is visible in the drill-down.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

# ---- Weights (sum to 1.0) --------------------------------------------------

_WEIGHT_CONCENTRATION = 0.30
_WEIGHT_VOL_VAR = 0.30
_WEIGHT_DRAWDOWN = 0.20
_WEIGHT_EVENTS = 0.20

# ---- Thresholds ------------------------------------------------------------

_VAR_SATURATION = 0.05  # 5 % daily VaR → component score 100.
_DRAWDOWN_SATURATION = 0.40  # 40 % drawdown → component score 100.
_EVENTS_WINDOW_DAYS = 5
_MIN_RETURNS_FOR_VAR = 30

_GREEN_MAX = 30
_YELLOW_MAX = 60

_TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class RiskMeterComponent:
    name: str
    score: float | None  # None when the component cannot be computed
    weight: float
    detail: dict[str, float | int | str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskMeterResult:
    """Full Risk Meter output.

    ``overall_score`` is rounded to one decimal place. ``color`` follows the
    bands in the module docstring. ``components`` preserves the four
    sub-scores (with ``weight`` and ``detail``) so callers can render the
    drill-down without a second computation pass.
    """

    overall_score: float
    color: str  # green | yellow | red
    components: list[RiskMeterComponent]


# ---- Component: concentration ---------------------------------------------


def compute_concentration(weights: list[float]) -> RiskMeterComponent:
    """HHI-based concentration score.

    HHI = sum(w_i^2) for normalised weights. An equal-weight portfolio of N
    holdings has HHI = 1/N, and a single-holding portfolio has HHI = 1. We
    rescale linearly so the output is on 0-100:

    * single holding (HHI = 1)                  → 100
    * 2 equal-weight holdings (HHI = 0.5)       → 100 * (0.5 - 1/N_REF) …

    Rather than an arbitrary N-reference, we use the direct rescaling
    ``score = HHI * 100`` which yields:

    * HHI = 1.0 → 100 (max concentration)
    * HHI = 0.5 → 50
    * HHI = 0.05 (~20 equal-weight) → 5

    matching AC #1 and #2 exactly.
    """
    if not weights:
        return RiskMeterComponent(
            name="concentration",
            score=None,
            weight=_WEIGHT_CONCENTRATION,
            detail={"hhi": None, "holdings": 0},
        )
    total = float(sum(abs(w) for w in weights))
    if total <= 0:
        return RiskMeterComponent(
            name="concentration",
            score=None,
            weight=_WEIGHT_CONCENTRATION,
            detail={"hhi": None, "holdings": len(weights)},
        )
    normalized = [abs(w) / total for w in weights]
    hhi = float(sum(w * w for w in normalized))
    score = round(max(0.0, min(100.0, hhi * 100.0)), 1)
    return RiskMeterComponent(
        name="concentration",
        score=score,
        weight=_WEIGHT_CONCENTRATION,
        detail={"hhi": round(hhi, 4), "holdings": len(weights)},
    )


# ---- Component: volatility / VaR ------------------------------------------


def _portfolio_returns(
    weights: dict[str, float],
    price_series: dict[str, pd.Series],
) -> pd.Series:
    """Combine per-holding close series into a weighted portfolio return series.

    Missing symbols are skipped (weight renormalised over what's available).
    Series are aligned on their outer index with forward-fill to tolerate
    mismatched trading calendars; any remaining NaNs are dropped.
    """
    aligned: dict[str, pd.Series] = {}
    total_weight = 0.0
    for symbol, w in weights.items():
        s = price_series.get(symbol)
        if s is None or s.empty:
            continue
        aligned[symbol] = s.astype(float)
        total_weight += abs(w)
    if not aligned or total_weight <= 0:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(aligned).ffill()
    returns = frame.pct_change().dropna(how="all")
    # Renormalise weights across the symbols we actually have.
    norm_weights = pd.Series(
        {sym: abs(weights[sym]) / total_weight for sym in aligned},
        index=list(aligned),
        dtype=float,
    )
    port_returns = (returns.fillna(0.0) * norm_weights).sum(axis=1)
    return port_returns.dropna()


def compute_volatility_var(
    weights: dict[str, float],
    price_series: dict[str, pd.Series],
) -> RiskMeterComponent:
    """Portfolio-level VaR-95 mapped to a 0-100 score.

    Returns ``score=None`` when insufficient data is available (<30 returns),
    which triggers weight renormalisation in :func:`compute_risk_meter`.
    """
    port_returns = _portfolio_returns(weights, price_series)
    n = int(port_returns.shape[0])
    if n < _MIN_RETURNS_FOR_VAR:
        return RiskMeterComponent(
            name="volatility_var",
            score=None,
            weight=_WEIGHT_VOL_VAR,
            detail={"var_95": None, "observations": n},
        )
    pct_5 = float(np.nanpercentile(port_returns.to_numpy(dtype=float), 5.0))
    var_95 = max(0.0, -pct_5)
    # Saturating linear map: 0 VaR -> 0, >= 5 % -> 100.
    ratio = min(1.0, var_95 / _VAR_SATURATION)
    score = round(ratio * 100.0, 1)
    # Annualised volatility for the drill-down detail (not used in scoring
    # but surfaced to the UI).
    vol_annual = float(port_returns.std(ddof=1)) * float(np.sqrt(_TRADING_DAYS_PER_YEAR))
    return RiskMeterComponent(
        name="volatility_var",
        score=score,
        weight=_WEIGHT_VOL_VAR,
        detail={
            "var_95": round(var_95, 4),
            "annual_volatility": round(vol_annual, 4),
            "observations": n,
        },
    )


# ---- Component: drawdown --------------------------------------------------


def compute_drawdown(
    weights: dict[str, float],
    price_series: dict[str, pd.Series],
) -> RiskMeterComponent:
    """Current drawdown of the weighted portfolio value series."""
    if not price_series:
        return RiskMeterComponent(
            name="drawdown",
            score=None,
            weight=_WEIGHT_DRAWDOWN,
            detail={"drawdown": None},
        )
    total_weight = sum(abs(w) for w in weights.values())
    if total_weight <= 0:
        return RiskMeterComponent(
            name="drawdown",
            score=None,
            weight=_WEIGHT_DRAWDOWN,
            detail={"drawdown": None},
        )
    # Build a value index: weighted average of normalised close series. We
    # normalise each series to 1.0 at its first observation so unit-price
    # differences across holdings don't swamp one another.
    frames: list[pd.Series] = []
    for symbol, s in price_series.items():
        w = abs(weights.get(symbol, 0.0))
        if w <= 0 or s.empty:
            continue
        base = float(s.iloc[0])
        if base <= 0:
            continue
        frames.append((s.astype(float) / base) * (w / total_weight))
    if not frames:
        return RiskMeterComponent(
            name="drawdown",
            score=None,
            weight=_WEIGHT_DRAWDOWN,
            detail={"drawdown": None},
        )
    portfolio_value = pd.concat(frames, axis=1).ffill().sum(axis=1).dropna()
    if portfolio_value.empty:
        return RiskMeterComponent(
            name="drawdown",
            score=None,
            weight=_WEIGHT_DRAWDOWN,
            detail={"drawdown": None},
        )
    peak = float(portfolio_value.cummax().iloc[-1])
    current = float(portfolio_value.iloc[-1])
    dd = 0.0 if peak <= 0 else max(0.0, (peak - current) / peak)
    ratio = min(1.0, dd / _DRAWDOWN_SATURATION)
    score = round(ratio * 100.0, 1)
    return RiskMeterComponent(
        name="drawdown",
        score=score,
        weight=_WEIGHT_DRAWDOWN,
        detail={"drawdown": round(dd, 4), "peak": round(peak, 4), "current": round(current, 4)},
    )


# ---- Component: events ----------------------------------------------------


def compute_events(
    upcoming_events: list[date] | None,
    *,
    today: date,
) -> RiskMeterComponent:
    """Proximity-weighted score for earnings / ex-div in the next 5 trading days.

    Each event within the window contributes ``(window - days_away) / window``
    to the raw score; we then saturate at 1.0 so a flurry of events doesn't
    push past the cap. No calendar data at MVP → this returns 0 (per risk
    mitigation in the job brief) rather than ``None``.
    """
    if upcoming_events is None:
        return RiskMeterComponent(
            name="events",
            score=0.0,
            weight=_WEIGHT_EVENTS,
            detail={"window_days": _EVENTS_WINDOW_DAYS, "upcoming": 0, "source": "unavailable"},
        )
    raw = 0.0
    counted = 0
    for ev in upcoming_events:
        delta = (ev - today).days
        if 0 <= delta <= _EVENTS_WINDOW_DAYS:
            raw += (_EVENTS_WINDOW_DAYS - delta) / _EVENTS_WINDOW_DAYS
            counted += 1
    score = round(min(1.0, raw) * 100.0, 1)
    return RiskMeterComponent(
        name="events",
        score=score,
        weight=_WEIGHT_EVENTS,
        detail={"window_days": _EVENTS_WINDOW_DAYS, "upcoming": counted},
    )


# ---- Orchestrator ---------------------------------------------------------


def _classify(score: float) -> str:
    if score <= _GREEN_MAX:
        return "green"
    if score <= _YELLOW_MAX:
        return "yellow"
    return "red"


def compute_risk_meter(
    *,
    holding_weights: list[float],
    weights_by_symbol: dict[str, float],
    price_series: dict[str, pd.Series],
    upcoming_events: list[date] | None,
    today: date,
) -> RiskMeterResult:
    """Blend the four components into the overall Risk Meter score.

    ``holding_weights`` is the positional weight list for the concentration
    component (does not need symbol keys). ``weights_by_symbol`` /
    ``price_series`` are used by the VaR and drawdown components.
    ``upcoming_events`` passes through to :func:`compute_events` and may be
    ``None`` when no calendar is wired yet.
    """
    concentration = compute_concentration(holding_weights)
    vol_var = compute_volatility_var(weights_by_symbol, price_series)
    drawdown = compute_drawdown(weights_by_symbol, price_series)
    events = compute_events(upcoming_events, today=today)

    components = [concentration, vol_var, drawdown, events]
    # Renormalise over components with a non-None score so a missing metric
    # doesn't drag the overall toward zero.
    weighted = 0.0
    weight_sum = 0.0
    for c in components:
        if c.score is None:
            continue
        weighted += c.score * c.weight
        weight_sum += c.weight
    overall = 0.0 if weight_sum == 0 else weighted / weight_sum
    overall_rounded = round(max(0.0, min(100.0, overall)), 1)
    return RiskMeterResult(
        overall_score=overall_rounded,
        color=_classify(overall_rounded),
        components=components,
    )


__all__ = [
    "RiskMeterComponent",
    "RiskMeterResult",
    "compute_concentration",
    "compute_drawdown",
    "compute_events",
    "compute_risk_meter",
    "compute_volatility_var",
]
