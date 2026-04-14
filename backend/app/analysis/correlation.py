"""Correlation helpers — pairwise Pearson and portfolio correlation matrices.

Kept in its own module so :mod:`backend.app.analysis.risk` can focus on
single-instrument metrics. Two entry points are exposed:

* :func:`compute_correlation` — Pearson coefficient between two aligned
  return series on a rolling 90-day window (AC #5).
* :func:`compute_correlation_matrix` — a full ``n x n`` Pearson matrix over
  aligned 90-day daily returns (AC #6), capped at :data:`MAX_PORTFOLIO_SIZE`
  instruments.

Both functions consume *return* series (not prices). Callers typically
derive returns via :func:`backend.app.analysis.risk.daily_log_returns`. We
deliberately keep this at "returns in, coefficient out" so the module has no
dependency on the DB layer and can be exercised by pure-python tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Brief risk-mitigation row: cap portfolios to keep matrix computation cheap
# and the resulting JSON payload under a reasonable size.
MAX_PORTFOLIO_SIZE = 50

_CORR_WINDOW = 90
_MIN_OBSERVATIONS = 30  # mirror the VaR threshold for consistency


@dataclass(frozen=True)
class CorrelationMatrix:
    """Result of :func:`compute_correlation_matrix`.

    ``symbols`` and ``matrix`` are aligned: ``matrix[i][j]`` is the Pearson
    correlation between ``symbols[i]`` and ``symbols[j]``. ``excluded`` lists
    any symbols dropped for insufficient data.
    """

    symbols: list[str]
    matrix: list[list[float]]
    window_days: int
    excluded: list[str] = field(default_factory=list)


def compute_correlation(
    returns_a: pd.Series,
    returns_b: pd.Series,
    window: int = _CORR_WINDOW,
) -> float | None:
    """Pearson correlation of two return series over the last ``window`` days.

    Aligns on the shared index (inner join) before taking the last ``window``
    observations — this keeps the correlation honest when one series starts
    later than the other. Returns ``None`` if fewer than
    :data:`_MIN_OBSERVATIONS` overlapping observations remain.
    """
    if returns_a.empty or returns_b.empty:
        return None
    aligned = pd.concat([returns_a, returns_b], axis=1, join="inner").dropna()
    if aligned.shape[0] < _MIN_OBSERVATIONS:
        return None
    tail = aligned.tail(window)
    # numpy.corrcoef over the two columns is ~10x faster than pandas .corr()
    # for small matrices and avoids the DataFrame round-trip.
    a = tail.iloc[:, 0].to_numpy(dtype=float)
    b = tail.iloc[:, 1].to_numpy(dtype=float)
    # Constant series -> variance 0 -> corrcoef would emit NaN. Guard explicitly.
    if float(np.var(a)) == 0.0 or float(np.var(b)) == 0.0:
        return None
    coef = float(np.corrcoef(a, b)[0, 1])
    if not np.isfinite(coef):
        return None
    return coef


def compute_correlation_matrix(
    returns_by_symbol: dict[str, pd.Series],
    window: int = _CORR_WINDOW,
) -> CorrelationMatrix:
    """Build an ``n x n`` Pearson matrix over the supplied return series.

    Symbols with fewer than :data:`_MIN_OBSERVATIONS` overlapping observations
    after alignment are dropped into :attr:`CorrelationMatrix.excluded` with
    an ``"insufficient"`` reason flag captured by the caller's data-quality
    report. Portfolios larger than :data:`MAX_PORTFOLIO_SIZE` raise
    :class:`ValueError` to force the caller to slice / rank beforehand.
    """
    if not returns_by_symbol:
        return CorrelationMatrix(symbols=[], matrix=[], window_days=window, excluded=[])
    if len(returns_by_symbol) > MAX_PORTFOLIO_SIZE:
        raise ValueError(
            f"portfolio size {len(returns_by_symbol)} exceeds cap of {MAX_PORTFOLIO_SIZE}"
        )
    # Align all series on their union index, then forward-fill the union so
    # short gaps don't push otherwise-valid pairs below the threshold. The
    # risk module's caller is responsible for feeding us only series that
    # survived the "exclude on long gap" check.
    frame = pd.DataFrame(returns_by_symbol).dropna(how="all")
    # Keep only columns with enough observations.
    kept: list[str] = []
    excluded: list[str] = []
    for col in frame.columns:
        if int(frame[col].dropna().shape[0]) < _MIN_OBSERVATIONS:
            excluded.append(col)
        else:
            kept.append(col)
    if not kept:
        return CorrelationMatrix(symbols=[], matrix=[], window_days=window, excluded=excluded)
    tail = frame[kept].tail(window)
    # Pandas .corr() drops NaNs pairwise, which is what we want.
    corr = tail.corr(method="pearson")
    # Any residual NaNs (e.g. constant series) become 0.0 — correlation is
    # undefined for a zero-variance series; 0 is the conservative substitute.
    corr = corr.fillna(0.0)
    return CorrelationMatrix(
        symbols=kept,
        matrix=[[float(x) for x in row] for row in corr.to_numpy()],
        window_days=window,
        excluded=excluded,
    )


__all__ = [
    "CorrelationMatrix",
    "MAX_PORTFOLIO_SIZE",
    "compute_correlation",
    "compute_correlation_matrix",
]
