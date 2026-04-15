"""Real-time alerts WebSocket (M3-20).

Endpoints::

    POST /api/ws/ticket   — mint a short-lived (30s) single-use ticket
    WS   /ws/alerts       — subscribe to user-scoped alert stream

WebSockets cannot easily use bearer-token ``Depends`` flows, so authentication
is bootstrapped via a Redis-backed ticket: the client calls ``POST
/api/ws/ticket`` over HTTPS with their bearer token, receives a ticket, and
opens the WebSocket with ``?ticket=<value>``. The ticket is consumed via
``GETDEL`` so it's strictly single-use.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
from typing import Any
from uuid import UUID

from backend.app.auth.dependencies import get_current_user
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

router = APIRouter(tags=["ws"])

_TICKET_PREFIX = "ws:ticket:"
_TICKET_TTL_SECONDS = 30
_CHANNEL_PREFIX = "ws:alerts:user:"
_PING_INTERVAL_SECONDS = 30.0
_PUBSUB_POLL_TIMEOUT = 1.0


class _UUIDEncoder(json.JSONEncoder):
    """JSON encoder that serialises UUIDs to their string form."""

    def default(self, o: Any) -> Any:  # noqa: D401 - JSONEncoder signature
        if isinstance(o, UUID):
            return str(o)
        return super().default(o)


def _channel_for(user_id: UUID) -> str:
    return f"{_CHANNEL_PREFIX}{user_id}"


async def publish_alert(redis: Redis, user_id: UUID, event: dict[str, Any]) -> int:
    """Publish an alert event to the per-user channel.

    Returns the number of subscribers that received the message (as reported
    by Redis). Callers (e.g. the notification dispatcher) can use this to
    decide whether to fall back to push notifications.
    """

    payload = json.dumps(event, cls=_UUIDEncoder)
    result = await redis.publish(_channel_for(user_id), payload)
    return int(result)


@router.post("/api/ws/ticket")
async def create_ticket(
    current_user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    """Mint a single-use ticket for opening the alerts WebSocket."""

    ticket = secrets.token_urlsafe(32)
    key = f"{_TICKET_PREFIX}{ticket}"
    # NX ensures we never clobber an existing (astronomically unlikely) entry.
    await redis.set(key, str(current_user.id), ex=_TICKET_TTL_SECONDS, nx=True)
    return {"ticket": ticket, "expires_in": _TICKET_TTL_SECONDS}


async def _consume_ticket(redis: Redis, ticket: str) -> UUID | None:
    """Atomically fetch-and-delete a ticket; return the owning user_id or None."""

    raw = await redis.getdel(f"{_TICKET_PREFIX}{ticket}")
    if raw is None:
        return None
    value = raw.decode() if isinstance(raw, bytes) else str(raw)
    try:
        return UUID(value)
    except ValueError:
        return None


@router.websocket("/ws/alerts")
async def ws_alerts(
    websocket: WebSocket,
    redis: Redis = Depends(get_redis),
) -> None:
    """Stream per-user alert events over a Redis pubsub-backed WebSocket."""

    await websocket.accept()

    ticket = websocket.query_params.get("ticket")
    if not ticket:
        await websocket.close(code=4401)
        return

    user_id = await _consume_ticket(redis, ticket)
    if user_id is None:
        await websocket.close(code=4401)
        return

    pubsub = redis.pubsub()
    channel = _channel_for(user_id)
    await pubsub.subscribe(channel)

    last_ping = asyncio.get_event_loop().time()
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=_PUBSUB_POLL_TIMEOUT,
            )
            if message is not None:
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode()
                if isinstance(data, str):
                    await websocket.send_text(data)

            now = asyncio.get_event_loop().time()
            if now - last_ping >= _PING_INTERVAL_SECONDS:
                await websocket.send_text(json.dumps({"type": "ping"}))
                last_ping = now
    except WebSocketDisconnect:
        pass
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel)
        with contextlib.suppress(Exception):
            await pubsub.aclose()  # type: ignore[no-untyped-call]
        with contextlib.suppress(Exception):
            await websocket.close()


__all__ = ["router", "publish_alert"]
