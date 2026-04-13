"""Auth service: register/login/refresh/logout + password change.

Bearer token semantics (per CLAUDE.md / TechSpec v1.3):

* Access tokens are short-lived RS256 JWTs returned in JSON bodies.
* Refresh tokens are opaque, single-use, stored in Redis keyed by user.
* Refresh rotation uses ``GETDEL`` (atomic read-and-delete) so concurrent
  refreshes cannot both succeed.
* On password change we bump a per-user ``pw_v`` counter so any refresh token
  issued under a previous version becomes invalid.

Storage schema:

* ``auth:rt:{token}`` → JSON ``{"user_id": ..., "pw_v": N}`` with TTL.
  Single-use: read+delete via GETDEL on refresh; explicit DEL on logout.
* ``auth:pwv:{user_id}`` → integer counter. Bumped on password change.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from backend.app.auth.jwt import create_access_token, generate_refresh_token
from backend.app.config import Settings, get_settings
from backend.app.models.users import User
from backend.app.schemas.auth import TokenPair
from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

_REFRESH_PREFIX = "auth:rt:"
_PWV_PREFIX = "auth:pwv:"


def _rt_key(token: str) -> str:
    return f"{_REFRESH_PREFIX}{token}"


def _pwv_key(user_id: UUID) -> str:
    return f"{_PWV_PREFIX}{user_id}"


@dataclass
class _Hasher:
    ph: PasswordHasher

    @classmethod
    def from_settings(cls, cfg: Settings) -> _Hasher:
        return cls(
            PasswordHasher(
                time_cost=cfg.argon2_time_cost,
                memory_cost=cfg.argon2_memory_cost,
                parallelism=cfg.argon2_parallelism,
            )
        )


class AuthService:
    """Encapsulates all auth-related DB + Redis interactions."""

    def __init__(
        self,
        session: AsyncSession,
        redis: Redis,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings or get_settings()
        self._hasher = _Hasher.from_settings(self.settings).ph

    # --- helpers --------------------------------------------------------

    async def _get_pw_version(self, user_id: UUID) -> int:
        raw = await self.redis.get(_pwv_key(user_id))
        return int(raw) if raw is not None else 0

    async def _bump_pw_version(self, user_id: UUID) -> int:
        return int(await self.redis.incr(_pwv_key(user_id)))

    async def _issue_tokens(self, user: User) -> TokenPair:
        """Sign an access token and persist a fresh refresh token."""
        cfg = self.settings
        tier = cfg.default_user_tier
        base_currency = cfg.default_base_currency

        access = create_access_token(
            user_id=user.id,
            tier=tier,
            base_currency=base_currency,
            settings=cfg,
        )
        refresh = generate_refresh_token()
        pw_v = await self._get_pw_version(user.id)
        payload = json.dumps({"user_id": str(user.id), "pw_v": pw_v})
        ttl_seconds = cfg.refresh_token_expires_days * 24 * 3600
        await self.redis.set(_rt_key(refresh), payload, ex=ttl_seconds)
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=cfg.access_token_expires_minutes * 60,
        )

    # --- use cases ------------------------------------------------------

    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str | None,
        locale: str | None,
    ) -> TokenPair:
        """Create a user and return an initial token pair."""
        hashed = self._hasher.hash(password)
        user = User(
            email=email.lower(),
            password_hash=hashed,
            full_name=full_name,
            locale=locale or "en-IN",
            is_active=True,
        )
        self.session.add(user)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            ) from exc
        await self.session.refresh(user)
        return await self._issue_tokens(user)

    async def login(self, *, email: str, password: str) -> TokenPair:
        """Verify credentials and return a fresh token pair."""
        result = await self.session.execute(select(User).where(User.email == email.lower()))
        user = result.scalar_one_or_none()
        unauthorized = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
        if user is None or not user.is_active:
            # Run verify_dummy to keep timing comparable even when user is missing.
            with contextlib.suppress(VerifyMismatchError):
                self._hasher.verify(_DUMMY_HASH, password)
            raise unauthorized
        try:
            self._hasher.verify(user.password_hash, password)
        except VerifyMismatchError as exc:
            raise unauthorized from exc
        if self._hasher.check_needs_rehash(user.password_hash):
            user.password_hash = self._hasher.hash(password)
            await self.session.commit()
            await self.session.refresh(user)
        return await self._issue_tokens(user)

    async def refresh(self, *, refresh_token: str) -> TokenPair:
        """Rotate a refresh token (atomic single-use via GETDEL)."""
        raw = await self.redis.getdel(_rt_key(refresh_token))
        if raw is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )
        try:
            data = json.loads(raw)
            user_id = UUID(str(data["user_id"]))
            pw_v = int(data["pw_v"])
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed refresh token",
            ) from exc

        current_pw_v = await self._get_pw_version(user_id)
        if pw_v != current_pw_v:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token invalidated (password changed)",
            )

        user = await self.session.get(User, user_id)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User no longer active",
            )
        return await self._issue_tokens(user)

    async def logout(self, *, refresh_token: str) -> None:
        """Idempotent: delete the refresh token if present."""
        await self.redis.delete(_rt_key(refresh_token))

    async def change_password(
        self,
        *,
        user: User,
        current_password: str,
        new_password: str,
    ) -> None:
        """Verify the current password, rehash, and invalidate all refresh tokens."""
        try:
            self._hasher.verify(user.password_hash, current_password)
        except VerifyMismatchError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password incorrect",
            ) from exc
        user.password_hash = self._hasher.hash(new_password)
        await self.session.commit()
        await self._bump_pw_version(user.id)


# Fixed dummy hash used to equalise timing when a login email doesn't exist.
# Generated once with argon2-cffi defaults; the exact value is not security
# sensitive — it just needs to be a valid argon2 hash string.
_DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=2,p=2$"
    "Zm9vYmFyYmF6cXV4Zm9vYg$mYh2o+2sEJwvG6VnJiDLqL6Z5v2XKx3I5m5qQxS8oZE"
)
