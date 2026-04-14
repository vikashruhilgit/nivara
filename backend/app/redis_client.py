"""Async Redis client factory for refresh-token storage."""

from __future__ import annotations

from functools import lru_cache

from backend.app.config import get_settings
from redis.asyncio import Redis, from_url


@lru_cache
def get_redis() -> Redis:
    """Return a process-wide async Redis client configured from settings."""
    settings = get_settings()
    return from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
