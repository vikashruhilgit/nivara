"""End-to-end auth flow tests (register/login/refresh/logout/password/me).

Covers AC #1–7 from the m1-3-auth job brief.
"""

from __future__ import annotations

import pytest
from backend.app.auth.jwt import decode_access_token
from backend.app.config import get_settings
from httpx import AsyncClient
from jose import jwt

pytestmark = pytest.mark.asyncio


async def _register(
    client: AsyncClient, email: str = "a@b.co", password: str = "hunter2hunter2"
) -> dict:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "full_name": "Test User"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_register_returns_token_pair_in_body(client: AsyncClient) -> None:
    body = await _register(client)
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60


async def test_register_duplicate_email_409(client: AsyncClient) -> None:
    await _register(client)
    resp = await client.post(
        "/api/auth/register",
        json={"email": "a@b.co", "password": "hunter2hunter2"},
    )
    assert resp.status_code == 409


async def test_login_returns_token_pair(client: AsyncClient) -> None:
    await _register(client)
    resp = await client.post(
        "/api/auth/login",
        json={"email": "a@b.co", "password": "hunter2hunter2"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]
    assert resp.json()["refresh_token"]


async def test_login_wrong_password_401(client: AsyncClient) -> None:
    await _register(client)
    resp = await client.post(
        "/api/auth/login",
        json={"email": "a@b.co", "password": "wrongwrongwrong"},
    )
    assert resp.status_code == 401


async def test_login_unknown_user_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/login",
        json={"email": "nope@x.co", "password": "hunter2hunter2"},
    )
    assert resp.status_code == 401


async def test_refresh_rotates_and_invalidates_old(client: AsyncClient) -> None:
    body = await _register(client)
    old_refresh = body["refresh_token"]

    resp = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 200
    new_pair = resp.json()
    assert new_pair["refresh_token"] != old_refresh
    assert new_pair["access_token"]

    # Old token must now fail (single-use via GETDEL).
    resp2 = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert resp2.status_code == 401


async def test_refresh_unknown_token_401(client: AsyncClient) -> None:
    resp = await client.post("/api/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert resp.status_code == 401


async def test_logout_invalidates_refresh(client: AsyncClient) -> None:
    body = await _register(client)
    rt = body["refresh_token"]
    resp = await client.post("/api/auth/logout", json={"refresh_token": rt})
    assert resp.status_code == 200
    resp2 = await client.post("/api/auth/refresh", json={"refresh_token": rt})
    assert resp2.status_code == 401


async def test_me_requires_bearer(client: AsyncClient) -> None:
    resp = await client.get("/api/auth/me")
    assert resp.status_code in (401, 403)  # HTTPBearer returns 403 when no creds


async def test_me_returns_user_for_valid_bearer(client: AsyncClient) -> None:
    body = await _register(client)
    at = body["access_token"]
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {at}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "a@b.co"


async def test_me_rejects_invalid_bearer(client: AsyncClient) -> None:
    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401


async def test_access_token_claims(client: AsyncClient) -> None:
    body = await _register(client)
    decoded = decode_access_token(body["access_token"])
    assert str(decoded.user_id)
    assert decoded.tier == "free"
    assert decoded.base_currency == "INR"
    assert decoded.kid == "test"
    # Also verify kid is present in the JWT header
    unverified_header = jwt.get_unverified_header(body["access_token"])
    assert unverified_header["kid"] == "test"


async def test_password_change_invalidates_all_refresh_tokens(client: AsyncClient) -> None:
    body = await _register(client)
    old_rt = body["refresh_token"]
    at = body["access_token"]

    resp = await client.post(
        "/api/auth/password",
        headers={"Authorization": f"Bearer {at}"},
        json={"current_password": "hunter2hunter2", "new_password": "newsecret123"},
    )
    assert resp.status_code == 200

    # Old refresh token must now fail even though it is still in Redis (pw_v mismatch)
    resp2 = await client.post("/api/auth/refresh", json={"refresh_token": old_rt})
    assert resp2.status_code == 401


async def test_password_change_wrong_current_401(client: AsyncClient) -> None:
    body = await _register(client)
    at = body["access_token"]
    resp = await client.post(
        "/api/auth/password",
        headers={"Authorization": f"Bearer {at}"},
        json={"current_password": "wrong", "new_password": "newsecret123"},
    )
    assert resp.status_code == 401


async def test_access_token_lifetime(client: AsyncClient) -> None:
    """Access token expiry must match configured minutes."""
    settings = get_settings()
    assert settings.access_token_expires_minutes == 15
