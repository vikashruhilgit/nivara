"""Deterministic f-string explainer — the always-available fallback.

This provider performs no I/O, runs in well under 10 ms, and is the ultimate
fallback when any other provider errors out (AC #3, AC #9). Output is a
single paragraph so the UI can render it without Markdown parsing.
"""

from __future__ import annotations

from backend.app.intelligence.explainers.base import (
    ExplainerProvider,
    RecommendationContext,
)


class TemplateExplainer(ExplainerProvider):
    @property
    def provider_name(self) -> str:
        return "template"

    async def explain(self, ctx: RecommendationContext) -> str:
        symbol = ctx.instrument_symbol or "the instrument"
        action = ctx.action.upper()
        confidence = ctx.confidence
        composite = ctx.composite_score
        if ctx.top_factors:
            factors = "; ".join(ctx.top_factors)
            factors_clause = f" Key factors: {factors}."
        else:
            factors_clause = ""
        return (
            f"{action} for {symbol} with confidence {confidence:.1f}% "
            f"(composite {composite:.2f}).{factors_clause}"
        )


__all__ = ["TemplateExplainer"]
