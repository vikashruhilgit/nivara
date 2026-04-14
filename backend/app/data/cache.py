"""Redis caching helpers for the :mod:`backend.app.data` provider layer.

Key scheme (per TechSpec v1.3 §9.1)::

    data:{provider}:ohlcv:{symbol}:{lookback_days}    TTL 1h
    data:{provider}:fundamentals:{symbol}             TTL 24h
    data:{provider}:quote:{symbol}                    TTL 60s (optional)

Only two call sites use this module: :class:`YahooProvider` reads the cache
before hitting upstream and writes on success. Every other consumer calls the
provider interface, which is transparently cached.

Serialisation uses ``pydantic.BaseModel.model_dump_json()`` so:

* Decimal fields round-trip exactly (strings in JSON).
* ``datetime`` fields stay timezone-aware.
* Schema evolution is tolerated: we ``json.loads`` → ``model_validate``, so
  unknown fields are silently dropped and missing optional fields default to
  ``None``.

If a cached payload is corrupt (bad JSON, schema mismatch) the helper returns
``None`` rather than raising, so the caller falls through to the upstream
fetch path. We log a warning but never propagate cache errors to users.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

#: OHLCV cache TTL — 1 hour per AC #2.
OHLCV_TTL_SECONDS = 60 * 60

#: Fundamentals cache TTL — 24 hours per AC #5.
FUNDAMENTALS_TTL_SECONDS = 24 * 60 * 60

#: Quote cache TTL — 60 seconds (tight because quotes are more volatile).
QUOTE_TTL_SECONDS = 60


def ohlcv_key(provider: str, symbol: str, lookback_days: int) -> str:
    return f"data:{provider}:ohlcv:{symbol}:{lookback_days}"


def fundamentals_key(provider: str, symbol: str) -> str:
    return f"data:{provider}:fundamentals:{symbol}"


def quote_key(provider: str, symbol: str) -> str:
    return f"data:{provider}:quote:{symbol}"


M = TypeVar("M", bound=BaseModel)


async def get_model(redis: Redis, key: str, model: type[M]) -> M | None:
    """Fetch and validate a single Pydantic model from Redis.

    Returns ``None`` on cache miss *or* on corrupt payload (the caller is
    expected to treat both outcomes identically — refetch from upstream).
    """
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        logger.warning("cache corrupt for key=%s: %s", key, exc)
        return None


async def set_model(redis: Redis, key: str, value: BaseModel, *, ttl: int) -> None:
    """Serialise ``value`` to JSON and store with the given TTL (seconds)."""
    await redis.set(key, value.model_dump_json(), ex=ttl)


async def get_model_list(redis: Redis, key: str, model: type[M]) -> list[M] | None:
    """Fetch a JSON array of models (used for OHLCV bar lists)."""
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        adapter = TypeAdapter(list[model])  # type: ignore[valid-type]
        return adapter.validate_json(raw)
    except ValidationError as exc:
        logger.warning("cache corrupt (list) for key=%s: %s", key, exc)
        return None


async def set_model_list(redis: Redis, key: str, values: Iterable[BaseModel], *, ttl: int) -> None:
    """Serialise an iterable of models as a JSON array and store with TTL."""
    items = list(values)
    # Round-trip through model_dump_json to avoid relying on TypeAdapter for
    # arbitrary model subclasses — simpler and equally correct.
    payload = "[" + ",".join(m.model_dump_json() for m in items) + "]"
    await redis.set(key, payload, ex=ttl)


async def invalidate(redis: Redis, *keys: str) -> int:
    """Delete the given cache keys. Used by the corporate-actions job (TechSpec §9.2).

    Returns the number of keys actually deleted. Never raises on missing keys.
    """
    if not keys:
        return 0
    return int(await redis.delete(*keys))


async def invalidate_symbol(redis: Redis, provider: str, symbol: str) -> int:
    """Invalidate every cache entry for ``symbol`` under ``provider``.

    Used when corporate actions (splits, dividends) change historical prices.
    Uses ``SCAN`` (not ``KEYS``) to avoid blocking Redis on large datasets.
    """
    pattern = f"data:{provider}:*:{symbol}*"
    deleted = 0
    async for key in redis.scan_iter(match=pattern):
        deleted += int(await redis.delete(key))
    return deleted


__all__ = [
    "FUNDAMENTALS_TTL_SECONDS",
    "OHLCV_TTL_SECONDS",
    "QUOTE_TTL_SECONDS",
    "fundamentals_key",
    "get_model",
    "get_model_list",
    "invalidate",
    "invalidate_symbol",
    "ohlcv_key",
    "quote_key",
    "set_model",
    "set_model_list",
]
