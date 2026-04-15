"""Notification dispatch infrastructure (M3-20).

This package implements the multi-channel alert dispatch used by the Risk
Guardian and other notification producers. Each notification producer
creates a :class:`~backend.app.models.notifications.Notification` row
(which IS the in-app / dashboard feed — no channel needed) and then
hands the row to :class:`AlertDispatcher` to fan out to any number of
external channels (Expo push, email, ...).

Channels follow the :class:`NotificationChannel` Protocol; adding a new
one (SMS, Slack, ...) only requires implementing ``async def send``.
"""

from __future__ import annotations

from backend.app.notifications.base import (
    AlertDispatcher,
    DispatchResult,
    NotificationChannel,
)
from backend.app.notifications.email import EmailChannel, SmtpConfig
from backend.app.notifications.push import ExpoPushChannel

__all__ = [
    "AlertDispatcher",
    "DispatchResult",
    "EmailChannel",
    "ExpoPushChannel",
    "NotificationChannel",
    "SmtpConfig",
]
