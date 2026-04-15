"""Expo Push notification channel.

Sends a batch POST to Expo's public push API for every active device
token registered against ``notification.user_id``. Zero devices is not
an error — it returns ``False`` so callers can decide (AC #11).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from backend.app.models.device_tokens import DeviceToken
from backend.app.models.notifications import Notification
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


class ExpoPushChannel:
    """Expo Push Service channel."""

    def __init__(
        self,
        session: AsyncSession,
        http_client: httpx.AsyncClient,
        access_token: str | None = None,
    ) -> None:
        self._session = session
        self._http = http_client
        self._access_token = access_token

    async def send(self, notification: Notification) -> bool:
        tokens = await self._active_tokens(notification.user_id)
        if not tokens:
            return False

        messages = self._build_messages(notification, tokens)
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip, deflate",
        }
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        try:
            resp = await self._http.post(EXPO_PUSH_URL, json=messages, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning(
                "ExpoPushChannel: HTTP error %s for user=%s",
                exc.__class__.__name__,
                notification.user_id,
            )
            return False

        if resp.status_code != 200:
            logger.warning(
                "ExpoPushChannel: non-200 status=%s for user=%s",
                resp.status_code,
                notification.user_id,
            )
            return False

        try:
            payload = resp.json()
        except ValueError:
            logger.warning("ExpoPushChannel: non-JSON response for user=%s", notification.user_id)
            return False

        if isinstance(payload, dict) and payload.get("errors"):
            logger.warning(
                "ExpoPushChannel: Expo reported errors for user=%s",
                notification.user_id,
            )
            return False

        return True

    async def _active_tokens(self, user_id: Any) -> list[str]:
        stmt = select(DeviceToken.expo_push_token).where(
            DeviceToken.user_id == user_id,
            DeviceToken.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def _build_messages(
        self, notification: Notification, tokens: list[str]
    ) -> list[dict[str, Any]]:
        data = notification.payload or {}
        return [
            {
                "to": token,
                "title": notification.title,
                "body": notification.body,
                "data": data,
                "sound": "default",
            }
            for token in tokens
        ]
