"""Recommendation API routes (M3-17).

Two endpoints:

* ``GET  /api/recommendations`` — list the current user's active (non-expired)
  recommendations.
* ``POST /api/recommendations/generate`` — synthesize a fresh recommendation
  for an instrument using the four analysis engines. When
  ``AI_ANALYSIS_ENABLED`` is true, a Celery task is dispatched in the
  ``ai_analysis`` queue (fire-and-forget) for shadow-mode logging. Live-mode
  blending is disabled in production unless
  ``AI_ANALYSIS_LEGAL_REVIEW_APPROVED`` is also true (MODE 4 AC #2).

Engine loading is best-effort: if any engine fails (no OHLCV, no
fundamentals, etc.) that engine is dropped from the composite and the
remaining weights are renormalised by the synthesizer.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from backend.app.analysis.technical import analyze_technical, load_ohlcv_from_db
from backend.app.auth.dependencies import get_current_user
from backend.app.config import Settings, get_settings
from backend.app.db import get_session
from backend.app.intelligence.explainers.template import TemplateExplainer
from backend.app.intelligence.synthesizer import synthesize
from backend.app.models.audit_log import AuditLog
from backend.app.models.instruments import Instrument
from backend.app.models.recommendations import Recommendation
from backend.app.models.users import User
from backend.app.schemas.recommendation import (
    RecommendationRequest,
    RecommendationResponse,
)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from backend.app.analysis.risk import RiskAnalysis
    from backend.app.analysis.sentiment import SentimentResult
    from backend.app.analysis.technical import TechnicalAnalysis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


def _resolve_shadow_mode(settings: Settings) -> bool:
    """Production hard-gate: force shadow on unless legal-review flag is set.

    MODE 4 AC #2 — we refuse to run live blending in production without an
    explicit human-approved legal-review flag.
    """
    if (
        settings.environment == "production"
        and not settings.ai_analysis_shadow_mode
        and not settings.ai_analysis_legal_review_approved
    ):
        logger.warning(
            "ai_analysis_shadow_mode=false rejected in production without legal review; forcing shadow"
        )
        return True
    return settings.ai_analysis_shadow_mode


async def _load_technical(
    db: AsyncSession, instrument_id: Instrument
) -> tuple[TechnicalAnalysis | None, datetime | None]:
    try:
        ohlcv = await load_ohlcv_from_db(db, instrument_id.id)
        if ohlcv.empty:
            return None, None
        return analyze_technical(ohlcv), datetime.now(UTC)
    except Exception:  # noqa: BLE001 — engines must degrade gracefully
        logger.warning("technical engine failed for %s", instrument_id.symbol, exc_info=True)
        return None, None


@router.get("", response_model=list[dict[str, object]])
async def list_recommendations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return all non-expired recommendations for the authenticated user."""
    now = datetime.now(UTC)
    stmt = (
        select(Recommendation)
        .where(Recommendation.user_id == current_user.id)
        .where(Recommendation.expires_at > now)
        .order_by(Recommendation.created_at.desc())
    )
    rows = list((await db.execute(stmt)).scalars())
    return [
        {
            "id": str(r.id),
            "instrument_id": str(r.instrument_id),
            "recommendation_type": r.recommendation_type,
            "rationale": r.rationale,
            "confidence_score": float(r.confidence_score),
            "expires_at": r.expires_at.isoformat(),
            "status": r.status,
        }
        for r in rows
    ]


@router.post("/generate", response_model=RecommendationResponse)
async def generate_recommendation(
    req: RecommendationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RecommendationResponse:
    instrument = await db.get(Instrument, req.instrument_id)
    if instrument is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="instrument not found")

    now = datetime.now(UTC)
    technical, tech_ts = await _load_technical(db, instrument)
    # Fundamental / sentiment / risk are expensive to compute synchronously
    # here and each has its own loader in ``backend.app.api.analysis``. The
    # MVP recommendation endpoint runs ONLY the technical engine inline; the
    # remaining engines are wired in a follow-up job when a joint loader
    # service exists. The synthesizer already handles missing engines by
    # renormalising weights.
    fundamental = None
    sentiment: SentimentResult | None = None
    risk: RiskAnalysis | None = None

    computed_at: dict[str, datetime] = {}
    if tech_ts is not None:
        computed_at["technical"] = tech_ts

    shadow_mode = _resolve_shadow_mode(settings)

    # AI shadow-mode: dispatch fire-and-forget Celery task when enabled.
    if settings.ai_analysis_enabled:
        try:
            from backend.app.tasks.ai_analysis import run as ai_run

            prompt = (
                f"Analyse investment outlook for {instrument.symbol} on {instrument.exchange}. "
                "Respond as JSON with keys outlook, risks, confidence (all in [0, 1]) and rationale."
            )
            ai_run.delay(str(instrument.id), prompt, "recommendation")
        except Exception:  # noqa: BLE001
            logger.warning("ai_analysis task dispatch failed", exc_info=True)

    response = await synthesize(
        instrument_id=instrument.id,
        technical=technical,
        fundamental=fundamental,
        sentiment=sentiment,
        risk=risk,
        computed_at_per_engine=computed_at,
        now=now,
        ai_score=None,  # shadow mode — no live blending
        ai_weight=settings.ai_analysis_weight,
        shadow_mode=shadow_mode,
        instrument_symbol=instrument.symbol,
        explainer=TemplateExplainer(),
    )

    # Persist only successful (non-stale) recommendations.
    if response.status == "ok" and response.action is not None and response.expires_at is not None:
        rec = Recommendation(
            user_id=current_user.id,
            instrument_id=instrument.id,
            recommendation_type=response.action,
            rationale=response.rationale or "",
            confidence_score=Decimal(f"{response.confidence or 0.0:.2f}"),
            expires_at=response.expires_at,
            status="pending",
        )
        db.add(rec)

        # Audit log — AC #10.
        db.add(
            AuditLog(
                user_id=current_user.id,
                event_type="recommendation_generated",
                event_data={
                    "instrument_id": str(instrument.id),
                    "action": response.action,
                    "confidence": response.confidence,
                    "composite_score": response.composite_score,
                    "explainer_used": response.explainer_used,
                    "ai_blended": response.ai_blended,
                    "shadow_mode": shadow_mode,
                },
            )
        )
        await db.commit()

    return response


__all__ = ["router"]
