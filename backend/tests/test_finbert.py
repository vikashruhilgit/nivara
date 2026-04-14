"""Tests for :mod:`backend.app.analysis.finbert`.

We never load the real ``ProsusAI/finbert`` model in CI — that's a ~400MB
download. Instead we inject a fake pipeline via :func:`set_pipeline` so the
scoring logic is exercised without touching HuggingFace.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import fakeredis.aioredis
import pytest
import pytest_asyncio
from backend.app.analysis.finbert import (
    _cache_key,
    _flatten_prediction,
    _scalar_from_labels,
    score_batch,
    score_text,
    set_pipeline,
)


class _FakePipeline:
    """Deterministic stand-in for ``transformers.pipeline(...)`` output.

    The real pipeline returns ``[[{"label", "score"}, ...], ...]`` when
    ``top_k=None``; we honour that shape. A dict ``per_text`` lets callers
    hard-code results by input string.
    """

    def __init__(self, per_text: dict[str, list[dict[str, Any]]]) -> None:
        self._per_text = per_text
        self.calls: int = 0

    def __call__(self, inputs: list[str], **kwargs: Any) -> list[list[dict[str, Any]]]:
        self.calls += 1
        out: list[list[dict[str, Any]]] = []
        for text in inputs:
            out.append(
                self._per_text.get(
                    text,
                    [
                        {"label": "neutral", "score": 1.0},
                        {"label": "positive", "score": 0.0},
                        {"label": "negative", "score": 0.0},
                    ],
                )
            )
        return out


@pytest_asyncio.fixture
async def redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture(autouse=True)
def _reset_pipeline() -> None:
    set_pipeline(None)
    yield
    set_pipeline(None)


def test_scalar_from_labels_collapses_to_pos_minus_neg() -> None:
    scalar = _scalar_from_labels(
        [
            {"label": "positive", "score": 0.8},
            {"label": "negative", "score": 0.1},
            {"label": "neutral", "score": 0.1},
        ]
    )
    # 0.8 - 0.1 = 0.7
    assert scalar == pytest.approx(0.7)


def test_scalar_from_labels_clamps_to_unit_range() -> None:
    # Defensive: shouldn't happen, but verify the clamp.
    scalar = _scalar_from_labels(
        [
            {"label": "positive", "score": 1.5},
            {"label": "negative", "score": 0.0},
        ]
    )
    assert scalar == 1.0


def test_flatten_prediction_handles_both_shapes() -> None:
    # top_k=None shape (list-of-lists).
    shape_a = [[{"label": "positive", "score": 0.6}]]
    # top_k=1 shape (flat list of dicts).
    shape_b = [{"label": "positive", "score": 0.6}]
    assert _flatten_prediction(shape_a)[0]["label"] == "positive"
    assert _flatten_prediction(shape_b)[0]["label"] == "positive"


async def test_score_text_uses_pipeline(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    fake = _FakePipeline(
        {
            "Great quarter for AAPL": [
                {"label": "positive", "score": 0.9},
                {"label": "negative", "score": 0.05},
                {"label": "neutral", "score": 0.05},
            ]
        }
    )
    set_pipeline(fake)
    result = await score_text("Great quarter for AAPL", redis=redis)
    assert result == pytest.approx(0.85)


async def test_score_text_empty_returns_zero() -> None:
    assert await score_text("") == 0.0
    assert await score_text("   ") == 0.0


async def test_score_text_uses_cache_on_second_call(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    fake = _FakePipeline(
        {
            "Cached headline": [
                {"label": "positive", "score": 0.7},
                {"label": "negative", "score": 0.0},
                {"label": "neutral", "score": 0.3},
            ]
        }
    )
    set_pipeline(fake)
    first = await score_text("Cached headline", redis=redis)
    second = await score_text("Cached headline", redis=redis)
    assert first == pytest.approx(0.7)
    assert second == pytest.approx(0.7)
    # Pipeline called only once — cache hit on second call.
    assert fake.calls == 1
    # And the cache key is what we expect.
    cached = await redis.get(_cache_key("Cached headline"))
    assert cached is not None


async def test_score_batch_preserves_order_and_handles_empty(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    fake = _FakePipeline(
        {
            "good news": [
                {"label": "positive", "score": 0.8},
                {"label": "negative", "score": 0.1},
            ],
            "bad news": [
                {"label": "positive", "score": 0.1},
                {"label": "negative", "score": 0.8},
            ],
        }
    )
    set_pipeline(fake)
    results = await score_batch(["good news", "", "bad news"], redis=redis)
    assert results[0] == pytest.approx(0.7)
    assert results[1] == 0.0  # empty input short-circuits.
    assert results[2] == pytest.approx(-0.7)


async def test_score_batch_mixed_cache_hits(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    fake = _FakePipeline(
        {
            "fresh": [
                {"label": "positive", "score": 0.6},
                {"label": "negative", "score": 0.0},
            ],
        }
    )
    set_pipeline(fake)
    # Pre-seed cache for "cached" so only "fresh" goes to the pipeline.
    await redis.set(_cache_key("cached"), "0.500000")
    results = await score_batch(["cached", "fresh"], redis=redis)
    assert results[0] == pytest.approx(0.5)
    assert results[1] == pytest.approx(0.6)
    assert fake.calls == 1
