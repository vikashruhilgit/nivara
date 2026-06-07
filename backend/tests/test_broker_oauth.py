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
from backend.app.api import broker_auth as broker_auth_module
from backend.app.brokers.errors import BrokerAPIError, BrokerErrorCode
from backend.app.config import Settings, get_settings
from backend.app.db import get_session
from backend.app.main import app
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from backend.app.services import encryption as enc_module
from backend.app.services.encryption import decrypt_token, encrypt_token, reset_master_key_cache
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


async def test_alpaca_callback_retired_returns_410(
    broker_client: tuple[AsyncClient, AsyncSession, Settings],
) -> None:
    """The Alpaca OAuth callback is retired in favour of the credentials
    endpoint — it now returns 410 Gone and creates no row."""
    client, session, _ = broker_client
    token = await _register_and_token(client)
    resp = await client.post(
        "/api/auth/broker/alpaca/callback",
        headers={"Authorization": f"Bearer {token}"},
        json={"code": "oauth-code-12345"},
    )
    assert resp.status_code == 410, resp.text
    # No row created by the retired path.
    rows = (await session.execute(select(BrokerConnection))).scalars().all()
    assert len(rows) == 0


# --------------------------------------------------------- alpaca credentials


async def _fake_verify_ok(api_key_id: str, api_secret: str) -> str:  # noqa: ARG001
    return "ALPACA-ACCT-001"


async def test_alpaca_credentials_persists_encrypted_per_user(
    broker_client: tuple[AsyncClient, AsyncSession, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC#1/#5/#6: per-user API keys are verified, encrypted, and persisted;
    the raw key/secret never appear in the response body or ciphertext."""
    client, session, _ = broker_client
    token = await _register_and_token(client)

    monkeypatch.setattr(broker_auth_module, "_verify_alpaca_account", _fake_verify_ok)

    resp = await client.post(
        "/api/auth/broker/alpaca/credentials",
        headers={"Authorization": f"Bearer {token}"},
        json={"api_key_id": "PKTESTKEY123", "api_secret": "topsecretvalue"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["broker"] == "alpaca"
    assert body["account_id"] == "ALPACA-ACCT-001"
    assert body["status"] == "active"
    assert body["id"]
    # AC#5: secret/key never echoed back in the response.
    assert "topsecretvalue" not in resp.text
    assert "PKTESTKEY123" not in resp.text

    rows = (await session.execute(select(BrokerConnection))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.broker == "alpaca"
    assert row.account_id == "ALPACA-ACCT-001"
    # Key ID -> access_token_encrypted, Secret -> refresh_token_encrypted.
    assert decrypt_token(row.access_token_encrypted, user_id=row.user_id) == "PKTESTKEY123"
    assert decrypt_token(row.refresh_token_encrypted, user_id=row.user_id) == "topsecretvalue"
    # Plaintext must not survive in the stored ciphertext bytes.
    assert b"PKTESTKEY123" not in row.access_token_encrypted
    assert b"topsecretvalue" not in row.refresh_token_encrypted


async def test_alpaca_credentials_invalid_returns_401_no_row(
    broker_client: tuple[AsyncClient, AsyncSession, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC#2: Alpaca rejecting the creds maps to 401 and creates no row."""
    client, session, _ = broker_client
    token = await _register_and_token(client)

    async def _fake_verify_bad(api_key_id: str, api_secret: str) -> str:  # noqa: ARG001
        raise BrokerAPIError(
            BrokerErrorCode.AUTH_EXPIRED,
            "bad creds",
            broker="alpaca",
            status_code=401,
        )

    monkeypatch.setattr(broker_auth_module, "_verify_alpaca_account", _fake_verify_bad)

    resp = await client.post(
        "/api/auth/broker/alpaca/credentials",
        headers={"Authorization": f"Bearer {token}"},
        json={"api_key_id": "PKBAD", "api_secret": "wrongsecret"},
    )
    assert resp.status_code == 401, resp.text
    rows = (await session.execute(select(BrokerConnection))).scalars().all()
    assert len(rows) == 0


async def test_alpaca_credentials_requires_auth(
    broker_client: tuple[AsyncClient, AsyncSession, Settings],
) -> None:
    """The credentials endpoint requires an authenticated user."""
    client, _, _ = broker_client
    resp = await client.post(
        "/api/auth/broker/alpaca/credentials",
        json={"api_key_id": "PKx", "api_secret": "sx"},
    )
    assert resp.status_code == 401


async def test_sync_invalidates_stale_alpaca_stub_returns_409(
    broker_client: tuple[AsyncClient, AsyncSession, Settings],
) -> None:
    """AC#8 integration: a legacy stub Alpaca row (placeholder tokens) is
    invalidated on sync — the route returns 409 and flips status to expired."""
    client, session, _ = broker_client
    token = await _register_and_token(client)

    user_id = await _get_current_user_id(session)
    conn = BrokerConnection(
        user_id=user_id,
        broker="alpaca",
        account_id="stale-acct",
        access_token_encrypted=encrypt_token("alpaca-access-OLD", user_id=user_id),
        refresh_token_encrypted=encrypt_token("alpaca-refresh-OLD", user_id=user_id),
        status="active",
    )
    session.add(conn)
    await session.commit()

    resp = await client.post(
        "/api/portfolio/sync",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409, resp.text

    refreshed = (
        await session.execute(select(BrokerConnection).where(BrokerConnection.id == conn.id))
    ).scalar_one()
    await session.refresh(refreshed)
    assert refreshed.status == "expired"


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
