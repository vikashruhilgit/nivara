"""Device registration API (M3-20).

Endpoints::

    POST /api/devices/register  — upsert an Expo push token for the current user.

All routes require bearer-token authentication.
"""

from __future__ import annotations

from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.models.device_tokens import DeviceToken
from backend.app.models.users import User
from backend.app.schemas.notification import DeviceOut, DeviceRegisterIn
from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.post("/register", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
async def register_device(
    payload: DeviceRegisterIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DeviceToken:
    """Register (or refresh) an Expo push token for the current user.

    Upsert semantics keyed by ``expo_push_token`` (globally unique):

    * Existing row for the same token → reassign to the current user (if needed),
      reactivate, and bump ``last_seen_at``.
    * No existing row → insert a new one bound to the current user.
    """

    stmt = select(DeviceToken).where(DeviceToken.expo_push_token == payload.expo_push_token)
    existing = (await session.execute(stmt)).scalar_one_or_none()

    if existing is not None:
        existing.user_id = current_user.id
        existing.platform = payload.platform
        existing.is_active = True
        existing.last_seen_at = func.now()
        await session.flush()
        await session.commit()
        await session.refresh(existing)
        return existing

    device = DeviceToken(
        user_id=current_user.id,
        expo_push_token=payload.expo_push_token,
        platform=payload.platform,
        is_active=True,
    )
    session.add(device)
    await session.flush()
    await session.commit()
    await session.refresh(device)
    return device


__all__ = ["router"]
