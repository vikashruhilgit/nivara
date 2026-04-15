"""Tests for the ExplainerProvider abstraction + TemplateExplainer (M3-17)."""

from __future__ import annotations

import time

import pytest
from backend.app.intelligence.explainers.base import (
    ExplainerProvider,
    RecommendationContext,
)
from backend.app.intelligence.explainers.template import TemplateExplainer


def _ctx(action: str = "buy", factors: list[str] | None = None) -> RecommendationContext:
    return RecommendationContext(
        action=action,
        confidence=82.5,
        composite_score=0.72,
        engine_scores={"technical": 0.8, "sentiment": 0.5},
        top_factors=factors
        if factors is not None
        else ["technicals bullish", "sentiment positive"],
        instrument_symbol="AAPL",
    )


def test_provider_name_is_template() -> None:
    assert TemplateExplainer().provider_name == "template"


def test_inherits_from_base() -> None:
    assert isinstance(TemplateExplainer(), ExplainerProvider)


@pytest.mark.asyncio
async def test_explain_is_deterministic() -> None:
    explainer = TemplateExplainer()
    ctx = _ctx()
    first = await explainer.explain(ctx)
    second = await explainer.explain(ctx)
    assert first == second
    assert "BUY" in first
    assert "AAPL" in first
    assert "82.5%" in first
    assert "0.72" in first
    assert "technicals bullish" in first


@pytest.mark.asyncio
async def test_explain_handles_empty_factors() -> None:
    result = await TemplateExplainer().explain(_ctx(factors=[]))
    assert "BUY" in result
    assert "Key factors" not in result


@pytest.mark.asyncio
async def test_explain_is_fast() -> None:
    """AC #3: TemplateExplainer must complete in <10ms."""
    explainer = TemplateExplainer()
    ctx = _ctx()
    # Warm up once (first call may JIT import frames).
    await explainer.explain(ctx)
    start = time.perf_counter()
    for _ in range(100):
        await explainer.explain(ctx)
    elapsed_ms = (time.perf_counter() - start) * 1000 / 100
    assert elapsed_ms < 10.0
