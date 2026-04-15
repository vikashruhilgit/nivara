"""Notification & device-token Pydantic schemas (M3-20).

These are the wire schemas for the Risk Guardian → Notification Dispatch
pipeline. ``AlertEvent`` is the *internal* event produced by the guardian
detectors; ``NotificationOut`` / ``NotificationListResponse`` are the API
responses for the in-app inbox; ``DeviceRegisterIn`` / ``DeviceOut`` are used
by the Expo push-token registration endpoint (Subtask 3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

NotificationType = Literal["price_alert", "system"]
Platform = Literal["ios", "android"]


class AlertEvent(BaseModel):
    """Internal alert event emitted by :class:`RiskGuardian` detectors.

    Not directly exposed over the API — the guardian converts these into
    ``Notification`` ORM rows via ``persist_alerts``.
    """

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    notification_type: NotificationType
    title: str
    body: str
    payload: dict[str, Any]


class NotificationOut(BaseModel):
    """A single Notification row as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    notification_type: str
    title: str
    body: str
    payload: dict[str, Any] | None
    sent_at: datetime | None
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    """Paged list response for ``GET /api/notifications``."""

    items: list[NotificationOut]
    page: int
    per_page: int
    total: int


class DeviceRegisterIn(BaseModel):
    """Request body for ``POST /api/notifications/register-device``."""

    expo_push_token: str
    platform: Platform


class DeviceOut(BaseModel):
    """Response for device-token registration / listing."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    expo_push_token: str
    platform: str
    is_active: bool
    created_at: datetime


__all__ = [
    "AlertEvent",
    "DeviceOut",
    "DeviceRegisterIn",
    "NotificationListResponse",
    "NotificationOut",
    "NotificationType",
    "Platform",
]
