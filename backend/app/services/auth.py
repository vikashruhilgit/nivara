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
* ``auth:pwreset:{sha256(token)}`` → JSON ``{"user_id": ...}`` with TTL.
  Single-use: read+delete via GETDEL on reset. Only the sha256 of the token
  is stored; the raw token travels to the user solely by email.
* ``auth:pwreset:rl:email:{email}`` / ``auth:pwreset:rl:ip:{ip}`` → fixed-window
  request counters for forgot-password rate limiting. The INCR + window EXPIRE
  (NX) run in one pipeline so the key always carries a TTL.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from backend.app.auth.jwt import create_access_token, generate_refresh_token
from backend.app.config import Settings, get_settings
from backend.app.models.users import User
from backend.app.notifications.transactional import send_password_reset_email
from backend.app.schemas.auth import TokenPair
from fastapi import BackgroundTasks, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

_REFRESH_PREFIX = "auth:rt:"
_PWV_PREFIX = "auth:pwv:"
_PWRESET_PREFIX = "auth:pwreset:"
_PWRESET_RL_EMAIL_PREFIX = "auth:pwreset:rl:email:"
_PWRESET_RL_IP_PREFIX = "auth:pwreset:rl:ip:"


def _rt_key(token: str) -> str:
    return f"{_REFRESH_PREFIX}{token}"


def _pwv_key(user_id: UUID) -> str:
    return f"{_PWV_PREFIX}{user_id}"


def _sha256_hex(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _pwreset_key(token_hash: str) -> str:
    return f"{_PWRESET_PREFIX}{token_hash}"


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

    # --- password reset (forgot / reset) --------------------------------

    async def _check_rate_limit(self, key: str) -> None:
        """Fixed-window counter: atomically INCR ``key`` and ensure a TTL.

        The INCR and the window EXPIRE run in a single Redis pipeline so the
        window key can never end up without a TTL (which would otherwise block
        an email/IP forever if the process died between the two commands).
        ``EXPIRE ... NX`` only sets the expiry when none exists yet, preserving
        fixed-window semantics (later hits in the same window don't slide it).

        Raises ``HTTPException(429)`` once the count exceeds the configured
        per-window maximum.
        """
        cfg = self.settings
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, cfg.password_reset_rate_limit_window_seconds, nx=True)
            results = await pipe.execute()
        count = int(results[0])
        if count > cfg.password_reset_rate_limit_max:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many password reset requests. Please try again later.",
            )

    async def request_password_reset(
        self,
        email: str,
        *,
        ip: str | None = None,
        background_tasks: BackgroundTasks | None = None,
    ) -> None:
        """Begin a password-reset flow for ``email`` (never reveals existence).

        Rate-limited per-email and per-IP. If the email maps to an active user,
        an opaque token is generated, its sha256 stored in Redis with a TTL,
        and the raw token emailed. Missing/inactive users are silently ignored.

        The email send is dispatched **out-of-band** (via ``background_tasks``
        when supplied) so the HTTP response latency does not depend on whether
        the user exists or on the potentially slow SMTP send — closing the
        user-enumeration timing oracle. The token-gen + Redis SET that remain
        inline are microsecond-scale, comparable to ``login``'s dummy-hash work.
        """
        normalized = email.lower()
        # The per-email rate limit is an intentional anti-abuse tradeoff: it
        # also lets an attacker who knows a victim's address exhaust that
        # victim's reset quota (a soft DoS on resets). Counting only for
        # *existing* users was deliberately rejected — branching the limit on
        # account existence would re-introduce the enumeration signal this flow
        # is designed to remove. The per-IP limit below bounds broad abuse.
        await self._check_rate_limit(f"{_PWRESET_RL_EMAIL_PREFIX}{normalized}")
        if ip:
            await self._check_rate_limit(f"{_PWRESET_RL_IP_PREFIX}{ip}")

        result = await self.session.execute(select(User).where(User.email == normalized))
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            # Never reveal whether the email exists.
            return

        token = generate_refresh_token()
        token_hash = _sha256_hex(token)
        payload = json.dumps({"user_id": str(user.id)})
        ttl_seconds = self.settings.password_reset_token_expires_minutes * 60
        await self.redis.set(_pwreset_key(token_hash), payload, ex=ttl_seconds)

        # Dispatch the email out-of-band: background tasks run AFTER the response
        # is sent, so response latency is independent of the (potentially slow)
        # SMTP send. The sender itself never raises on missing SMTP config.
        if background_tasks is not None:
            background_tasks.add_task(send_password_reset_email, user.email, token)
        else:
            await send_password_reset_email(user.email, token)

    async def reset_password(self, token: str, new_password: str) -> None:
        """Consume a reset token (atomic single-use) and set a new password.

        Raises ``HTTPException(400)`` on a missing/expired token. On success the
        password is rehashed and the per-user ``pw_v`` counter bumped so all
        previously-issued refresh tokens are invalidated.
        """
        token_hash = _sha256_hex(token)
        raw = await self.redis.getdel(_pwreset_key(token_hash))
        invalid = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
        if raw is None:
            raise invalid
        try:
            data = json.loads(raw)
            user_id = UUID(str(data["user_id"]))
        except (ValueError, KeyError, TypeError) as exc:
            raise invalid from exc

        user = await self.session.get(User, user_id)
        if user is None or not user.is_active:
            raise invalid

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
