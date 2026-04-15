"""Shadow-mode runner for AI analysis.

Called from the ``tasks.ai_analysis.run`` Celery task after a user requests
a recommendation. Contract:

* Sanitize the incoming prompt (defence-in-depth — the caller should have
  already scrubbed PII but we redact again here).
* Invoke the provider with a hard timeout.
* Persist the outcome to ``ai_analysis_log`` — always, even on failure —
  with ``shadow_mode=settings.ai_analysis_shadow_mode``.
* DB write failures are swallowed with a warning (MODE 4 AC #7): the AI
  result is dropped and the recommendation proceeds with traditional scoring.
* Never raise — all exceptions are logged and converted to ``None`` return
  so the Celery task never marks itself ``FAILURE`` on provider issues.
"""

from __future__ import annotations

import contextlib
import logging
from decimal import Decimal
from uuid import UUID

from backend.app.intelligence.ai_analysis.base import (
    AiAnalysisError,
    AiAnalysisProvider,
    AiAnalysisResult,
)
from backend.app.intelligence.ai_analysis.sanitizer import redact_pii, sanitize_prompt
from backend.app.models.ai_analysis_log import AiAnalysisLog
from backend.app.schemas.ai_analysis import ai_score_from_output
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def run_shadow_analysis(
    *,
    db: AsyncSession,
    instrument_id: UUID | None,
    prompt: str,
    provider: AiAnalysisProvider,
    request_type: str,
    timeout_s: float,
    shadow_mode: bool,
) -> AiAnalysisResult | None:
    """Run provider + persist telemetry. Returns ``None`` on any failure."""
    cleaned = redact_pii(sanitize_prompt(prompt))

    result: AiAnalysisResult | None = None
    status: str = "success"
    error_message: str | None = None
    latency_ms: int = 0
    model_name = provider.provider_name
    result_dict: dict[str, object] | None = None
    ai_score: Decimal | None = None

    try:
        result = await provider.analyze(cleaned, timeout_s=timeout_s)
        latency_ms = result.latency_ms
        model_name = result.model_name
        result_dict = result.model_dump(mode="json")
        raw_score = ai_score_from_output(
            outlook=result.outlook,
            risks=result.risks,
            confidence=result.confidence,
        )
        ai_score = Decimal(f"{raw_score:.4f}")
    except AiAnalysisError as exc:
        status = "timeout" if "timed out" in str(exc).lower() else "error"
        error_message = str(exc)[:500]
        logger.warning("ai_analysis %s: %s", provider.provider_name, error_message)
    except Exception as exc:  # defensive — never let an AI failure propagate
        status = "error"
        error_message = f"unexpected: {exc}"[:500]
        logger.exception("ai_analysis %s unexpected failure", provider.provider_name)

    row = AiAnalysisLog(
        request_type=request_type,
        model_name=model_name,
        prompt_tokens=result.prompt_tokens if result else 0,
        completion_tokens=result.completion_tokens if result else 0,
        latency_ms=latency_ms,
        status=status,
        error_message=error_message,
        shadow_mode=shadow_mode,
        instrument_id=instrument_id,
        result_json=result_dict,
        ai_score=ai_score,
    )
    try:
        db.add(row)
        await db.commit()
    except Exception:  # MODE 4 AC #7: swallow DB write failures
        logger.warning("ai_analysis_log write failed; discarding result", exc_info=True)
        with contextlib.suppress(Exception):  # pragma: no cover
            await db.rollback()
        return None

    # In shadow mode the caller ignores the returned result (logging only).
    return result if status == "success" else None


__all__ = ["run_shadow_analysis"]
