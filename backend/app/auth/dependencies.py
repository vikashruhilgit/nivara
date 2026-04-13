"""FastAPI dependencies for request authentication."""

from __future__ import annotations

from backend.app.auth.jwt import InvalidTokenError, decode_access_token
from backend.app.db import get_session
from backend.app.models.users import User
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resolve the current user from an ``Authorization: Bearer <token>`` header.

    Raises 401 for missing/invalid/expired tokens or inactive users.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized
    try:
        decoded = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = await session.get(User, decoded.user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user
