"""End-to-end tests for the forgot/reset-password flow.

Covers the subtask-2 contract on ``feat/m4-forgot-password``:

* ``POST /api/auth/password/forgot`` — always 200 with a generic body (no
  account enumeration); rate-limited (429).
* ``POST /api/auth/password/reset`` — consumes a single-use token, sets a new
  password, and invalidates previously-issued refresh tokens.

The raw reset token is never stored in Redis (only its sha256). The only way
to obtain it in a test is via the email sender, so we monkeypatch
``backend.app.services.auth.send_password_reset_email`` (the bound name inside
the service module) with an async stub that captures the raw ``code`` argument.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest
from backend.app.config import get_settings
from backend.app.services.auth import _PWRESET_PREFIX, _sha256_hex
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_FORGOT = "/api/auth/password/forgot"
_RESET = "/api/auth/password/reset"
_GENERIC_FORGOT_DETAIL = "If that email exists, a reset link has been sent."
_RESET_DONE_DETAIL = "Password has been reset."


async def _register(
    client: AsyncClient,
    email: str = "user@example.com",
    password: str = "hunter2hunter2",
) -> dict:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "full_name": "Test User"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class _TokenCapture:
    """Async stub for ``send_password_reset_email`` that records raw codes."""

    def __init__(self) -> None:
        self.codes: list[str] = []
        self.emails: list[str] = []

    async def __call__(self, to_email: str, code: str) -> None:
        self.emails.append(to_email)
        self.codes.append(code)


@pytest.fixture
def captured_tokens(monkeypatch: pytest.MonkeyPatch) -> _TokenCapture:
    """Patch the email sender as bound in the service module and capture codes."""
    capture = _TokenCapture()
    monkeypatch.setattr(
        "backend.app.services.auth.send_password_reset_email",
        capture,
    )
    return capture


async def _forgot(client: AsyncClient, email: str) -> None:
    resp = await client.post(_FORGOT, json={"email": email})
    assert resp.status_code == 200, resp.text
    assert resp.json()["detail"] == _GENERIC_FORGOT_DETAIL


# --- AC #1: no account enumeration -------------------------------------------


async def test_forgot_identical_response_registered_vs_unregistered(
    client: AsyncClient,
    fake_redis: fakeredis.aioredis.FakeRedis,
    captured_tokens: _TokenCapture,
) -> None:
    await _register(client, email="known@example.com")

    known = await client.post(_FORGOT, json={"email": "known@example.com"})
    unknown = await client.post(_FORGOT, json={"email": "ghost@example.com"})

    assert known.status_code == 200
    assert unknown.status_code == 200
    # Identical status AND body — nothing distinguishes the two cases.
    assert known.json() == unknown.json()
    assert known.json()["detail"] == _GENERIC_FORGOT_DETAIL

    # The sender fired only for the registered email.
    assert captured_tokens.emails == ["known@example.com"]


# --- AC #2: token persisted + sender captured a raw token --------------------


async def test_forgot_persists_token_and_emails_raw_code(
    client: AsyncClient,
    fake_redis: fakeredis.aioredis.FakeRedis,
    captured_tokens: _TokenCapture,
) -> None:
    await _register(client, email="active@example.com")
    await _forgot(client, "active@example.com")

    # A reset-token entry exists under the auth:pwreset:* prefix.
    keys = await fake_redis.keys(f"{_PWRESET_PREFIX}*")
    # Exclude rate-limit keys (auth:pwreset:rl:*) — assert a real token entry.
    token_keys = [k for k in keys if not k.startswith(f"{_PWRESET_PREFIX}rl:")]
    assert token_keys, f"expected a reset-token key under {_PWRESET_PREFIX}*, got {keys}"

    # The fake sender captured exactly one raw token.
    assert len(captured_tokens.codes) == 1
    raw_token = captured_tokens.codes[0]
    assert raw_token

    # The stored key is the sha256 of the raw token (raw token never in Redis).
    expected_key = f"{_PWRESET_PREFIX}{_sha256_hex(raw_token)}"
    assert expected_key in token_keys


# --- AC #3 + #5: valid reset, password changes, single-use -------------------


async def test_valid_reset_changes_password_and_is_single_use(
    client: AsyncClient,
    fake_redis: fakeredis.aioredis.FakeRedis,
    captured_tokens: _TokenCapture,
) -> None:
    email = "reset@example.com"
    old_pw = "hunter2hunter2"
    new_pw = "brandnewpass99"
    await _register(client, email=email, password=old_pw)

    await _forgot(client, email)
    token = captured_tokens.codes[-1]

    # Reset with a valid new password.
    resp = await client.post(_RESET, json={"token": token, "new_password": new_pw})
    assert resp.status_code == 200, resp.text
    assert resp.json()["detail"] == _RESET_DONE_DETAIL

    # Old password no longer works; new password does (password_hash changed).
    old_login = await client.post("/api/auth/login", json={"email": email, "password": old_pw})
    assert old_login.status_code == 401

    new_login = await client.post("/api/auth/login", json={"email": email, "password": new_pw})
    assert new_login.status_code == 200, new_login.text
    assert new_login.json()["access_token"]

    # Single-use: replaying the same token fails with a generic 400.
    replay = await client.post(_RESET, json={"token": token, "new_password": "anotherpass123"})
    assert replay.status_code == 400
    assert replay.json()["detail"] == "Invalid or expired reset token"


# --- AC #4: refresh tokens issued before reset are invalidated ---------------


async def test_old_refresh_token_rejected_after_reset(
    client: AsyncClient,
    fake_redis: fakeredis.aioredis.FakeRedis,
    captured_tokens: _TokenCapture,
) -> None:
    email = "refresh@example.com"
    old_pw = "hunter2hunter2"
    new_pw = "brandnewpass99"

    body = await _register(client, email=email, password=old_pw)
    old_refresh = body["refresh_token"]

    await _forgot(client, email)
    token = captured_tokens.codes[-1]

    reset = await client.post(_RESET, json={"token": token, "new_password": new_pw})
    assert reset.status_code == 200, reset.text

    # The refresh token issued *before* the reset must now be rejected (pw_v bump).
    resp = await client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 401
    assert "invalidated" in resp.json()["detail"].lower()


# --- AC #6: invalid / already-used / expired tokens → generic 400 -----------


async def test_reset_with_unknown_token_400(
    client: AsyncClient,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    resp = await client.post(
        _RESET, json={"token": "not-a-real-token", "new_password": "brandnewpass99"}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid or expired reset token"


async def test_reset_with_expired_token_400(
    client: AsyncClient,
    fake_redis: fakeredis.aioredis.FakeRedis,
    captured_tokens: _TokenCapture,
) -> None:
    email = "expire@example.com"
    await _register(client, email=email)
    await _forgot(client, email)
    token = captured_tokens.codes[-1]

    # Simulate expiry / eviction by deleting the stored key before the reset.
    await fake_redis.delete(f"{_PWRESET_PREFIX}{_sha256_hex(token)}")

    resp = await client.post(_RESET, json={"token": token, "new_password": "brandnewpass99"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid or expired reset token"


# --- AC #7: new_password length validation (pydantic 422) --------------------


async def test_reset_short_password_422(
    client: AsyncClient,
    fake_redis: fakeredis.aioredis.FakeRedis,
    captured_tokens: _TokenCapture,
) -> None:
    email = "short@example.com"
    await _register(client, email=email)
    await _forgot(client, email)
    token = captured_tokens.codes[-1]

    resp = await client.post(_RESET, json={"token": token, "new_password": "short"})
    assert resp.status_code == 422


# --- AC #8: rate limiting ----------------------------------------------------


async def test_forgot_rate_limited_returns_429(
    client: AsyncClient,
    fake_redis: fakeredis.aioredis.FakeRedis,
    captured_tokens: _TokenCapture,
) -> None:
    settings = get_settings()
    max_allowed = settings.password_reset_rate_limit_max
    email = "rl@example.com"
    await _register(client, email=email)

    # The first ``max_allowed`` requests succeed within the fixed window.
    for _ in range(max_allowed):
        resp = await client.post(_FORGOT, json={"email": email})
        assert resp.status_code == 200, resp.text

    # The next request exceeds the window maximum → 429.
    resp = await client.post(_FORGOT, json={"email": email})
    assert resp.status_code == 429
