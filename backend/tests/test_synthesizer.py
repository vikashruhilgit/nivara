"""Tests for the recommendation synthesizer (M3-17)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from backend.app.intelligence.explainers.template import TemplateExplainer
from backend.app.intelligence.staleness import StalenessLevel
from backend.app.intelligence.synthesizer import MAX_AI_WEIGHT, synthesize


@dataclass
class _Technical:
    composite_score: float | None


@dataclass
class _Fundamental:
    composite_score: float | None


@dataclass
class _Sentiment:
    composite: float


@dataclass
class _RiskScore:
    score: int


@dataclass
class _Risk:
    risk_score: _RiskScore


def _fresh_timestamps(now: datetime) -> dict[str, datetime]:
    return dict.fromkeys(("technical", "fundamental", "sentiment", "risk"), now)


@pytest.mark.asyncio
async def test_strong_buy_threshold() -> None:
    now = datetime.now(UTC)
    out = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.9),
        fundamental=_Fundamental(composite_score=90),
        sentiment=_Sentiment(composite=0.9),
        risk=_Risk(risk_score=_RiskScore(score=10)),  # low risk → bullish
        computed_at_per_engine=_fresh_timestamps(now),
        now=now,
    )
    assert out.status == "ok"
    assert out.action == "strong_buy"
    assert out.composite_score is not None and out.composite_score > 0.6
    assert out.confidence is not None and out.confidence > 0


@pytest.mark.asyncio
async def test_strong_sell_threshold() -> None:
    now = datetime.now(UTC)
    out = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=-0.9),
        fundamental=_Fundamental(composite_score=10),
        sentiment=_Sentiment(composite=-0.9),
        risk=_Risk(risk_score=_RiskScore(score=90)),
        computed_at_per_engine=_fresh_timestamps(now),
        now=now,
    )
    assert out.action == "strong_sell"
    assert out.composite_score is not None and out.composite_score < -0.6


@pytest.mark.asyncio
async def test_hold_when_neutral() -> None:
    now = datetime.now(UTC)
    out = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.0),
        fundamental=_Fundamental(composite_score=50),
        sentiment=_Sentiment(composite=0.0),
        risk=_Risk(risk_score=_RiskScore(score=50)),
        computed_at_per_engine=_fresh_timestamps(now),
        now=now,
    )
    assert out.action == "hold"


@pytest.mark.asyncio
async def test_stale_between_1_and_4h_reduces_confidence_by_5() -> None:
    now = datetime.now(UTC)
    stale = now - timedelta(hours=2)
    out_fresh = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.8),
        fundamental=None,
        sentiment=None,
        risk=None,
        computed_at_per_engine={"technical": now},
        now=now,
    )
    out_stale = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.8),
        fundamental=None,
        sentiment=None,
        risk=None,
        computed_at_per_engine={"technical": stale},
        now=now,
    )
    assert out_fresh.confidence is not None and out_stale.confidence is not None
    assert abs((out_fresh.confidence - out_stale.confidence) - 5.0) < 1e-6


@pytest.mark.asyncio
async def test_very_stale_data_suppresses_recommendation() -> None:
    now = datetime.now(UTC)
    stale = now - timedelta(hours=30)
    out = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.8),
        fundamental=None,
        sentiment=None,
        risk=None,
        computed_at_per_engine={"technical": stale},
        now=now,
    )
    assert out.status == "stale"
    assert out.action is None
    assert out.reason == "data_too_stale"


@pytest.mark.asyncio
async def test_no_engines_returns_stale() -> None:
    now = datetime.now(UTC)
    out = await synthesize(
        instrument_id=uuid4(),
        technical=None,
        fundamental=None,
        sentiment=None,
        risk=None,
        computed_at_per_engine={},
        now=now,
    )
    assert out.status == "stale"
    assert out.reason == "no_engine_data"
    # no_engine_data path: staleness is not meaningful (there's no data to age)
    # so the field should be None, not SUPPRESSED.
    assert out.staleness is None


# ------------------------------------------------------------- staleness bands


@pytest.mark.asyncio
async def test_aging_engines_reduce_confidence_by_5() -> None:
    """3h-old engines → AGING band, ~5pp confidence reduction."""
    now = datetime.now(UTC)
    aging = now - timedelta(hours=3)
    fresh_out = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.5),
        fundamental=None,
        sentiment=None,
        risk=None,
        computed_at_per_engine={"technical": now},
        now=now,
    )
    aging_out = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.5),
        fundamental=None,
        sentiment=None,
        risk=None,
        computed_at_per_engine={"technical": aging},
        now=now,
    )
    assert aging_out.staleness is StalenessLevel.AGING
    assert fresh_out.confidence is not None and aging_out.confidence is not None
    assert abs((fresh_out.confidence - aging_out.confidence) - 5.0) < 1e-6


@pytest.mark.asyncio
async def test_stale_engines_reduce_confidence_by_15() -> None:
    """12h-old engines → STALE band, ~15pp confidence reduction."""
    now = datetime.now(UTC)
    stale = now - timedelta(hours=12)
    fresh_out = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.5),
        fundamental=None,
        sentiment=None,
        risk=None,
        computed_at_per_engine={"technical": now},
        now=now,
    )
    stale_out = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.5),
        fundamental=None,
        sentiment=None,
        risk=None,
        computed_at_per_engine={"technical": stale},
        now=now,
    )
    assert stale_out.staleness is StalenessLevel.STALE
    assert fresh_out.confidence is not None and stale_out.confidence is not None
    assert abs((fresh_out.confidence - stale_out.confidence) - 15.0) < 1e-6


@pytest.mark.asyncio
async def test_suppressed_engines_hide_recommendation() -> None:
    """25h-old engines → SUPPRESSED band, status=stale, reason=data_too_stale."""
    now = datetime.now(UTC)
    too_stale = now - timedelta(hours=25)
    out = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.8),
        fundamental=None,
        sentiment=None,
        risk=None,
        computed_at_per_engine={"technical": too_stale},
        now=now,
    )
    assert out.status == "stale"
    assert out.reason == "data_too_stale"
    assert out.staleness is StalenessLevel.SUPPRESSED
    assert out.action is None


@pytest.mark.asyncio
async def test_explainer_wired_when_passed() -> None:
    now = datetime.now(UTC)
    out = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.8),
        fundamental=None,
        sentiment=None,
        risk=None,
        computed_at_per_engine={"technical": now},
        now=now,
        explainer=TemplateExplainer(),
        instrument_symbol="AAPL",
    )
    assert out.rationale is not None
    assert "AAPL" in out.rationale
    assert out.explainer_used == "template"


@pytest.mark.asyncio
async def test_explainer_failure_falls_back_to_template() -> None:
    """AC #9: any explainer failure must fall back; recommendation not blocked."""

    class _Broken(TemplateExplainer):
        @property
        def provider_name(self) -> str:
            return "broken"

        async def explain(self, ctx):  # type: ignore[override]
            raise RuntimeError("boom")

    now = datetime.now(UTC)
    out = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.8),
        fundamental=None,
        sentiment=None,
        risk=None,
        computed_at_per_engine={"technical": now},
        now=now,
        explainer=_Broken(),
        instrument_symbol="AAPL",
    )
    assert out.status == "ok"
    assert out.rationale is not None
    assert out.explainer_used == "template"  # fell back


@pytest.mark.asyncio
async def test_shadow_mode_does_not_blend_ai() -> None:
    now = datetime.now(UTC)
    out = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.1),
        fundamental=None,
        sentiment=None,
        risk=None,
        computed_at_per_engine={"technical": now},
        now=now,
        ai_score=0.9,  # would otherwise push bullish
        ai_weight=0.3,
        shadow_mode=True,
    )
    assert out.ai_blended is False
    # Composite equals the deterministic-only value.
    assert out.composite_score == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_live_mode_caps_ai_weight() -> None:
    now = datetime.now(UTC)
    # Request 0.5 weight but MAX_AI_WEIGHT=0.30 should cap it.
    out = await synthesize(
        instrument_id=uuid4(),
        technical=_Technical(composite_score=0.0),
        fundamental=None,
        sentiment=None,
        risk=None,
        computed_at_per_engine={"technical": now},
        now=now,
        ai_score=1.0,
        ai_weight=0.5,
        shadow_mode=False,
    )
    assert out.ai_blended is True
    # With det=0 and ai=1.0 and ai_weight capped at 0.30 → composite = 0.30.
    assert out.composite_score == pytest.approx(MAX_AI_WEIGHT, abs=1e-6)
