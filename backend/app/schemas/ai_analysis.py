"""Pydantic v2 schemas for AI analysis I/O (MODE 4).

Mirrors the validated shape emitted by :class:`AiAnalysisResult` for use in
API responses / admin tooling. Kept in ``schemas/`` so API-layer code can
import it without pulling the provider subprocess modules.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class AiAnalysisOutput(BaseModel):
    """Range-clamped AI output suitable for persistence and scoring."""

    outlook: float = Field(..., description="Bullish probability in [0, 1]")
    risks: float = Field(..., description="Risk level in [0, 1]")
    confidence: float = Field(..., description="Self-reported confidence in [0, 1]")
    rationale: str

    @field_validator("outlook", "risks", "confidence", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> float:
        f = float(v)
        if f != f:
            raise ValueError("NaN not permitted")
        return max(0.0, min(1.0, f))


def ai_score_from_output(outlook: float, risks: float, confidence: float) -> float:
    """Map (outlook, risks, confidence) ∈ [0, 1]^3 to [-1, +1].

    ``raw = (outlook + (1 - risks)) / 2`` weighted by ``confidence`` collapses
    to a bullishness estimate in ``[0, 1]``; we then map to ``[-1, +1]`` via
    ``2 * raw - 1``. Callers use this score as the AI leg in the synthesizer.
    """
    raw = ((outlook + (1.0 - risks)) / 2.0) * confidence
    return 2.0 * raw - 1.0


__all__ = ["AiAnalysisOutput", "ai_score_from_output"]
