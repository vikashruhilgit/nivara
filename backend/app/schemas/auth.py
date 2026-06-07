"""Pydantic v2 schemas for the auth API surface."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    """Payload for POST /api/auth/register."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    locale: str | None = Field(default=None, max_length=10)


class LoginRequest(BaseModel):
    """Payload for POST /api/auth/login."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    """Payload for POST /api/auth/refresh."""

    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    """Payload for POST /api/auth/logout."""

    refresh_token: str = Field(min_length=1)


class PasswordChangeRequest(BaseModel):
    """Payload for POST /api/auth/password (current user)."""

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    """Payload for POST /api/auth/password/forgot."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Payload for POST /api/auth/password/reset."""

    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class TokenPair(BaseModel):
    """Response body for register / login / refresh.

    Mobile stores ``refresh_token`` in ``expo-secure-store``. Bearer pattern:
    the client sends ``Authorization: Bearer <access_token>`` on subsequent
    requests. No cookies, no CSRF.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 scheme name, not a credential
    expires_in: int = Field(description="Access token lifetime in seconds")


class UserPublic(BaseModel):
    """Minimal user representation returned by protected endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str | None = None
    locale: str
    is_active: bool


class MessageResponse(BaseModel):
    """Simple ack body (logout, password-change)."""

    detail: str
