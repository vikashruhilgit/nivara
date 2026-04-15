"""Tests for the real-time alerts WebSocket (M3-20, Subtask 6).

Uses FastAPI's synchronous :class:`TestClient` (starlette) for WebSocket
support — the async :class:`httpx.AsyncClient` used elsewhere doesn't have a
``websocket_connect`` helper. Redis is stubbed with ``fakeredis`` so pubsub
end-to-end round trips work in-process.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Generator
from typing import Any
from uuid import uuid4

import fakeredis.aioredis
import pytest
import pytest_asyncio
from backend.app.api.ws_alerts import publish_alert
from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.main import app
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

# ---------------------------------------------------------------- fixtures


class _StubSession:
    """Minimal session — none of the WS endpoints actually query the DB."""

    async def execute(self, _stmt: Any) -> Any:  # pragma: no cover - defensive
        raise AssertionError("WS endpoints must not touch the DB in these tests")

    async def commit(self) -> None:  # pragma: no cover
        return None


@pytest_asyncio.fixture
async def fake_redis_ws() -> AsyncGenerator[fakeredis.aioredis.FakeRedis, None]:
    """Shared fakeredis instance — publisher + WS handler must see the same one."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def user() -> User:
    return User(id=uuid4(), email="ws@example.com", password_hash="x", is_active=True)


@pytest.fixture
def ws_client(
    user: User,
    fake_redis_ws: fakeredis.aioredis.FakeRedis,
) -> Generator[TestClient, None, None]:
    """Build a TestClient with overrides for current user + redis."""

    async def _session_override() -> AsyncGenerator[_StubSession, None]:
        yield _StubSession()

    async def _user_override() -> User:
        return user

    def _redis_override() -> fakeredis.aioredis.FakeRedis:
        return fake_redis_ws

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_redis] = _redis_override

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------- tickets + WS


def test_create_ticket_returns_ticket_and_ttl(ws_client: TestClient) -> None:
    resp = ws_client.post("/api/ws/ticket")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["ticket"], str) and len(body["ticket"]) > 16
    assert body["expires_in"] == 30


def test_ws_alerts_without_ticket_is_closed(ws_client: TestClient) -> None:
    """WS with no ticket query param is closed with code 4401."""
    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        ws_client.websocket_connect("/ws/alerts") as ws,
    ):
        # Receiving from a closed socket raises WebSocketDisconnect.
        ws.receive_text()
    assert excinfo.value.code == 4401


def test_ws_alerts_ticket_delivers_published_payload(
    ws_client: TestClient,
    user: User,
    fake_redis_ws: fakeredis.aioredis.FakeRedis,
) -> None:
    """AC #9: connect with a ticket, then publish → the payload is delivered."""
    ticket = ws_client.post("/api/ws/ticket").json()["ticket"]

    event = {"type": "price_alert", "symbol": "AAPL", "user_id": str(user.id)}

    with ws_client.websocket_connect(f"/ws/alerts?ticket={ticket}") as ws:
        # Publish on the SAME event loop that owns the WS handler + fakeredis
        # subscriber queue. fakeredis pubsub delivery uses asyncio.Queue
        # instances bound to the subscriber's loop, so a cross-loop
        # publish (e.g. from asyncio.new_event_loop()) silently never
        # arrives. Using the TestClient's anyio portal runs publish_alert
        # inside the server task's loop, which is where the subscribe()
        # call registered its queue.
        delivered: dict[str, Any] | None = None
        for _ in range(20):
            ws.portal.call(publish_alert, fake_redis_ws, user.id, event)
            try:
                raw = ws.receive_text()
            except Exception:  # noqa: S112 - retry-on-any for WS pubsub race
                continue
            payload = json.loads(raw)
            if payload.get("type") != "ping":
                delivered = payload
                break

        assert delivered is not None, "WS client never received the published event"
        assert delivered["type"] == "price_alert"
        assert delivered["symbol"] == "AAPL"
        assert delivered["user_id"] == str(user.id)
