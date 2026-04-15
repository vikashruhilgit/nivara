"""Notification API routes (M3-20).

Endpoints::

    GET   /api/notifications                      — paginated list (with read filter)
    PATCH /api/notifications/{notification_id}/read — mark a notification as read

All routes require bearer-token authentication and are scoped to the
authenticated user.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.models.notifications import Notification
from backend.app.models.users import User
from backend.app.schemas.notification import (
    NotificationListResponse,
    NotificationOut,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    read: bool | None = Query(
        None,
        description="Filter by read status. None=all, False=unread, True=read",
    ),
) -> NotificationListResponse:
    """Return a paginated list of notifications for the current user.

    Ordered by ``created_at`` DESC. When ``read`` is ``False`` only unread
    notifications (``read_at IS NULL``) are returned; when ``True`` only read
    ones; when unset, all are returned.
    """

    base_filters = [Notification.user_id == current_user.id]
    if read is False:
        base_filters.append(Notification.read_at.is_(None))
    elif read is True:
        base_filters.append(Notification.read_at.is_not(None))

    count_stmt = select(func.count()).select_from(Notification).where(*base_filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    offset = (page - 1) * per_page
    list_stmt = (
        select(Notification)
        .where(*base_filters)
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    rows = (await session.execute(list_stmt)).scalars().all()

    items = [NotificationOut.model_validate(row) for row in rows]
    return NotificationListResponse(
        items=items,
        page=page,
        per_page=per_page,
        total=total,
    )


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> NotificationOut:
    """Mark a notification as read.

    Idempotent — if ``read_at`` is already set, the row is returned unchanged.
    Returns 404 when the notification does not exist or does not belong to the
    current user.
    """

    stmt = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == current_user.id,
    )
    notification = (await session.execute(stmt)).scalar_one_or_none()
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(notification)

    return NotificationOut.model_validate(notification)


__all__ = ["router"]
