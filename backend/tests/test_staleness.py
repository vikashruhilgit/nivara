"""Tests for recommendation staleness classification + confidence reduction (M4-23 S2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from backend.app.config import get_settings
from backend.app.intelligence.staleness import (
    StalenessLevel,
    apply_confidence_reduction,
    classify_staleness,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Ensure each test sees a pristine Settings instance."""
    get_settings.cache_clear()


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# classify_staleness — banding                                                 #
# --------------------------------------------------------------------------- #


def test_fresh_when_well_under_one_hour() -> None:
    now = _now()
    created = now - timedelta(minutes=30)
    assert classify_staleness(created, now) is StalenessLevel.FRESH


def test_fresh_just_under_one_hour_boundary() -> None:
    now = _now()
    created = now - timedelta(minutes=59, seconds=59)
    assert classify_staleness(created, now) is StalenessLevel.FRESH


def test_aging_at_one_hour_exactly() -> None:
    """At exactly 1h (boundary), the rec transitions from fresh -> aging."""
    now = _now()
    created = now - timedelta(hours=1)
    assert classify_staleness(created, now) is StalenessLevel.AGING


def test_aging_around_three_hours_ac6() -> None:
    now = _now()
    created = now - timedelta(hours=3)
    assert classify_staleness(created, now) is StalenessLevel.AGING


def test_aging_just_under_six_hours_boundary() -> None:
    now = _now()
    created = now - timedelta(hours=5, minutes=59)
    assert classify_staleness(created, now) is StalenessLevel.AGING


def test_stale_at_six_hours_exactly() -> None:
    now = _now()
    created = now - timedelta(hours=6)
    assert classify_staleness(created, now) is StalenessLevel.STALE


def test_stale_around_twelve_hours_ac7() -> None:
    now = _now()
    created = now - timedelta(hours=12)
    assert classify_staleness(created, now) is StalenessLevel.STALE


def test_stale_just_under_twenty_four_hours() -> None:
    now = _now()
    created = now - timedelta(hours=23, minutes=59)
    assert classify_staleness(created, now) is StalenessLevel.STALE


def test_suppressed_at_twenty_four_hours_exactly_ac8() -> None:
    now = _now()
    created = now - timedelta(hours=24)
    assert classify_staleness(created, now) is StalenessLevel.SUPPRESSED


def test_suppressed_far_beyond_twenty_four_hours() -> None:
    now = _now()
    created = now - timedelta(days=3)
    assert classify_staleness(created, now) is StalenessLevel.SUPPRESSED


def test_future_timestamp_treated_as_fresh() -> None:
    """Clock skew guard: created_at > now should not flip to suppressed."""
    now = _now()
    created = now + timedelta(minutes=5)
    assert classify_staleness(created, now) is StalenessLevel.FRESH


# --------------------------------------------------------------------------- #
# apply_confidence_reduction                                                   #
# --------------------------------------------------------------------------- #


def test_fresh_has_no_penalty_ac5() -> None:
    assert apply_confidence_reduction(80.0, StalenessLevel.FRESH) == 80.0


def test_aging_reduces_by_five_points_ac6() -> None:
    assert apply_confidence_reduction(80.0, StalenessLevel.AGING) == 75.0


def test_stale_reduces_by_fifteen_points_ac7() -> None:
    assert apply_confidence_reduction(80.0, StalenessLevel.STALE) == 65.0


def test_suppressed_zeroes_confidence() -> None:
    assert apply_confidence_reduction(80.0, StalenessLevel.SUPPRESSED) == 0.0


def test_reduction_clamped_to_zero_floor() -> None:
    assert apply_confidence_reduction(3.0, StalenessLevel.STALE) == 0.0


def test_reduction_clamped_to_hundred_ceiling() -> None:
    # Bogus inputs shouldn't produce >100.
    assert apply_confidence_reduction(150.0, StalenessLevel.FRESH) == 100.0


# --------------------------------------------------------------------------- #
# Configurability                                                              #
# --------------------------------------------------------------------------- #


def test_thresholds_respect_settings_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirm env overrides retune the bands."""
    monkeypatch.setenv("STALENESS_FRESH_HOURS", "2")
    monkeypatch.setenv("STALENESS_AGING_HOURS", "8")
    monkeypatch.setenv("STALENESS_STALE_HOURS", "48")
    get_settings.cache_clear()

    now = _now()
    # 90 min old: would be AGING at defaults, FRESH with fresh_h=2.
    assert classify_staleness(now - timedelta(minutes=90), now) is StalenessLevel.FRESH
    # 7h old: AGING under new config (was STALE at default 6h).
    assert classify_staleness(now - timedelta(hours=7), now) is StalenessLevel.AGING
    # 36h old: STALE under new config (was SUPPRESSED at default 24h).
    assert classify_staleness(now - timedelta(hours=36), now) is StalenessLevel.STALE
    # 49h old: SUPPRESSED at new 48h threshold.
    assert classify_staleness(now - timedelta(hours=49), now) is StalenessLevel.SUPPRESSED
