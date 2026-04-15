"""Global Redis-backed sliding-window rate limiter for broker API calls.

Used to coordinate per-broker (or per-broker-per-account) request budgets
across all workers / Celery processes — an in-memory limiter cannot enforce
this because multiple processes each think they have the full budget.

Algorithm: sliding window implemented as a sorted-set (ZSET) where:

* member = unique request id (``uuid4().hex``)
* score  = ms timestamp when the request was admitted

On each ``acquire()``:

1. ``ZREMRANGEBYSCORE`` trims entries older than ``now - window``.
2. ``ZCARD`` returns the number of in-flight / recent requests.
3. If below ``max_requests``, ``ZADD`` self + ``EXPIRE`` and return.
4. Otherwise, ``ZRANGE 0 0 WITHSCORES`` yields the oldest score; the caller
   sleeps until that score + window has elapsed, then retries.

Total wait is capped at ``max_wait_seconds``; exceeding that raises a
:class:`BrokerAPIError` with ``BrokerErrorCode.RATE_LIMITED`` (no dedicated
``RATE_LIMIT_TIMEOUT`` code exists in the enum, so we reuse ``RATE_LIMITED``
and surface the wait in the message — revisit if an enum constant is added).

Integration into :mod:`backend.app.brokers.zerodha` is intentionally deferred
to a later subtask; this module exposes pure infrastructure.
"""

import asyncio
import logging
import time
import uuid
from types import TracebackType
from typing import Self

from backend.app.brokers.errors import BrokerAPIError, BrokerErrorCode
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_SINGLE_WAIT_WARN_S = 2.0
_CUMULATIVE_WAIT_WARN_S = 5.0


class GlobalRateLimiter:
    """Cross-process sliding-window limiter backed by Redis ZSET.

    Parameters
    ----------
    redis_client:
        Async Redis client (``redis.asyncio.Redis``). Caller owns its lifecycle.
    key:
        Redis key namespace for this limiter bucket (e.g.
        ``"ratelimit:zerodha:orders"``). Distinct buckets must use distinct keys.
    max_requests:
        Maximum admitted requests per rolling ``window_seconds``.
    window_seconds:
        Length of the sliding window in seconds.
    max_wait_seconds:
        Cap on cumulative time a single ``acquire()`` call will wait before
        raising :class:`BrokerAPIError`.
    """

    def __init__(
        self,
        redis_client: Redis,
        key: str,
        max_requests: int = 10,
        window_seconds: float = 1.0,
        max_wait_seconds: float = 30.0,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if max_wait_seconds < 0:
            raise ValueError("max_wait_seconds must be >= 0")

        self._redis = redis_client
        self._key = key
        self._max = max_requests
        self._window_s = window_seconds
        self._window_ms = int(window_seconds * 1000)
        self._max_wait_s = max_wait_seconds
        # Keep the key alive slightly longer than one window so idle buckets
        # expire on their own (no sweep job needed).
        self._expire_s = max(int(window_seconds * 2) + 1, 2)

    async def acquire(self) -> None:
        """Block until a slot is available or raise :class:`BrokerAPIError`."""
        start = time.monotonic()
        cumulative_wait = 0.0

        while True:
            now_ms = int(time.time() * 1000)
            cutoff = now_ms - self._window_ms

            # Trim expired entries and count in-window requests.
            await self._redis.zremrangebyscore(self._key, 0, cutoff)
            count = await self._redis.zcard(self._key)

            if count < self._max:
                member = uuid.uuid4().hex
                await self._redis.zadd(self._key, {member: now_ms})
                await self._redis.expire(self._key, self._expire_s)
                return

            # Compute sleep time from the oldest score in the window.
            oldest = await self._redis.zrange(self._key, 0, 0, withscores=True)
            if not oldest:
                # Race: someone trimmed between ZCARD and ZRANGE. Retry.
                continue

            _member, oldest_score = oldest[0]
            wait_ms = int(oldest_score) + self._window_ms - now_ms
            # Tiny positive floor to avoid busy-spinning if clocks race.
            sleep_s = max(wait_ms / 1000.0, 0.005)

            elapsed = time.monotonic() - start
            if elapsed + sleep_s > self._max_wait_s:
                raise BrokerAPIError(
                    BrokerErrorCode.RATE_LIMITED,
                    (
                        f"rate-limit wait exceeded max_wait_seconds="
                        f"{self._max_wait_s} (key={self._key!r}, elapsed={elapsed:.3f}s)"
                    ),
                )

            if sleep_s > _SINGLE_WAIT_WARN_S:
                logger.warning(
                    "rate_limiter: single wait %.2fs (key=%s, count=%d, max=%d)",
                    sleep_s,
                    self._key,
                    count,
                    self._max,
                )

            await asyncio.sleep(sleep_s)
            cumulative_wait += sleep_s

            if cumulative_wait > _CUMULATIVE_WAIT_WARN_S:
                logger.warning(
                    "rate_limiter: cumulative wait %.2fs (key=%s)",
                    cumulative_wait,
                    self._key,
                )

    async def __aenter__(self) -> Self:
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # Sliding window is time-decayed; no explicit release needed.
        return None
