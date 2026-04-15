"""AI analysis provider base class + result schema.

Providers must implement :meth:`AiAnalysisProvider.analyze` and may raise
:class:`AiAnalysisError` for *any* failure (timeout, malformed output,
network error, SDK missing). Callers swallow the error and proceed with the
deterministic-only recommendation per MODE 4 AC #6.

Output validation (MODE 4 AC #3, #4) is baked into :class:`AiAnalysisResult`
via field validators: ``outlook``/``risks``/``confidence`` clamp to
``[0.0, 1.0]`` so providers cannot emit out-of-range values.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AiAnalysisError(Exception):
    """Any AI-analysis failure (timeout, parse error, auth, transport)."""


class AiAnalysisResult(BaseModel):
    """Validated provider output + telemetry for ``ai_analysis_log``."""

    outlook: float = Field(..., description="Bullish probability in [0, 1]")
    risks: float = Field(..., description="Risk level in [0, 1]")
    confidence: float = Field(..., description="Self-reported confidence in [0, 1]")
    rationale: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int
    model_name: str

    @field_validator("outlook", "risks", "confidence", mode="before")
    @classmethod
    def _clamp_unit_interval(cls, v: Any) -> float:
        f = float(v)
        if f != f:  # NaN guard
            raise ValueError("NaN not permitted")
        return max(0.0, min(1.0, f))


def parse_provider_json(raw: str) -> dict[str, Any]:
    """Parse provider stdout into a dict, tolerating CLI wrappers.

    Accepts either a bare JSON object with ``{outlook, risks, confidence,
    rationale}``, or a wrapper like ``{"result": "<json>"}`` (claude CLI's
    ``--output-format json`` emits the latter with the text inside ``result``).
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AiAnalysisError(f"invalid JSON from provider: {exc}") from exc
    if isinstance(data, dict) and "outlook" in data:
        return data
    if isinstance(data, dict) and isinstance(data.get("result"), str):
        try:
            inner = json.loads(data["result"])
        except json.JSONDecodeError as exc:
            raise AiAnalysisError(f"invalid JSON in result wrapper: {exc}") from exc
        if isinstance(inner, dict):
            return inner
    raise AiAnalysisError("provider JSON missing required keys")


class AiAnalysisProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short identifier (``claude_cli|api``) used by audit + ai_analysis_log."""

    @abstractmethod
    async def analyze(self, prompt: str, *, timeout_s: float) -> AiAnalysisResult:
        """Run the analysis; raise :class:`AiAnalysisError` on any failure."""


__all__ = [
    "AiAnalysisError",
    "AiAnalysisProvider",
    "AiAnalysisResult",
    "parse_provider_json",
]
