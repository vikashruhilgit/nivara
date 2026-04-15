"""Recommendation staleness classification + confidence reduction (M4-23 S2).

The synthesizer timestamps every recommendation with ``computed_at``. As the
underlying engine outputs age, downstream consumers (mobile feed + detail
screens) need to convey *how stale* the data is so users can interpret the
call with appropriate trust.

Four bands — thresholds configurable via :class:`Settings`, defaults:

* ``< 1h``   → :class:`StalenessLevel.FRESH`      no confidence penalty
* ``< 6h``   → :class:`StalenessLevel.AGING`      -5 percentage points
* ``< 24h``  → :class:`StalenessLevel.STALE`      -15 percentage points
* ``>= 24h`` → :class:`StalenessLevel.SUPPRESSED` recommendation hidden
              from the feed; direct navigation shows "Data too old".

The function signature is deliberately pure — callers pass ``created_at``
and ``now`` explicitly so tests can freeze time without monkeypatching.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from backend.app.config import get_settings


class StalenessLevel(StrEnum):
    """Discrete staleness bands used by the mobile feed + synthesizer."""

    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    SUPPRESSED = "suppressed"


# Default reduction schedule (percentage points subtracted from confidence).
_DEFAULT_REDUCTIONS: dict[StalenessLevel, float] = {
    StalenessLevel.FRESH: 0.0,
    StalenessLevel.AGING: 5.0,
    StalenessLevel.STALE: 15.0,
    StalenessLevel.SUPPRESSED: 0.0,  # suppressed recs aren't returned.
}


def _thresholds() -> tuple[float, float, float]:
    """Return ``(fresh_h, aging_h, stale_h)`` thresholds in hours."""
    s = get_settings()
    fresh_h = float(getattr(s, "staleness_fresh_hours", 1.0))
    aging_h = float(getattr(s, "staleness_aging_hours", 6.0))
    stale_h = float(getattr(s, "staleness_stale_hours", 24.0))
    return fresh_h, aging_h, stale_h


def classify_staleness(created_at: datetime, now: datetime) -> StalenessLevel:
    """Classify a recommendation's age into one of four bands.

    Both ``created_at`` and ``now`` must be timezone-aware (UTC recommended).
    If ``created_at`` is in the future (clock skew), we treat it as fresh.
    """
    fresh_h, aging_h, stale_h = _thresholds()
    age: timedelta = now - created_at
    hours = age.total_seconds() / 3600.0
    if hours < 0:
        return StalenessLevel.FRESH
    if hours < fresh_h:
        return StalenessLevel.FRESH
    if hours < aging_h:
        return StalenessLevel.AGING
    if hours < stale_h:
        return StalenessLevel.STALE
    return StalenessLevel.SUPPRESSED


def apply_confidence_reduction(confidence: float, level: StalenessLevel) -> float:
    """Return ``confidence`` reduced by the staleness penalty, clamped to [0, 100].

    ``SUPPRESSED`` is a signal for callers to drop the recommendation entirely;
    we still return a clamped value (0) so this function never raises.
    """
    if level is StalenessLevel.SUPPRESSED:
        return 0.0
    penalty = _DEFAULT_REDUCTIONS.get(level, 0.0)
    reduced = confidence - penalty
    if reduced < 0.0:
        return 0.0
    if reduced > 100.0:
        return 100.0
    return reduced


__all__ = [
    "StalenessLevel",
    "apply_confidence_reduction",
    "classify_staleness",
]
