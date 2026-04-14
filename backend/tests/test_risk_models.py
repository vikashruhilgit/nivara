"""Tests for :mod:`backend.app.analysis.risk` and ``...analysis.correlation``.

Exercises each metric in isolation plus the full :func:`analyze_risk`
orchestration and both correlation entry points. All tests run on synthetic
price series so they're deterministic and independent of any provider or DB
layer. Brief acceptance-criteria coverage is called out in each test's
docstring (e.g. "AC #1") so the mapping back to the job brief is explicit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from backend.app.analysis.correlation import (
    MAX_PORTFOLIO_SIZE,
    compute_correlation,
    compute_correlation_matrix,
)
from backend.app.analysis.risk import (
    _DEFAULT_PROXY_SCORE,
    _SECTOR_PROXY_SCORES,
    analyze_risk,
    compute_drawdown,
    compute_risk_score,
    compute_var,
    compute_volatility,
    daily_log_returns,
    prepare_close_series,
)

# ---- Helpers --------------------------------------------------------------


def _close_series(n: int, *, seed: int = 42, mu: float = 0.0005, sigma: float = 0.015) -> pd.Series:
    """Build a deterministic synthetic close-price series of length ``n``."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(mu, sigma, n)
    close = 100.0 * np.cumprod(1.0 + returns)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.Series(close, index=idx, name="close")


# ---- VaR -------------------------------------------------------------------


def test_var_returns_95_and_99_percentiles_with_252_days() -> None:
    """AC #1: 252d of returns -> 95 % and 99 % historical-simulation VaR."""
    close = _close_series(253)  # 253 closes -> 252 returns after diff
    returns = daily_log_returns(close)
    result = compute_var(returns)

    assert result.status == "ok"
    assert result.var_95 is not None
    assert result.var_99 is not None
    # 99 % VaR must be at least as large as 95 % — it's a deeper loss percentile.
    assert result.var_99 >= result.var_95
    # Both should be positive loss fractions well under 1 for a normal-ish series.
    assert 0.0 <= result.var_95 < 1.0
    assert 0.0 <= result.var_99 < 1.0
    assert result.lookback_days == 252


def test_var_insufficient_data_below_30() -> None:
    """AC #2: fewer than 30 return observations -> insufficient_data status."""
    close = _close_series(20)
    returns = daily_log_returns(close)
    result = compute_var(returns)

    assert result.status == "insufficient_data"
    assert result.var_95 is None
    assert result.var_99 is None


def test_var_empty_series() -> None:
    """Empty input must not crash and must return status=empty."""
    result = compute_var(pd.Series(dtype=float))
    assert result.status == "empty"
    assert result.var_95 is None and result.var_99 is None
    assert result.lookback_days == 0


# ---- Volatility ------------------------------------------------------------


def test_volatility_annualised_on_full_history() -> None:
    """90d/30d vols are positive and the 30d matches a manual sqrt(252) check."""
    close = _close_series(260, sigma=0.02)
    returns = daily_log_returns(close)
    vol = compute_volatility(returns)

    assert vol.vol_30d is not None and vol.vol_30d > 0
    assert vol.vol_90d is not None and vol.vol_90d > 0
    assert vol.estimated is False
    manual = float(returns.tail(30).std(ddof=1)) * float(np.sqrt(252))
    assert vol.vol_30d == pytest.approx(manual, rel=1e-9)


def test_volatility_flagged_estimated_below_30_returns() -> None:
    """AC #3: <30 returns -> still computed but ``estimated=True``."""
    close = _close_series(15)
    returns = daily_log_returns(close)
    vol = compute_volatility(returns)

    assert vol.estimated is True
    # With 14 returns we can still compute a std dev; value must be finite.
    assert vol.vol_30d is not None and np.isfinite(vol.vol_30d)


# ---- Drawdown --------------------------------------------------------------


def test_drawdown_15_percent_below_peak() -> None:
    """AC #10: current = peak * 0.85 -> drawdown == 0.15."""
    close = pd.Series([100.0, 110.0, 120.0, 115.0, 102.0])  # peak 120 -> current 102
    dd = compute_drawdown(close)
    assert dd.peak_price == 120.0
    assert dd.current_price == 102.0
    assert dd.drawdown == pytest.approx(0.15, rel=1e-9)


def test_drawdown_zero_when_at_peak() -> None:
    close = pd.Series([100.0, 110.0, 115.0, 120.0])  # monotonic up
    dd = compute_drawdown(close)
    assert dd.drawdown == 0.0


def test_drawdown_empty_series() -> None:
    dd = compute_drawdown(pd.Series(dtype=float))
    assert dd.drawdown is None
    assert dd.peak_price is None
    assert dd.current_price is None


# ---- Missing-data handling -------------------------------------------------


def test_forward_fill_short_gap() -> None:
    """AC #7: <=5 day gaps are forward-filled, not dropped."""
    values = [100.0, 101.0, np.nan, np.nan, 103.0, 104.0]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=6, freq="D"))

    cleaned, report = prepare_close_series(close)
    assert report.excluded_from_correlation is False
    # Both NaNs should have been filled to 101.0 and the cleaned series keeps
    # every observation.
    assert len(cleaned) == 6
    assert cleaned.iloc[2] == 101.0 and cleaned.iloc[3] == 101.0
    assert report.forward_filled_days >= 2


def test_long_gap_flags_excluded_from_correlation() -> None:
    """AC #8: gap > 5 days flips ``excluded_from_correlation`` to True."""
    values = [100.0, 101.0] + [np.nan] * 7 + [110.0]
    close = pd.Series(values, index=pd.date_range("2024-01-01", periods=10, freq="D"))

    cleaned, report = prepare_close_series(close)
    assert report.excluded_from_correlation is True
    # The 7 NaNs exceed the fill limit, so they get dropped -> series shorter.
    assert len(cleaned) < len(close)
    assert any("gap" in n for n in report.notes)


# ---- Risk score ------------------------------------------------------------


def test_risk_score_uses_sector_proxy_on_thin_data() -> None:
    """AC #4: <30 returns -> sector-average proxy score with proxy_based flag."""
    close = _close_series(10)
    returns = daily_log_returns(close)
    vol = compute_volatility(returns)
    dd = compute_drawdown(close)
    var = compute_var(returns)

    rs = compute_risk_score(
        returns=returns, volatility=vol, drawdown=dd, var=var, sector="Technology"
    )
    assert rs.proxy_based is True
    assert rs.score == _SECTOR_PROXY_SCORES["technology"]
    assert rs.sector == "Technology"


def test_risk_score_default_proxy_for_unknown_sector() -> None:
    close = _close_series(10)
    returns = daily_log_returns(close)
    rs = compute_risk_score(
        returns=returns,
        volatility=compute_volatility(returns),
        drawdown=compute_drawdown(close),
        var=compute_var(returns),
        sector="MysteryCategory",
    )
    assert rs.proxy_based is True
    assert rs.score == _DEFAULT_PROXY_SCORE


def test_risk_score_computed_from_metrics_when_data_sufficient() -> None:
    """With full history the score is data-driven and 0 <= score <= 100."""
    close = _close_series(260, sigma=0.03)
    returns = daily_log_returns(close)
    rs = compute_risk_score(
        returns=returns,
        volatility=compute_volatility(returns),
        drawdown=compute_drawdown(close),
        var=compute_var(returns),
        sector="Technology",
    )
    assert rs.proxy_based is False
    assert 0 <= rs.score <= 100


# ---- Orchestration ---------------------------------------------------------


def test_analyze_risk_returns_full_panel() -> None:
    """AC #9 shape: VaR + vols + drawdown + score + quality all populated."""
    close = _close_series(260)
    analysis = analyze_risk(close, sector="Technology")

    assert analysis.bars_analyzed == 260
    assert analysis.var.status == "ok"
    assert analysis.volatility.vol_30d is not None
    assert analysis.volatility.vol_90d is not None
    assert analysis.drawdown.drawdown is not None
    assert 0 <= analysis.risk_score.score <= 100
    assert analysis.risk_score.proxy_based is False
    assert analysis.data_quality.observations == 260


def test_analyze_risk_short_history_uses_proxy_and_flags_estimated() -> None:
    close = _close_series(15)
    analysis = analyze_risk(close, sector="Healthcare")

    assert analysis.var.status == "insufficient_data"
    assert analysis.volatility.estimated is True
    assert analysis.risk_score.proxy_based is True
    assert analysis.risk_score.score == _SECTOR_PROXY_SCORES["healthcare"]


# ---- Correlation ------------------------------------------------------------


def test_pairwise_correlation_on_90_day_window() -> None:
    """AC #5: 90d of returns for two series -> Pearson coefficient."""
    # Build two strongly-correlated series (shared noise component dominates).
    rng = np.random.default_rng(7)
    shared = rng.normal(0, 0.01, 120)
    idx = pd.date_range("2024-01-01", periods=120, freq="D")
    a = pd.Series(shared + rng.normal(0, 0.001, 120), index=idx)
    b = pd.Series(shared + rng.normal(0, 0.001, 120), index=idx)

    rho = compute_correlation(a, b)
    assert rho is not None
    assert rho > 0.9  # very high by construction


def test_pairwise_correlation_insufficient_observations() -> None:
    idx = pd.date_range("2024-01-01", periods=20, freq="D")
    a = pd.Series(np.linspace(0.0, 0.01, 20), index=idx)
    b = pd.Series(np.linspace(0.01, 0.0, 20), index=idx)
    assert compute_correlation(a, b) is None


def test_correlation_matrix_5x5() -> None:
    """AC #6: 5 instruments over 90d -> 5x5 Pearson matrix."""
    rng = np.random.default_rng(11)
    idx = pd.date_range("2024-01-01", periods=120, freq="D")
    returns_by_symbol = {
        sym: pd.Series(rng.normal(0, 0.01, 120), index=idx)
        for sym in ("AAA", "BBB", "CCC", "DDD", "EEE")
    }
    result = compute_correlation_matrix(returns_by_symbol)

    assert len(result.symbols) == 5
    assert len(result.matrix) == 5
    for row in result.matrix:
        assert len(row) == 5
    # Diagonal must be ~1.0 (self-correlation).
    for i in range(5):
        assert result.matrix[i][i] == pytest.approx(1.0, abs=1e-9)
    # Matrix must be symmetric.
    for i in range(5):
        for j in range(5):
            assert result.matrix[i][j] == pytest.approx(result.matrix[j][i], abs=1e-9)
    assert result.window_days == 90
    assert result.excluded == []


def test_correlation_matrix_drops_insufficient_series() -> None:
    """AC #8: series with too few observations are excluded, not matrixed."""
    idx_long = pd.date_range("2024-01-01", periods=120, freq="D")
    idx_short = pd.date_range("2024-01-01", periods=20, freq="D")
    rng = np.random.default_rng(13)
    returns_by_symbol = {
        "LONG_A": pd.Series(rng.normal(0, 0.01, 120), index=idx_long),
        "LONG_B": pd.Series(rng.normal(0, 0.01, 120), index=idx_long),
        "SHORT": pd.Series(rng.normal(0, 0.01, 20), index=idx_short),
    }
    result = compute_correlation_matrix(returns_by_symbol)
    assert "SHORT" in result.excluded
    assert set(result.symbols) == {"LONG_A", "LONG_B"}


def test_correlation_matrix_portfolio_cap() -> None:
    """Portfolios larger than :data:`MAX_PORTFOLIO_SIZE` are rejected loudly."""
    idx = pd.date_range("2024-01-01", periods=120, freq="D")
    returns = {f"S{i}": pd.Series(np.zeros(120), index=idx) for i in range(MAX_PORTFOLIO_SIZE + 1)}
    with pytest.raises(ValueError, match="exceeds cap"):
        compute_correlation_matrix(returns)


def test_correlation_matrix_empty_input() -> None:
    result = compute_correlation_matrix({})
    assert result.symbols == []
    assert result.matrix == []
    assert result.excluded == []
