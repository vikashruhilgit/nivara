"""Quantitative risk models — VaR, volatility, drawdown, and composite score.

This module is the canonical home for single-instrument risk metrics used by
the Risk Meter (M3-16), the recommendation engine (M3-17), and the Risk
Guardian (M3-20). Correlation-matrix math lives in
:mod:`backend.app.analysis.correlation` to keep this file focused on
single-series computations, but a thin re-export is provided at the bottom so
consumers can import everything from ``backend.app.analysis.risk``.

Definitions
-----------
* **VaR (Value at Risk)** — historical simulation. Given a return series, the
  95 % (resp. 99 %) VaR is the fifth (resp. first) percentile of losses
  expressed as a positive number. We use ``numpy.percentile`` with linear
  interpolation, which is the convention most risk engines default to; that
  choice is captured in :data:`_VAR_INTERPOLATION` so a single place governs
  reproducibility.
* **Volatility** — annualised standard deviation of daily log returns over a
  rolling window (30 or 90 trading days). Multiplied by ``sqrt(252)`` to
  annualise, matching conventional finance-industry reporting.
* **Drawdown** — current fractional distance below the running peak of the
  close series. ``0.15`` means 15 % below peak.
* **Risk score** — weighted blend of volatility, drawdown, and VaR magnitude,
  mapped onto ``[0, 100]``. When insufficient history is available we fall
  back to a per-sector default (captured in :data:`_SECTOR_PROXY_SCORES`).

Insufficient-data policy
------------------------
We prefer returning ``status="insufficient_data"`` over returning a bogus
point estimate. The one exception is volatility: if fewer than 30 bars are
available we still compute it but flag ``estimated=True`` so callers can
render a caveat. The rationale is that volatility with 20 bars is still a
useful sanity-check, whereas a VaR with 20 bars is dangerously misleading
(tail events do not appear in short windows).

Missing-data policy
-------------------
Single-day gaps (<=5 consecutive missing days per AC #7/#8) are forward
filled before computing returns. Longer gaps flip the
``excluded_from_correlation`` data-quality flag so the correlation module
can drop the series from any matrix it builds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

# ---- Constants -------------------------------------------------------------

_MIN_RETURNS_FOR_VAR = 30
_VAR_LOOKBACK = 252  # 1 trading year per brief
_VOL_WINDOW_SHORT = 30
_VOL_WINDOW_LONG = 90
_TRADING_DAYS_PER_YEAR = 252
_FORWARD_FILL_LIMIT = 5  # AC #7: <=5 days -> forward fill; >5 excludes from correlation.

# numpy.percentile interpolation method. Pinned here so risk-model output is
# bit-reproducible across numpy versions; "linear" is the historical default.
_VAR_INTERPOLATION: Literal["linear"] = "linear"

# Sector-average fallback scores per brief AC #4. These are intentionally
# conservative point estimates derived from long-run historical volatility
# rankings; a later job can replace them with a DB-backed lookup.
_SECTOR_PROXY_SCORES: dict[str, int] = {
    "technology": 60,
    "consumer_discretionary": 55,
    "communication_services": 55,
    "energy": 70,
    "financials": 55,
    "utilities": 35,
    "consumer_staples": 35,
    "healthcare": 45,
    "industrials": 50,
    "materials": 60,
    "real_estate": 50,
    "crypto": 85,
}
_DEFAULT_PROXY_SCORE = 55  # Used when sector is unknown.


# ---- Dataclasses -----------------------------------------------------------


@dataclass(frozen=True)
class VaR:
    status: str  # "ok" | "insufficient_data" | "empty"
    var_95: float | None
    var_99: float | None
    lookback_days: int


@dataclass(frozen=True)
class Volatility:
    vol_30d: float | None
    vol_90d: float | None
    estimated: bool


@dataclass(frozen=True)
class Drawdown:
    drawdown: float | None
    peak_price: float | None
    current_price: float | None


@dataclass(frozen=True)
class RiskScore:
    score: int
    proxy_based: bool
    sector: str | None


@dataclass(frozen=True)
class DataQualityReport:
    observations: int
    forward_filled_days: int
    excluded_from_correlation: bool
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RiskAnalysis:
    """Full output of :func:`analyze_risk`."""

    var: VaR
    volatility: Volatility
    drawdown: Drawdown
    risk_score: RiskScore
    data_quality: DataQualityReport
    bars_analyzed: int


# ---- Data preparation ------------------------------------------------------


def prepare_close_series(close: pd.Series) -> tuple[pd.Series, DataQualityReport]:
    """Clean a close-price series for risk analysis.

    Rules (AC #7, #8):

    * Forward-fill any run of <= :data:`_FORWARD_FILL_LIMIT` consecutive NaNs.
    * If a run exceeds the threshold, the series is flagged as "exclude from
      correlation" — we still analyse it for VaR/volatility (those can live
      with gappy data since we compute from simple returns) but the flag
      propagates to the data-quality report so the correlation module skips
      the series.
    * Drop leading NaNs after fill (series must start at a real observation).
    """
    if close.empty:
        return close, DataQualityReport(
            observations=0, forward_filled_days=0, excluded_from_correlation=False, notes=["empty"]
        )
    s = close.astype(float).copy()
    # Identify runs of consecutive NaNs so we can count what gets filled vs
    # flagged. Simpler than tracking the diff: just count NaNs before & after
    # a limit-capped forward fill.
    nan_count_before = int(s.isna().sum())
    filled = s.ffill(limit=_FORWARD_FILL_LIMIT)
    # Anything still NaN after the limited ffill is a run longer than the
    # threshold (or a leading NaN, which we drop below).
    excluded = bool(filled.isna().any())
    # Drop remaining NaNs (long gaps or leading NaNs).
    cleaned = filled.dropna()
    # The forward-filled count = NaNs that were present originally minus the
    # ones we had to drop (runs longer than the ffill limit, plus any leading
    # NaNs). ``s.shape[0] - cleaned.shape[0]`` is the number dropped.
    forward_filled = max(0, nan_count_before - (int(s.shape[0]) - int(cleaned.shape[0])))
    notes: list[str] = []
    if excluded:
        notes.append(f"gap exceeded forward-fill limit of {_FORWARD_FILL_LIMIT} days")
    return cleaned, DataQualityReport(
        observations=int(cleaned.shape[0]),
        forward_filled_days=forward_filled,
        excluded_from_correlation=excluded,
        notes=notes,
    )


def daily_log_returns(close: pd.Series) -> pd.Series:
    """Daily log returns ``ln(p_t / p_{t-1})``. Strips the initial NaN."""
    if close.empty:
        return pd.Series(dtype=float)
    return np.log(close.astype(float)).diff().dropna()


# ---- Individual risk metrics -----------------------------------------------


def compute_var(returns: pd.Series, lookback: int = _VAR_LOOKBACK) -> VaR:
    """Historical-simulation VaR at 95 % and 99 %.

    Uses the most recent ``lookback`` returns (or all available, whichever is
    smaller). Refuses to compute if fewer than :data:`_MIN_RETURNS_FOR_VAR`
    observations are available — see module docstring for why.

    Returns losses as *positive* numbers: ``var_95 = 0.04`` means "we expect
    to lose at most 4 % on 95 % of days".
    """
    if returns.empty:
        return VaR(status="empty", var_95=None, var_99=None, lookback_days=0)
    # Window the tail to lookback (data is expected ascending by date).
    windowed = returns.tail(lookback)
    n = int(windowed.shape[0])
    if n < _MIN_RETURNS_FOR_VAR:
        return VaR(status="insufficient_data", var_95=None, var_99=None, lookback_days=n)
    # Historical simulation: take the 5th percentile of returns; losses are
    # the negation of negative returns. Using nanpercentile guards against
    # stray NaNs we didn't catch earlier.
    arr = windowed.to_numpy(dtype=float)
    pct_5 = float(np.nanpercentile(arr, 5.0, method=_VAR_INTERPOLATION))
    pct_1 = float(np.nanpercentile(arr, 1.0, method=_VAR_INTERPOLATION))
    # Convert return percentiles to positive loss fractions (0 if the
    # percentile is positive, which can happen in strong bull runs).
    var_95 = max(0.0, -pct_5)
    var_99 = max(0.0, -pct_1)
    return VaR(status="ok", var_95=var_95, var_99=var_99, lookback_days=n)


def compute_volatility(returns: pd.Series) -> Volatility:
    """Annualised std dev over 30- and 90-day rolling windows.

    If fewer than 30 observations are present we still compute over the
    available window but flag ``estimated=True`` per AC #3.
    """
    n = int(returns.shape[0])
    if n == 0:
        return Volatility(vol_30d=None, vol_90d=None, estimated=False)
    sqrt_yr = float(np.sqrt(_TRADING_DAYS_PER_YEAR))
    estimated = n < _VOL_WINDOW_SHORT
    # ddof=1 matches numpy/pandas default sample std dev.
    vol_30 = float(returns.tail(_VOL_WINDOW_SHORT).std(ddof=1)) * sqrt_yr if n >= 2 else None
    vol_90 = float(returns.tail(_VOL_WINDOW_LONG).std(ddof=1)) * sqrt_yr if n >= 2 else None
    # Convert possible NaN (e.g. constant series, or n==1) to None.
    if vol_30 is not None and not np.isfinite(vol_30):
        vol_30 = None
    if vol_90 is not None and not np.isfinite(vol_90):
        vol_90 = None
    return Volatility(vol_30d=vol_30, vol_90d=vol_90, estimated=estimated)


def compute_drawdown(close: pd.Series) -> Drawdown:
    """Current drawdown from running peak.

    ``drawdown = (peak - current) / peak`` expressed as a positive fraction.
    Returns ``None`` fields on an empty series.
    """
    if close.empty:
        return Drawdown(drawdown=None, peak_price=None, current_price=None)
    peak = float(close.cummax().iloc[-1])
    current = float(close.iloc[-1])
    if peak <= 0:
        return Drawdown(drawdown=None, peak_price=peak, current_price=current)
    dd = max(0.0, (peak - current) / peak)
    return Drawdown(drawdown=dd, peak_price=peak, current_price=current)


# ---- Composite risk score --------------------------------------------------


def _score_from_metrics(vol: Volatility, drawdown: Drawdown, var: VaR) -> int:
    """Blend volatility / drawdown / VaR into a 0-100 risk score.

    Mapping rationale: we want a score that's interpretable to a retail user
    where 0 is "negligible risk" and 100 is "speculative". Each input is
    mapped onto a 0-100 sub-score with saturating ceilings so a single
    pathological metric can push the blend high but cannot alone pin it to
    100.

    Weights (sum to 1.0):
      * Volatility 90d: 0.5  (structural risk signal)
      * Current drawdown: 0.3  (acute stress signal)
      * VaR-95:         0.2  (tail-risk signal)
    """
    # Volatility: 10 % annualised -> 20, 30 % -> 60, 60 % -> 100.
    vol_input = vol.vol_90d if vol.vol_90d is not None else vol.vol_30d
    vol_sub = _saturate(vol_input, low=0.05, high=0.60, low_score=0.0, high_score=100.0)
    # Drawdown: 0 -> 0, 30 % -> 60, 60 %+ -> 100.
    dd_sub = _saturate(drawdown.drawdown, low=0.0, high=0.60, low_score=0.0, high_score=100.0)
    # VaR: 1 % daily -> 20, 3 % -> 60, 6 % -> 100.
    var_sub = _saturate(var.var_95, low=0.005, high=0.06, low_score=0.0, high_score=100.0)

    # When a sub-metric is missing we renormalise the weights over what we
    # have, so a missing VaR doesn't drag the score toward zero.
    weighted = 0.0
    weight_sum = 0.0
    for score, weight in ((vol_sub, 0.5), (dd_sub, 0.3), (var_sub, 0.2)):
        if score is None:
            continue
        weighted += score * weight
        weight_sum += weight
    if weight_sum == 0:
        return _DEFAULT_PROXY_SCORE
    composite = weighted / weight_sum
    return int(round(max(0.0, min(100.0, composite))))


def _saturate(
    value: float | None,
    *,
    low: float,
    high: float,
    low_score: float,
    high_score: float,
) -> float | None:
    """Linearly map ``value`` from ``[low, high]`` to ``[low_score, high_score]``.

    Values outside the interval clamp. ``None`` propagates as ``None``.
    """
    if value is None:
        return None
    if value <= low:
        return low_score
    if value >= high:
        return high_score
    t = (value - low) / (high - low)
    return low_score + t * (high_score - low_score)


def compute_risk_score(
    *,
    returns: pd.Series,
    volatility: Volatility,
    drawdown: Drawdown,
    var: VaR,
    sector: str | None,
) -> RiskScore:
    """Return a 0-100 risk score, proxying to a sector default when data is thin.

    AC #4: when fewer than 30 return observations are available we fall back
    to a sector proxy (or :data:`_DEFAULT_PROXY_SCORE`) and flag the result
    as ``proxy_based=True``.
    """
    if int(returns.shape[0]) < _MIN_RETURNS_FOR_VAR:
        key = (sector or "").strip().lower().replace(" ", "_")
        proxy = _SECTOR_PROXY_SCORES.get(key, _DEFAULT_PROXY_SCORE)
        return RiskScore(score=proxy, proxy_based=True, sector=sector)
    score = _score_from_metrics(volatility, drawdown, var)
    return RiskScore(score=score, proxy_based=False, sector=sector)


# ---- Orchestration ---------------------------------------------------------


def analyze_risk(close: pd.Series, *, sector: str | None = None) -> RiskAnalysis:
    """Compute the full risk panel for a close-price series.

    ``close`` must be indexed by date (ascending). Missing observations are
    handled per the module-level policy. ``sector`` is used for the
    insufficient-data proxy fallback on the composite score.
    """
    cleaned, quality = prepare_close_series(close)
    returns = daily_log_returns(cleaned)
    var = compute_var(returns)
    vol = compute_volatility(returns)
    drawdown = compute_drawdown(cleaned)
    score = compute_risk_score(
        returns=returns, volatility=vol, drawdown=drawdown, var=var, sector=sector
    )
    return RiskAnalysis(
        var=var,
        volatility=vol,
        drawdown=drawdown,
        risk_score=score,
        data_quality=quality,
        bars_analyzed=int(cleaned.shape[0]),
    )


# Re-export correlation helpers so callers can do a single import.
from backend.app.analysis.correlation import (  # noqa: E402  (placed after dataclasses to avoid cycle)
    MAX_PORTFOLIO_SIZE,
    CorrelationMatrix,
    compute_correlation,
    compute_correlation_matrix,
)

__all__ = [
    "CorrelationMatrix",
    "DataQualityReport",
    "Drawdown",
    "MAX_PORTFOLIO_SIZE",
    "RiskAnalysis",
    "RiskScore",
    "VaR",
    "Volatility",
    "analyze_risk",
    "compute_correlation",
    "compute_correlation_matrix",
    "compute_drawdown",
    "compute_risk_score",
    "compute_var",
    "compute_volatility",
    "daily_log_returns",
    "prepare_close_series",
]
