"""Base types for the notification dispatch pipeline.

The dashboard / in-app feed is implicit: every notification producer
persists a :class:`~backend.app.models.notifications.Notification` row
which the mobile app reads via the notifications API. The channels in
this package deliver *outbound* copies (push, email, ...) of that row
to the user. No dedicated "in-app" channel is needed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from backend.app.models.notifications import Notification
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class NotificationChannel(Protocol):
    """A single outbound notification transport (push, email, ...)."""

    async def send(self, notification: Notification) -> bool:
        """Deliver ``notification``. Return ``True`` on success, ``False`` otherwise.

        Implementations MUST NOT raise on transport failures — they should
        catch, log, and return ``False``. The dispatcher will still capture
        any unexpected exceptions as a safety net.
        """
        ...


@dataclass
class DispatchResult:
    """Outcome of dispatching one notification across multiple channels."""

    notification_id: UUID
    channels_attempted: list[str] = field(default_factory=list)
    channels_succeeded: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def any_success(self) -> bool:
        return bool(self.channels_succeeded)


class AlertDispatcher:
    """Fan-out dispatcher that sends one notification to many channels.

    The caller owns the SQLAlchemy transaction; this class only mutates
    ``notification.sent_at`` in memory (no commit). A single failing
    channel never aborts the others.
    """

    def __init__(
        self,
        session: AsyncSession,
        channels: list[NotificationChannel],
    ) -> None:
        self._session = session
        self._channels = channels

    async def dispatch(self, notification: Notification) -> DispatchResult:
        result = DispatchResult(notification_id=notification.id)
        for channel in self._channels:
            name = type(channel).__name__
            result.channels_attempted.append(name)
            try:
                ok = await channel.send(notification)
            except Exception as exc:  # defensive: channels should handle their own
                logger.warning(
                    "notification channel %s raised unexpectedly: %s",
                    name,
                    exc.__class__.__name__,
                )
                result.errors[name] = f"{exc.__class__.__name__}: {exc}"
                continue
            if ok:
                result.channels_succeeded.append(name)
            else:
                result.errors.setdefault(name, "send returned False")

        if result.any_success and notification.sent_at is None:
            notification.sent_at = datetime.now(UTC)

        return result

    async def dispatch_many(self, notifications: list[Notification]) -> list[DispatchResult]:
        results: list[DispatchResult] = []
        for n in notifications:
            results.append(await self.dispatch(n))
        return results
