"""Anthropic API analyzer.

Uses the ``anthropic`` SDK (optional dependency). Any missing SDK, missing
API key, transport error, non-JSON response, or validation failure becomes
an :class:`AiAnalysisError` so the caller can log and fall back.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from backend.app.intelligence.ai_analysis.base import (
    AiAnalysisError,
    AiAnalysisProvider,
    AiAnalysisResult,
    parse_provider_json,
)

logger = logging.getLogger(__name__)


class ApiAnalyzer(AiAnalysisProvider):
    def __init__(
        self,
        api_key: str | None,
        *,
        model: str = "claude-3-5-sonnet-latest",
        max_tokens: int = 1024,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens

    @property
    def provider_name(self) -> str:
        return "api"

    async def analyze(self, prompt: str, *, timeout_s: float) -> AiAnalysisResult:
        if not self._api_key:
            raise AiAnalysisError("anthropic api_key not configured")
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AiAnalysisError("anthropic SDK not installed") from exc

        client: Any = anthropic.AsyncAnthropic(api_key=self._api_key)
        start = time.monotonic()
        try:
            message = await asyncio.wait_for(
                client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=timeout_s,
            )
        except TimeoutError as exc:
            raise AiAnalysisError("anthropic API timed out") from exc
        except Exception as exc:
            logger.debug("anthropic API transport error")
            raise AiAnalysisError(f"anthropic API error: {exc}") from exc
        latency_ms = int((time.monotonic() - start) * 1000)

        # Extract text from the first content block.
        try:
            content_blocks = list(message.content)
            text_block = next(
                (b for b in content_blocks if getattr(b, "type", None) == "text"),
                None,
            )
            if text_block is None or not getattr(text_block, "text", None):
                raise AiAnalysisError("anthropic API returned no text content")
            text = text_block.text
        except AiAnalysisError:
            raise
        except Exception as exc:
            raise AiAnalysisError(f"anthropic API response malformed: {exc}") from exc

        data = parse_provider_json(text)
        usage = getattr(message, "usage", None)
        prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        try:
            return AiAnalysisResult(
                outlook=data.get("outlook", 0.0),
                risks=data.get("risks", 0.0),
                confidence=data.get("confidence", 0.0),
                rationale=str(data.get("rationale", "")),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                model_name=self._model,
            )
        except Exception as exc:
            raise AiAnalysisError(f"anthropic API output validation failed: {exc}") from exc


__all__ = ["ApiAnalyzer"]
