"""Claude CLI subprocess analyzer.

Runs the local ``claude`` CLI via ``asyncio.subprocess``. The CLI is invoked
with ``--print --output-format json`` so stdout is machine-parseable. Prompt
text is piped over stdin to avoid shell-escaping risks.

Failure modes (all wrapped as :class:`AiAnalysisError`):

* ``FileNotFoundError`` — CLI not installed → error kind: ``cli_missing``
* ``asyncio.TimeoutError`` — over ``timeout_s`` → kill process, kind: ``timeout``
* non-zero return code → stderr in message, kind: ``nonzero_exit``
* unparseable JSON / missing keys → kind: ``invalid_output``
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


class ClaudeCliAnalyzer(AiAnalysisProvider):
    def __init__(self, binary: str = "claude", model_name: str = "claude-cli") -> None:
        self._binary = binary
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return "claude_cli"

    async def analyze(self, prompt: str, *, timeout_s: float) -> AiAnalysisResult:
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                "--print",
                "--output-format",
                "json",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise AiAnalysisError(f"claude CLI not found: {exc}") from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=timeout_s,
            )
        except TimeoutError as exc:
            with _suppress_errors():
                proc.kill()
                await proc.wait()
            raise AiAnalysisError("claude CLI timed out") from exc
        except Exception as exc:  # pragma: no cover — transport errors
            logger.debug("claude CLI transport error")
            raise AiAnalysisError(f"claude CLI transport error: {exc}") from exc

        latency_ms = int((time.monotonic() - start) * 1000)
        if proc.returncode != 0:
            stderr = stderr_bytes.decode("utf-8", errors="replace")[:500]
            raise AiAnalysisError(f"claude CLI exited {proc.returncode}: {stderr}")

        raw = stdout_bytes.decode("utf-8", errors="replace")
        data = parse_provider_json(raw)
        try:
            return AiAnalysisResult(
                outlook=data.get("outlook", 0.0),
                risks=data.get("risks", 0.0),
                confidence=data.get("confidence", 0.0),
                rationale=str(data.get("rationale", "")),
                prompt_tokens=int(data.get("prompt_tokens", 0)),
                completion_tokens=int(data.get("completion_tokens", 0)),
                latency_ms=latency_ms,
                model_name=self._model_name,
            )
        except Exception as exc:
            raise AiAnalysisError(f"claude CLI output validation failed: {exc}") from exc


class _suppress_errors:
    def __enter__(self) -> _suppress_errors:
        return self

    def __exit__(self, *_: Any) -> bool:
        return True


__all__ = ["ClaudeCliAnalyzer"]
