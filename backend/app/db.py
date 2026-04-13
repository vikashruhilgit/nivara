"""Async SQLAlchemy engine/session factory + FastAPI dependency."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from backend.app.config import get_settings
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@lru_cache
def get_engine() -> AsyncEngine:
    """Lazy-initialised async engine, cached for the process lifetime."""
    settings = get_settings()
    return create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)


@lru_cache
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a session, committing on success, rolling back on error."""
    factory = _session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
