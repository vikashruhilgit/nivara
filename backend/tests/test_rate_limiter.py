"""Tests for :class:`backend.app.brokers.rate_limiter.GlobalRateLimiter`.

Backed by ``fakeredis.aioredis`` so tests run without a live Redis. Timing
assertions use generous lower bounds only — upper bounds are avoided to
keep the suite stable under CI load.
"""

import asyncio
import time

import fakeredis.aioredis
import pytest
from backend.app.brokers.errors import BrokerAPIError, BrokerErrorCode
from backend.app.brokers.rate_limiter import GlobalRateLimiter

pytestmark = pytest.mark.asyncio


async def _make_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


async def test_burst_within_window_is_immediate() -> None:
    redis = await _make_redis()
    limiter = GlobalRateLimiter(
        redis,
        key="rl:test:burst",
        max_requests=5,
        window_seconds=1.0,
        max_wait_seconds=5.0,
    )

    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - start

    # Five acquires within a 5-request window should cost near-zero.
    assert elapsed < 0.25, f"expected near-instant burst, took {elapsed:.3f}s"


async def test_one_over_max_waits_for_window_roll() -> None:
    redis = await _make_redis()
    window = 0.5
    limiter = GlobalRateLimiter(
        redis,
        key="rl:test:rollover",
        max_requests=3,
        window_seconds=window,
        max_wait_seconds=5.0,
    )

    for _ in range(3):
        await limiter.acquire()

    start = time.monotonic()
    await limiter.acquire()
    waited = time.monotonic() - start

    # The 4th request must wait until the oldest entry rolls out of the window.
    # Allow slack on the upper side for scheduler jitter; lower bound must hold.
    assert waited >= window * 0.7, f"expected >= {window * 0.7:.3f}s wait, got {waited:.3f}s"


async def test_concurrent_gather_respects_rate() -> None:
    redis = await _make_redis()
    max_requests = 5
    window = 0.4
    total = 20
    limiter = GlobalRateLimiter(
        redis,
        key="rl:test:concurrent",
        max_requests=max_requests,
        window_seconds=window,
        max_wait_seconds=30.0,
    )

    start = time.monotonic()

    async def one() -> None:
        await limiter.acquire()

    await asyncio.gather(*(one() for _ in range(total)))
    elapsed = time.monotonic() - start

    # With N requests at rate R per window W, elapsed must be >= floor(N/R)*W.
    min_expected = (total // max_requests) * window * 0.7  # 0.7 slack for jitter
    assert elapsed >= min_expected, (
        f"expected >= {min_expected:.3f}s for {total} reqs "
        f"at {max_requests}/{window}s, got {elapsed:.3f}s"
    )


async def test_exceeding_max_wait_raises_broker_error() -> None:
    redis = await _make_redis()
    # Window of 2s with just 1 slot; second acquire cannot complete before
    # max_wait_seconds=0.2s elapses.
    limiter = GlobalRateLimiter(
        redis,
        key="rl:test:giveup",
        max_requests=1,
        window_seconds=2.0,
        max_wait_seconds=0.2,
    )

    await limiter.acquire()

    with pytest.raises(BrokerAPIError) as exc_info:
        await limiter.acquire()

    assert exc_info.value.code == BrokerErrorCode.RATE_LIMITED


async def test_context_manager_acquires() -> None:
    redis = await _make_redis()
    limiter = GlobalRateLimiter(
        redis,
        key="rl:test:ctx",
        max_requests=2,
        window_seconds=0.5,
        max_wait_seconds=2.0,
    )

    async with limiter:
        pass
    async with limiter:
        pass

    # Third entry should wait for window roll but succeed.
    start = time.monotonic()
    async with limiter:
        waited = time.monotonic() - start
    assert waited >= 0.1, f"expected a measurable wait, got {waited:.3f}s"
