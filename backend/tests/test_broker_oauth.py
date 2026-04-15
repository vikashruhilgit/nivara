"""Tests for ``/api/auth/broker/*`` endpoints.

Focus areas
-----------
1. ``GET /connect`` returns an OAuth redirect URL (AC #7) for Alpaca.
2. ``GET /connect`` returns 501 for Zerodha (MVP stub).
3. ``GET /connect`` requires authentication.
4. ``POST /callback`` encrypts broker tokens and persists a
   :class:`BrokerConnection` row.
"""

from __future__ import annotations

import base64
import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import fakeredis.aioredis
import pytest
import pytest_asyncio
from backend.app.config import Settings, get_settings
from backend.app.db import get_session
from backend.app.main import app
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from backend.app.services import encryption as enc_module
from backend.app.services.encryption import decrypt_token, reset_master_key_cache
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


def _master_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


@pytest_asyncio.fixture
async def broker_client(
    rsa_key_pair: tuple[str, str],
) -> AsyncGenerator[tuple[AsyncClient, AsyncSession, Settings], None]:
    """Client wired to a SQLite DB that holds users + broker_connections."""
    private_pem, public_pem = rsa_key_pair

    # Settings: JWT keys from session fixture + master encryption key.
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        jwt_algorithm="RS256",
        jwt_private_key_pem=private_pem,
        jwt_public_key_pem=public_pem,
        jwt_kid="test",
        jwt_issuer="investiq",
        jwt_audience="investiq-mobile",
        argon2_time_cost=1,
        argon2_memory_cost=8,
        argon2_parallelism=1,
        master_encryption_key=_master_key(),
        alpaca_api_key="alpaca-key-xyz",
        alpaca_oauth_redirect_uri="http://localhost:8000/api/auth/broker/alpaca/callback",
    )
    from backend.app import config as config_module
    from backend.app.api import broker_auth as broker_auth_module
    from backend.app.auth import jwt as jwt_module
    from backend.app.services import auth as auth_service_module

    config_module.get_settings = lambda: settings  # type: ignore[assignment]
    jwt_module.get_settings = lambda: settings  # type: ignore[assignment]
    auth_service_module.get_settings = lambda: settings  # type: ignore[assignment]
    enc_module.get_settings = lambda: settings  # type: ignore[assignment]
    broker_auth_module.get_settings = lambda: settings  # type: ignore[assignment]
    jwt_module._reset_key_caches()
    reset_master_key_cache()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: User.__table__.create(sync_conn))
        await conn.run_sync(lambda sync_conn: BrokerConnection.__table__.create(sync_conn))
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

        async def _session_override() -> AsyncGenerator[AsyncSession, None]:
            yield session

        def _redis_override() -> fakeredis.aioredis.FakeRedis:
            return redis

        app.dependency_overrides[get_session] = _session_override
        app.dependency_overrides[get_redis] = _redis_override

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac, session, settings
        finally:
            app.dependency_overrides.clear()
            await redis.aclose()

    await engine.dispose()

    config_module.get_settings = get_settings  # type: ignore[assignment]
    jwt_module.get_settings = get_settings  # type: ignore[assignment]
    auth_service_module.get_settings = get_settings  # type: ignore[assignment]
    enc_module.get_settings = get_settings  # type: ignore[assignment]
    broker_auth_module.get_settings = get_settings  # type: ignore[assignment]
    jwt_module._reset_key_caches()
    reset_master_key_cache()


async def _register_and_token(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": "broker-user@example.com",
            "password": "hunter2hunter2",
            "full_name": "Broker Tester",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def test_connect_requires_auth(
    broker_client: tuple[AsyncClient, AsyncSession, Settings],
) -> None:
    client, _, _ = broker_client
    resp = await client.get("/api/auth/broker/alpaca/connect")
    assert resp.status_code == 401


async def test_alpaca_connect_returns_oauth_redirect(
    broker_client: tuple[AsyncClient, AsyncSession, Settings],
) -> None:
    client, _, _ = broker_client
    token = await _register_and_token(client)
    resp = await client.get(
        "/api/auth/broker/alpaca/connect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["broker"] == "alpaca"
    assert body["redirect_url"].startswith("https://app.alpaca.markets/oauth/authorize")
    assert "client_id=alpaca-key-xyz" in body["redirect_url"]
    assert "redirect_uri=" in body["redirect_url"]


async def test_zerodha_connect_returns_501(
    broker_client: tuple[AsyncClient, AsyncSession, Settings],
) -> None:
    client, _, _ = broker_client
    token = await _register_and_token(client)
    resp = await client.get(
        "/api/auth/broker/zerodha/connect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 501


async def test_alpaca_callback_persists_encrypted_tokens(
    broker_client: tuple[AsyncClient, AsyncSession, Settings],
) -> None:
    client, session, _ = broker_client
    token = await _register_and_token(client)
    resp = await client.post(
        "/api/auth/broker/alpaca/callback",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "oauth-code-12345"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["broker"] == "alpaca"
    assert body["status"] == "active"

    # Verify row + ciphertext in DB.
    rows = (await session.execute(select(BrokerConnection))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.broker == "alpaca"
    assert isinstance(row.access_token_encrypted, bytes)
    assert b"alpaca-access-oauth-code-12345" not in row.access_token_encrypted

    # And we can decrypt with the per-user key.
    pt = decrypt_token(row.access_token_encrypted, user_id=row.user_id)
    assert pt == "alpaca-access-oauth-code-12345"


# --------------------------------------------------------------------- connections status


async def _get_current_user_id(
    session: AsyncSession, email: str = "broker-user@example.com"
) -> object:
    row = (await session.execute(select(User).where(User.email == email))).scalar_one()
    return row.id


async def test_connections_endpoint_reports_connected_for_active_row(
    broker_client: tuple[AsyncClient, AsyncSession, Settings],
) -> None:
    client, session, _ = broker_client
    token = await _register_and_token(client)

    # Seed an active Alpaca connection with no expiry.
    user_id = await _get_current_user_id(session)
    conn = BrokerConnection(
        user_id=user_id,
        broker="alpaca",
        account_id="paper-abc",
        access_token_encrypted=b"ciphertext",
        refresh_token_encrypted=b"ciphertext2",
        status="active",
    )
    session.add(conn)
    await session.commit()

    resp = await client.get(
        "/api/auth/broker/connections",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["connections"]) == 1
    item = body["connections"][0]
    assert item["broker"] == "alpaca"
    assert item["status"] == "connected"


async def test_connections_endpoint_reports_auth_expired_for_stale_zerodha(
    broker_client: tuple[AsyncClient, AsyncSession, Settings],
) -> None:
    """Surface AUTH_EXPIRED to the dashboard (AC #5) — derived from
    token_expires_at + Zerodha's 06:00 IST daily cutoff rule."""
    client, session, _ = broker_client
    token = await _register_and_token(client)

    user_id = await _get_current_user_id(session)
    # Set token_expires_at to yesterday 04:00 IST — strictly before today's
    # 06:00 IST cutoff regardless of the current wall-clock time.
    ist = ZoneInfo("Asia/Kolkata")
    stale_expiry = (
        datetime.now(ist).replace(hour=4, minute=0, second=0, microsecond=0) - timedelta(days=2)
    ).astimezone(UTC)

    conn = BrokerConnection(
        user_id=user_id,
        broker="zerodha",
        account_id="ZD0001",
        access_token_encrypted=b"ciphertext",
        refresh_token_encrypted=None,
        token_expires_at=stale_expiry,
        status="active",
    )
    session.add(conn)
    await session.commit()

    resp = await client.get(
        "/api/auth/broker/connections",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["connections"]
    assert len(items) == 1
    assert items[0]["broker"] == "zerodha"
    assert items[0]["status"] == "auth_expired"


async def test_connections_endpoint_reports_auth_expired_for_db_expired_status(
    broker_client: tuple[AsyncClient, AsyncSession, Settings],
) -> None:
    """A connection already flipped to ``expired`` by the sync path surfaces as
    ``auth_expired`` to the dashboard."""
    client, session, _ = broker_client
    token = await _register_and_token(client)

    user_id = await _get_current_user_id(session)
    conn = BrokerConnection(
        user_id=user_id,
        broker="alpaca",
        account_id="paper-xyz",
        access_token_encrypted=b"ct",
        refresh_token_encrypted=b"ct2",
        status="expired",
    )
    session.add(conn)
    await session.commit()

    resp = await client.get(
        "/api/auth/broker/connections",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    items = resp.json()["connections"]
    assert len(items) == 1
    assert items[0]["status"] == "auth_expired"
