"""JWT RS256 key management and access/refresh token utilities.

Access tokens are short-lived (default 15 min), RS256-signed JWTs carrying
``user_id``, ``tier``, ``base_currency``; the signing key ID is advertised via
the ``kid`` header (to support future rotation).

Refresh tokens are opaque, high-entropy random strings — *not* JWTs. They are
stored in Redis by :mod:`backend.app.services.auth` with single-use semantics
(GETDEL on refresh). Keeping them opaque avoids coupling refresh rotation to
JWT validation rules.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from backend.app.config import Settings, get_settings
from jose import JWTError, jwt


class InvalidTokenError(Exception):
    """Raised when an access token cannot be validated."""


@dataclass(frozen=True)
class DecodedAccessToken:
    """Validated access token payload."""

    user_id: UUID
    tier: str
    base_currency: str
    kid: str
    expires_at: datetime


# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------


def _read_pem(path: str | None, inline: str | None, *, kind: str) -> str:
    """Return PEM content, preferring inline value, falling back to path."""
    if inline:
        return inline
    if path:
        pem_path = Path(path)
        if not pem_path.is_file():
            raise RuntimeError(f"JWT {kind} key file not found: {path}")
        return pem_path.read_text(encoding="utf-8")
    raise RuntimeError(
        f"JWT {kind} key not configured. Set jwt_{kind}_key_path or "
        f"jwt_{kind}_key_pem (see scripts/generate_keys.sh)."
    )


_private_key_cache: dict[tuple[str | None, str | None], str] = {}
_public_key_cache: dict[tuple[str | None, str | None], str] = {}


def _private_key(settings: Settings) -> str:
    key = (settings.jwt_private_key_path, settings.jwt_private_key_pem)
    if key not in _private_key_cache:
        _private_key_cache[key] = _read_pem(
            settings.jwt_private_key_path, settings.jwt_private_key_pem, kind="private"
        )
    return _private_key_cache[key]


def _public_key(settings: Settings) -> str:
    key = (settings.jwt_public_key_path, settings.jwt_public_key_pem)
    if key not in _public_key_cache:
        _public_key_cache[key] = _read_pem(
            settings.jwt_public_key_path, settings.jwt_public_key_pem, kind="public"
        )
    return _public_key_cache[key]


def _reset_key_caches() -> None:
    """Test helper: clear cached PEM material."""
    _private_key_cache.clear()
    _public_key_cache.clear()


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------


def create_access_token(
    *,
    user_id: UUID,
    tier: str,
    base_currency: str,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> str:
    """Sign an RS256 access token with the configured private key and kid."""
    cfg = settings or get_settings()
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=cfg.access_token_expires_minutes)
    payload = {
        "sub": str(user_id),
        "user_id": str(user_id),
        "tier": tier,
        "base_currency": base_currency,
        "kid": cfg.jwt_kid,
        "iss": cfg.jwt_issuer,
        "aud": cfg.jwt_audience,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token: str = jwt.encode(
        payload,
        _private_key(cfg),
        algorithm=cfg.jwt_algorithm,
        headers={"kid": cfg.jwt_kid},
    )
    return token


def decode_access_token(token: str, *, settings: Settings | None = None) -> DecodedAccessToken:
    """Verify signature and standard claims, returning the decoded payload.

    Raises :class:`InvalidTokenError` for any validation failure (expiry,
    signature, audience, issuer, malformed claims).
    """
    cfg = settings or get_settings()
    try:
        payload = jwt.decode(
            token,
            _public_key(cfg),
            algorithms=[cfg.jwt_algorithm],
            audience=cfg.jwt_audience,
            issuer=cfg.jwt_issuer,
        )
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    try:
        user_id = UUID(str(payload["user_id"]))
        tier = str(payload["tier"])
        base_currency = str(payload["base_currency"])
        kid = str(payload["kid"])
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidTokenError(f"malformed access token payload: {exc}") from exc

    return DecodedAccessToken(
        user_id=user_id,
        tier=tier,
        base_currency=base_currency,
        kid=kid,
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# Refresh tokens (opaque)
# ---------------------------------------------------------------------------


def generate_refresh_token(nbytes: int = 48) -> str:
    """Return a URL-safe opaque refresh token (>=48 bytes entropy by default)."""
    return secrets.token_urlsafe(nbytes)
