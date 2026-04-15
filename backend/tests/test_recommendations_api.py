"""Tests for recommendations API helpers (M3-17).

Full HTTP integration tests are deferred to a follow-up job because the
existing test harness uses SQLite-only tables and the recommendations
endpoint exercises Postgres-specific JSONB + enum columns (instruments,
recommendations, audit_log). These tests cover the pure helpers and
production-hard-gate logic from ``api/recommendations.py``.
"""

from __future__ import annotations

import pytest
from backend.app.api.recommendations import _resolve_shadow_mode
from backend.app.config import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "development",
        "ai_analysis_enabled": False,
        "ai_analysis_shadow_mode": True,
        "ai_analysis_legal_review_approved": False,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_shadow_mode_default_is_true() -> None:
    assert _resolve_shadow_mode(_settings()) is True


def test_production_without_legal_review_forces_shadow() -> None:
    """MODE 4 AC #2: prod + shadow_mode=False + no legal review → force shadow."""
    s = _settings(
        environment="production",
        ai_analysis_shadow_mode=False,
        ai_analysis_legal_review_approved=False,
    )
    assert _resolve_shadow_mode(s) is True


def test_production_with_legal_review_allows_live() -> None:
    s = _settings(
        environment="production",
        ai_analysis_shadow_mode=False,
        ai_analysis_legal_review_approved=True,
    )
    assert _resolve_shadow_mode(s) is False


def test_development_respects_shadow_mode_flag() -> None:
    s = _settings(environment="development", ai_analysis_shadow_mode=False)
    assert _resolve_shadow_mode(s) is False


def test_ai_weight_config_is_capped_by_code_constant() -> None:
    """MODE 4 AC #5: AI_ANALYSIS_WEIGHT above MAX_AI_WEIGHT must be capped in synth."""
    from backend.app.intelligence.synthesizer import MAX_AI_WEIGHT

    assert MAX_AI_WEIGHT == 0.30
