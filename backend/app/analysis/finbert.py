"""FinBERT sentiment inference service.

Wraps the HuggingFace ``ProsusAI/finbert`` model in an async-friendly API so
the sentiment engine can score article titles / Reddit posts without
blocking the event loop. Design choices:

* **Lazy load.** The model (~400MB) is only materialised on the first call
  via a module-scoped singleton guarded by an :class:`asyncio.Lock`. Tests
  inject a fake pipeline via :func:`set_pipeline` and never pay the cost.
* **CPU only.** The MVP deliberately avoids GPU. We pin ``device=-1`` so
  ``transformers`` doesn't probe for CUDA.
* **Sync-wrapped-in-thread.** ``transformers`` pipelines are synchronous;
  we run them via :func:`asyncio.to_thread` to preserve the async contract.
* **Redis caching.** Scored texts are cached by SHA-256 of the text, keyed
  under ``analysis:finbert:sentiment:{hash}`` with a 24h TTL. Repeat
  scoring is free; storage is tiny (one float per entry).

Scoring contract
----------------
FinBERT's raw output is a distribution over ``{positive, negative, neutral}``.
We collapse that into a scalar in ``[-1, +1]`` as ``positive - negative``,
which is the same convention used by the scoring engine. Neutral
probability never enters the score directly — it simply dampens the
magnitude, which is the desired behaviour for "mild" headlines.

Graceful degradation
--------------------
If ``transformers`` / ``torch`` are not installed (possible in minimal dev
environments), calls raise :class:`FinBertUnavailable`. The sentiment
engine treats this as a neutral score rather than a hard failure so the
service keeps returning composite scores even on thin deployments.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import TYPE_CHECKING, Any, Protocol

from redis.asyncio import Redis

if TYPE_CHECKING:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)

FINBERT_MODEL_NAME = "ProsusAI/finbert"
FINBERT_CACHE_TTL_SECONDS = 24 * 60 * 60
FINBERT_CACHE_PREFIX = "analysis:finbert:sentiment:"


class FinBertUnavailable(Exception):
    """FinBERT could not be loaded (missing deps or model fetch failure)."""


class _PipelineLike(Protocol):
    """Minimal shape of a transformers text-classification pipeline.

    We accept any callable returning ``list[list[{"label", "score"}]]``
    (top_k=None default) *or* ``list[{"label", "score"}]`` (top_k=1). The
    conversion helper :func:`_flatten_prediction` handles both.
    """

    def __call__(self, inputs: list[str], **kwargs: Any) -> Any: ...


# Module-level pipeline singleton. Tests inject via :func:`set_pipeline`.
_pipeline: _PipelineLike | None = None
_pipeline_lock: asyncio.Lock = asyncio.Lock()


def set_pipeline(pipeline: _PipelineLike | None) -> None:
    """Replace (or clear) the cached pipeline — used only by tests."""
    global _pipeline
    _pipeline = pipeline


async def _get_pipeline() -> _PipelineLike:
    """Return the shared pipeline, loading it on first use."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    async with _pipeline_lock:
        if _pipeline is not None:
            return _pipeline
        _pipeline = await asyncio.to_thread(_load_pipeline)
        return _pipeline


def _load_pipeline() -> _PipelineLike:
    """Synchronous, CPU-bound load — always called via ``asyncio.to_thread``."""
    try:
        from transformers import pipeline
    except ImportError as exc:
        raise FinBertUnavailable(
            "transformers / torch not installed; install with "
            "`pip install transformers torch --index-url "
            "https://download.pytorch.org/whl/cpu`"
        ) from exc
    try:
        # device=-1 forces CPU; return_all_scores is deprecated so we use top_k=None.
        # Assign to a typed local rather than `return pipeline(...)`: when
        # transformers is installed its return type is concrete (no ignore
        # needed); when it isn't (e.g. the pre-commit mypy env) the value is
        # Any, and the annotation keeps mypy --strict from flagging no-any-return.
        pipe: _PipelineLike = pipeline(
            "text-classification",
            model=FINBERT_MODEL_NAME,
            device=-1,
            top_k=None,
        )
        return pipe
    except Exception as exc:  # noqa: BLE001
        raise FinBertUnavailable(f"FinBERT load failed: {exc}") from exc


# ---- Public API ------------------------------------------------------------


def _cache_key(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{FINBERT_CACHE_PREFIX}{digest}"


def _flatten_prediction(raw: Any) -> list[dict[str, Any]]:
    """Normalise transformers output to ``[{"label", "score"}, ...]``.

    Handles both the legacy ``return_all_scores`` shape (``[[{...}]]``) and
    the single-best shape (``[{...}]``).
    """
    if not raw:
        return []
    first = raw[0]
    if isinstance(first, list):
        return [d for d in first if isinstance(d, dict)]
    if isinstance(first, dict):
        return [d for d in raw if isinstance(d, dict)]
    return []


def _scalar_from_labels(labels: list[dict[str, Any]]) -> float:
    """Collapse label-score dict list into a ``[-1, +1]`` scalar.

    positive - negative; neutral is ignored (its mass dampens magnitude).
    Unknown labels are skipped so a future model release with different
    labelling never crashes the scorer.
    """
    pos = 0.0
    neg = 0.0
    for entry in labels:
        label = str(entry.get("label", "")).lower()
        try:
            score = float(entry.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        if label == "positive":
            pos = score
        elif label == "negative":
            neg = score
    score_scalar = pos - neg
    # Numerical clamp in case the model outputs slightly out-of-range values.
    return max(-1.0, min(1.0, score_scalar))


async def score_text(text: str, *, redis: Redis | None = None) -> float:
    """Return the sentiment scalar (``-1..+1``) for a single text.

    Uses Redis cache when supplied. Raises :class:`FinBertUnavailable` when
    transformers/torch are missing or the model fails to load.
    """
    text = (text or "").strip()
    if not text:
        return 0.0
    if redis is not None:
        cached_raw: Any = await redis.get(_cache_key(text))
        if cached_raw is not None:
            try:
                return float(cached_raw)
            except (TypeError, ValueError):
                pass  # corrupt cache — fall through to re-score

    pipeline = await _get_pipeline()
    prediction = await asyncio.to_thread(lambda: pipeline([text]))
    scalar = _scalar_from_labels(_flatten_prediction(prediction))

    if redis is not None:
        await redis.set(_cache_key(text), f"{scalar:.6f}", ex=FINBERT_CACHE_TTL_SECONDS)
    return scalar


async def score_batch(texts: list[str], *, redis: Redis | None = None) -> list[float]:
    """Score a batch of texts, using Redis cache on a per-text basis.

    Ordering is preserved. Empty or whitespace-only texts score 0.0.
    """
    if not texts:
        return []

    # First pass — collect cache hits and build the list of texts we still
    # need to actually run through FinBERT. Preserve input order via indices.
    results: list[float | None] = [None] * len(texts)
    to_score: list[tuple[int, str]] = []
    for idx, raw in enumerate(texts):
        text = (raw or "").strip()
        if not text:
            results[idx] = 0.0
            continue
        if redis is not None:
            cached_raw: Any = await redis.get(_cache_key(text))
            if cached_raw is not None:
                try:
                    results[idx] = float(cached_raw)
                    continue
                except (TypeError, ValueError):
                    pass
        to_score.append((idx, text))

    if to_score:
        pipeline = await _get_pipeline()
        batch_texts = [t for _, t in to_score]
        prediction = await asyncio.to_thread(lambda: pipeline(batch_texts))
        # transformers returns a parallel list to the batch input.
        for (idx, text), per_item in zip(to_score, prediction, strict=True):
            # Each per_item is either a list-of-dicts or a single dict list.
            labels = _flatten_prediction([per_item])
            scalar = _scalar_from_labels(labels)
            results[idx] = scalar
            if redis is not None:
                await redis.set(_cache_key(text), f"{scalar:.6f}", ex=FINBERT_CACHE_TTL_SECONDS)

    # Any slot still None indicates a logic error above — coerce to 0.0
    # defensively so callers never see None.
    return [(r if r is not None else 0.0) for r in results]


__all__ = [
    "FINBERT_CACHE_PREFIX",
    "FINBERT_CACHE_TTL_SECONDS",
    "FINBERT_MODEL_NAME",
    "FinBertUnavailable",
    "score_batch",
    "score_text",
    "set_pipeline",
]
