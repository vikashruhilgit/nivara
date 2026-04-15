"""Recommendation synthesizer — weighted composite of analysis engines.

Combines the four analysis engines (technical, fundamental, sentiment, risk)
into a single action + confidence + rationale per AC #1, #2, and MODE 4.

Weight scheme (TechSpec v1.3):

    technical  0.40
    fundamental 0.25
    sentiment  0.20
    risk       0.15

Each engine is normalised to ``[-1, +1]`` before blending:

* technical already emits ``composite_score`` in ``[-1, +1]``.
* fundamental emits 0-100 → ``(score - 50) / 50``.
* sentiment already emits ``composite`` in ``[-1, +1]``.
* risk emits 0-100 where *higher = riskier* → inverted to
  ``-(score - 50) / 50`` so more risk pushes the composite bearish.

Missing engines drop out and the remaining weights are renormalised to
sum to 1.0. If no engine is available we return ``status="stale"``.

Staleness (AC #5-#8) is computed as the *maximum* age across available
engines' ``computed_at`` timestamps. The confidence penalty schedule:

* ``< 1h``    — no penalty (fresh)
* ``1-6h``   — −5 %  (aging)
* ``6-24h``  — −15 % (stale)
* ``≥ 24h``  — recommendation suppressed (``status="stale"``).

Thresholds live in :mod:`backend.app.intelligence.staleness`.

Action thresholds on the composite score (AC #2):

* ``>  0.6``       → ``strong_buy``
* ``0.3 < c ≤ 0.6``→ ``buy``
* ``-0.3 ≤ c ≤ 0.3``→ ``hold``
* ``-0.6 ≤ c < -0.3``→ ``sell``
* ``< -0.6``       → ``strong_sell``

Confidence is ``100 * (1 - mean_abs_deviation_from_composite)`` clamped to
``[0, 100]``, then reduced by the staleness penalty.

AI blending (MODE 4): lives in this module. The ``ai_score`` parameter is
a scalar in ``[-1, +1]``. In shadow mode we NEVER blend; in live mode we
take ``min(settings.ai_analysis_weight, MAX_AI_WEIGHT)`` and redistribute
proportionally from the four deterministic engines so weights still sum to
1.0. ``MAX_AI_WEIGHT = 0.30`` is a hard code constant (AC MODE 4 #5).

Subtask 7 wires the explainer + AI-weight blending here. Subtask 2 produced
the stub with ``rationale=None`` and ai_score ignored.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from backend.app.intelligence.staleness import (
    StalenessLevel,
    apply_confidence_reduction,
    classify_staleness,
)
from backend.app.schemas.recommendation import EngineScores, RecommendationResponse

if TYPE_CHECKING:
    from backend.app.analysis.risk import RiskAnalysis
    from backend.app.analysis.sentiment import SentimentResult
    from backend.app.analysis.technical import TechnicalAnalysis

logger = logging.getLogger(__name__)

WEIGHTS: dict[str, float] = {
    "technical": 0.40,
    "fundamental": 0.25,
    "sentiment": 0.20,
    "risk": 0.15,
}

MAX_AI_WEIGHT: float = 0.30

_RECOMMENDATION_TTL = timedelta(hours=24)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _normalize_fundamental(score: float | None) -> float | None:
    if score is None:
        return None
    return _clamp((score - 50.0) / 50.0, -1.0, 1.0)


def _normalize_risk(score: float | None) -> float | None:
    if score is None:
        return None
    # Higher risk → more bearish; invert before scaling.
    return _clamp(-(score - 50.0) / 50.0, -1.0, 1.0)


def _action_for(composite: float) -> str:
    if composite > 0.6:
        return "strong_buy"
    if composite > 0.3:
        return "buy"
    if composite >= -0.3:
        return "hold"
    if composite >= -0.6:
        return "sell"
    return "strong_sell"


def _top_factors(normalized: dict[str, float]) -> list[str]:
    """Human-readable labels for the top contributing engines."""
    factor_labels: dict[str, tuple[str, str]] = {
        "technical": ("technicals bullish", "technicals bearish"),
        "fundamental": ("fundamentals solid", "fundamentals weak"),
        "sentiment": ("sentiment positive", "sentiment negative"),
        "risk": ("risk favourable", "risk elevated"),
    }
    factors: list[tuple[str, float]] = [
        (
            factor_labels[k][0] if v >= 0 else factor_labels[k][1],
            abs(v),
        )
        for k, v in normalized.items()
    ]
    factors.sort(key=lambda t: t[1], reverse=True)
    return [f for f, _ in factors[:3]]


def _normalize_engines(
    *,
    technical: TechnicalAnalysis | None,
    fundamental: Any | None,
    sentiment: SentimentResult | None,
    risk: RiskAnalysis | None,
) -> dict[str, float]:
    """Normalise each engine to [-1,+1]; drop engines with no signal."""
    out: dict[str, float] = {}
    if technical is not None and technical.composite_score is not None:
        out["technical"] = _clamp(float(technical.composite_score), -1.0, 1.0)
    fund_score = getattr(fundamental, "composite_score", None) if fundamental else None
    fund_norm = _normalize_fundamental(float(fund_score) if fund_score is not None else None)
    if fund_norm is not None:
        out["fundamental"] = fund_norm
    if sentiment is not None:
        out["sentiment"] = _clamp(float(sentiment.composite), -1.0, 1.0)
    if risk is not None and risk.risk_score is not None:
        out["risk"] = _normalize_risk(float(risk.risk_score.score)) or 0.0
    return out


def _renormalize_weights(available: set[str]) -> dict[str, float]:
    total = sum(WEIGHTS[k] for k in available)
    if total <= 0:
        return {}
    return {k: WEIGHTS[k] / total for k in available}


def _blend_ai(
    *,
    det_weights: dict[str, float],
    ai_weight_cfg: float,
    shadow_mode: bool,
    ai_score: float | None,
) -> tuple[dict[str, float], float, bool]:
    """Apply MODE 4 AI blending.

    Returns ``(new_det_weights, ai_weight, ai_blended)``. In shadow mode or
    when ``ai_score`` is absent, ai_weight is 0 and det_weights are unchanged.
    """
    if shadow_mode or ai_score is None:
        return det_weights, 0.0, False
    ai_weight = max(0.0, min(ai_weight_cfg, MAX_AI_WEIGHT))
    if ai_weight <= 0.0:
        return det_weights, 0.0, False
    scale = 1.0 - ai_weight
    new_weights = {k: v * scale for k, v in det_weights.items()}
    return new_weights, ai_weight, True


async def synthesize(
    *,
    instrument_id: UUID,
    technical: TechnicalAnalysis | None,
    fundamental: Any | None,
    sentiment: SentimentResult | None,
    risk: RiskAnalysis | None,
    computed_at_per_engine: dict[str, datetime],
    now: datetime,
    ai_score: float | None = None,
    ai_weight: float = 0.0,
    shadow_mode: bool = True,
    instrument_symbol: str | None = None,
    explainer: Any | None = None,
) -> RecommendationResponse:
    """Synthesize a recommendation from engine outputs.

    ``explainer`` is an optional :class:`ExplainerProvider`; when provided,
    it is invoked inside a try/except and failures fall back to the
    deterministic template one-liner (AC #9). Leaving it as ``None`` keeps
    the synthesizer importable without the explainer package (used by some
    unit tests).
    """
    normalized = _normalize_engines(
        technical=technical,
        fundamental=fundamental,
        sentiment=sentiment,
        risk=risk,
    )
    engine_scores = EngineScores(
        technical=normalized.get("technical"),
        fundamental=normalized.get("fundamental"),
        sentiment=normalized.get("sentiment"),
        risk=normalized.get("risk"),
    )

    if not normalized:
        return RecommendationResponse(
            status="stale",
            reason="no_engine_data",
            engine_scores=engine_scores,
            computed_at=now,
            staleness=StalenessLevel.SUPPRESSED,
        )

    # Staleness gate — classify based on the oldest engine timestamp.
    available_times = [computed_at_per_engine[k] for k in normalized if k in computed_at_per_engine]
    oldest = min(available_times) if available_times else now
    staleness_level = classify_staleness(oldest, now)
    if staleness_level is StalenessLevel.SUPPRESSED:
        return RecommendationResponse(
            status="stale",
            reason="data_too_stale",
            engine_scores=engine_scores,
            computed_at=now,
            staleness=staleness_level,
        )

    det_weights = _renormalize_weights(set(normalized.keys()))
    new_det_weights, ai_w, ai_blended = _blend_ai(
        det_weights=det_weights,
        ai_weight_cfg=ai_weight,
        shadow_mode=shadow_mode,
        ai_score=ai_score,
    )
    composite = sum(new_det_weights[k] * normalized[k] for k in normalized)
    if ai_blended and ai_score is not None:
        composite += ai_w * _clamp(float(ai_score), -1.0, 1.0)
    composite = _clamp(composite, -1.0, 1.0)

    action = _action_for(composite)

    # Confidence from engine dispersion around the composite.
    abs_dev = sum(abs(v - composite) for v in normalized.values()) / max(len(normalized), 1)
    confidence_raw = 100.0 * (1.0 - min(abs_dev, 1.0))
    confidence = apply_confidence_reduction(_clamp(confidence_raw, 0.0, 100.0), staleness_level)

    top_factors = _top_factors(normalized)
    rationale: str | None = None
    explainer_used: str | None = None
    if explainer is not None:
        from backend.app.intelligence.explainers.base import RecommendationContext

        ctx = RecommendationContext(
            action=action,
            confidence=confidence,
            composite_score=composite,
            engine_scores=dict(normalized),
            top_factors=top_factors,
            instrument_symbol=instrument_symbol,
        )
        try:
            rationale = await explainer.explain(ctx)
            explainer_used = explainer.provider_name
        except Exception:  # noqa: BLE001 — explainer must never block (AC #9)
            logger.warning(
                "explainer %s failed; falling back to template",
                getattr(explainer, "provider_name", "unknown"),
                exc_info=True,
            )
            from backend.app.intelligence.explainers.template import TemplateExplainer

            try:
                fallback = TemplateExplainer()
                rationale = await fallback.explain(ctx)
                explainer_used = fallback.provider_name
            except Exception:  # pragma: no cover — pure string formatting
                rationale = f"{action.upper()} (composite {composite:.2f})"
                explainer_used = "template"

    return RecommendationResponse(
        status="ok",
        action=action,  # type: ignore[arg-type]
        confidence=confidence,
        composite_score=composite,
        engine_scores=engine_scores,
        rationale=rationale,
        expires_at=now + _RECOMMENDATION_TTL,
        computed_at=now,
        explainer_used=explainer_used,
        ai_blended=ai_blended,
        staleness=staleness_level,
    )


__all__ = [
    "MAX_AI_WEIGHT",
    "WEIGHTS",
    "synthesize",
]
