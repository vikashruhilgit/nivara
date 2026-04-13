"""Shared pytest fixtures for auth tests.

Uses an in-memory SQLite database (via aiosqlite) for the users table and
``fakeredis`` for refresh-token storage. JWT RS256 keys are generated once
per test session and injected via settings overrides.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import fakeredis.aioredis
import pytest
import pytest_asyncio
from backend.app.config import Settings, get_settings
from backend.app.db import get_session
from backend.app.main import app
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _generate_rsa_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


@pytest.fixture(scope="session")
def rsa_key_pair() -> tuple[str, str]:
    return _generate_rsa_pair()


@pytest.fixture(autouse=True)
def _override_settings(rsa_key_pair: tuple[str, str]) -> None:
    private_pem, public_pem = rsa_key_pair
    get_settings.cache_clear()
    overrides = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",  # ignored; fakeredis override below
        jwt_algorithm="RS256",
        jwt_private_key_pem=private_pem,
        jwt_public_key_pem=public_pem,
        jwt_kid="test",
        jwt_issuer="investiq",
        jwt_audience="investiq-mobile",
        # keep argon2 cheap for tests
        argon2_time_cost=1,
        argon2_memory_cost=8,
        argon2_parallelism=1,
    )

    def _settings() -> Settings:
        return overrides

    # Replace the get_settings reference in every module that imported it.
    # lru_cache-wrapped functions can't be swapped via __wrapped__ alone because
    # consumers hold a direct reference to the cached callable.
    from backend.app import config as config_module
    from backend.app.auth import jwt as jwt_module
    from backend.app.services import auth as auth_service_module

    config_module.get_settings = _settings  # type: ignore[assignment]
    jwt_module.get_settings = _settings  # type: ignore[assignment]
    auth_service_module.get_settings = _settings  # type: ignore[assignment]

    # Clear the jwt module's cached PEM keys so fresh RSA material is used.
    jwt_module._reset_key_caches()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # Only create tables needed for auth tests. Other tables (e.g. audit_log)
        # use Postgres-specific JSONB and cannot be rendered under SQLite.
        await conn.run_sync(lambda sync_conn: User.__table__.create(sync_conn))
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def fake_redis() -> AsyncGenerator[fakeredis.aioredis.FakeRedis, None]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> AsyncGenerator[AsyncClient, None]:
    async def _session_override() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    def _redis_override() -> fakeredis.aioredis.FakeRedis:
        return fake_redis

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_redis] = _redis_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
