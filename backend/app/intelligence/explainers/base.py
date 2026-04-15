"""Explainer provider abstraction.

An :class:`ExplainerProvider` converts a :class:`RecommendationContext` —
the already-synthesized action/confidence/factor bundle — into human-readable
rationale text. Providers must never block the recommendation pipeline:
callers wrap every explainer call in a try/except and fall back to the
deterministic :class:`~backend.app.intelligence.explainers.template.TemplateExplainer`
on any failure (AC #9).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RecommendationContext:
    """Minimal inputs an explainer needs.

    All engine scores are already normalised to ``[-1, +1]``; the composite
    is the weighted blend the synthesizer produced. ``top_factors`` is a
    short human-readable list (e.g. ``["technicals bullish", "sentiment positive"]``)
    that the synthesizer pre-computes so explainers do not repeat that work.
    """

    action: str
    confidence: float
    composite_score: float
    engine_scores: dict[str, float]
    top_factors: list[str] = field(default_factory=list)
    instrument_symbol: str | None = None


class ExplainerProvider(ABC):
    """Abstract explainer. Subclasses must be safe to call concurrently."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short identifier used by audit logging (``template|claude_cli|api``)."""

    @abstractmethod
    async def explain(self, ctx: RecommendationContext) -> str:
        """Render a single-paragraph rationale from ``ctx``."""


__all__ = ["ExplainerProvider", "RecommendationContext"]
