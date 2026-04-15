"""Celery task entry point for AI analysis (MODE 4).

The task is fire-and-forget from the API endpoint: it never blocks
recommendation generation. Inside the task we build an async loop,
construct the configured provider, and delegate to ``run_shadow_analysis``
which handles sanitization, invocation, and telemetry persistence.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from backend.app.celery_app import celery_app
from backend.app.config import get_settings
from backend.app.db import _session_factory
from backend.app.intelligence.ai_analysis.api import ApiAnalyzer
from backend.app.intelligence.ai_analysis.base import AiAnalysisProvider
from backend.app.intelligence.ai_analysis.claude_cli import ClaudeCliAnalyzer
from backend.app.intelligence.ai_analysis.shadow import run_shadow_analysis

logger = logging.getLogger(__name__)


def _build_provider() -> AiAnalysisProvider:
    settings = get_settings()
    if settings.ai_analysis_provider == "api":
        return ApiAnalyzer(api_key=settings.anthropic_api_key)
    return ClaudeCliAnalyzer()


async def _run_async(instrument_id: str | None, prompt: str, request_type: str) -> None:
    settings = get_settings()
    provider = _build_provider()
    factory = _session_factory()
    async with factory() as session:
        await run_shadow_analysis(
            db=session,
            instrument_id=UUID(instrument_id) if instrument_id else None,
            prompt=prompt,
            provider=provider,
            request_type=request_type,
            timeout_s=settings.ai_analysis_timeout_s,
            shadow_mode=settings.ai_analysis_shadow_mode,
        )


@celery_app.task(name="tasks.ai_analysis.run", queue="ai_analysis")  # type: ignore[untyped-decorator]
def run(instrument_id: str | None, prompt: str, request_type: str = "recommendation") -> None:
    """Entry point registered with Celery. Synchronous wrapper over async impl."""
    try:
        asyncio.run(_run_async(instrument_id, prompt, request_type))
    except Exception:  # pragma: no cover — defensive; never let the task crash
        logger.exception("ai_analysis task failed")


__all__ = ["run"]
