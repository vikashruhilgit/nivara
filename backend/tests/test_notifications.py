"""Tests for the notifications + devices APIs and push/email channels.

The ``notifications`` and ``device_tokens`` tables use Postgres-only column
types (JSONB, native enums) so we substitute an in-memory fake session that
satisfies the small surface the endpoints actually use: ``execute`` with a
``Notification`` or ``DeviceToken`` query, plus ``add`` / ``flush`` /
``commit`` / ``refresh``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.main import app
from backend.app.models.device_tokens import DeviceToken
from backend.app.models.notifications import Notification
from backend.app.models.users import User
from backend.app.notifications.email import EmailChannel, SmtpConfig
from backend.app.notifications.push import EXPO_PUSH_URL, ExpoPushChannel
from httpx import ASGITransport, AsyncClient

# --------------------------------------------------------------------- fakes


class _Result:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._values)

    def scalar_one(self) -> Any:
        return self._values[0]

    def scalar_one_or_none(self) -> Any:
        return self._values[0] if self._values else None


class _FakeSession:
    """In-memory stand-in routing queries by target table string."""

    def __init__(
        self,
        *,
        notifications: list[Notification] | None = None,
        device_tokens: list[DeviceToken] | None = None,
        users: list[User] | None = None,
    ) -> None:
        self.notifications: list[Notification] = notifications or []
        self.device_tokens: list[DeviceToken] = device_tokens or []
        self.users: list[User] = users or []
        self.committed = 0
        self.added: list[Any] = []

    async def execute(self, stmt: Any) -> _Result:
        sql = str(stmt).lower()

        uuid_binds = _extract_uuid_binds(stmt)
        uuid_bind = uuid_binds[0] if uuid_binds else None
        token_bind = _extract_str_bind(stmt)

        if "count(" in sql and "from notifications" in sql:
            filtered = self._filter_notifications(sql, user_id=uuid_bind)
            return _Result([len(filtered)])
        if "from notifications" in sql:
            # PATCH path: stmt filters by both id and user_id — two binds.
            if "notifications.id = " in sql and len(uuid_binds) >= 2:
                nid, user_id = uuid_binds[0], uuid_binds[1]
                rows = self._filter_notifications(sql, nid=nid, user_id=user_id)
            else:
                rows = self._filter_notifications(sql, user_id=uuid_bind)
            rows.sort(key=lambda n: n.created_at, reverse=True)
            return _Result(rows)
        if "from device_tokens" in sql:
            dt_rows = [
                d
                for d in self.device_tokens
                if (token_bind is None or d.expo_push_token == token_bind)
                and (uuid_bind is None or d.user_id == uuid_bind)
            ]
            return _Result(dt_rows)
        if "from users" in sql:
            u_rows = [u for u in self.users if uuid_bind is None or u.id == uuid_bind]
            return _Result(u_rows)
        return _Result([])

    def _filter_notifications(
        self,
        sql: str,
        *,
        nid: UUID | None = None,
        user_id: UUID | None = None,
    ) -> list[Notification]:
        unread = "read_at is null" in sql
        read = "read_at is not null" in sql
        rows = list(self.notifications)
        if nid is not None:
            rows = [n for n in rows if n.id == nid]
        if user_id is not None:
            rows = [n for n in rows if n.user_id == user_id]
        if unread:
            rows = [n for n in rows if n.read_at is None]
        elif read:
            rows = [n for n in rows if n.read_at is not None]
        return rows

    async def get(self, entity: type[Any], ident: Any) -> Any:
        if entity is User:
            for u in self.users:
                if u.id == ident:
                    return u
        return None

    def add(self, entity: Any) -> None:
        if isinstance(entity, DeviceToken):
            if entity.id is None:
                entity.id = uuid4()
            if getattr(entity, "created_at", None) is None:
                entity.created_at = datetime.now(UTC)
            if getattr(entity, "last_seen_at", None) is None:
                entity.last_seen_at = datetime.now(UTC)
            self.device_tokens.append(entity)
        elif isinstance(entity, Notification):
            if entity.id is None:
                entity.id = uuid4()
            if getattr(entity, "created_at", None) is None:
                entity.created_at = datetime.now(UTC)
            self.notifications.append(entity)
        self.added.append(entity)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed += 1

    async def refresh(self, entity: Any) -> None:
        # Real refresh would re-read DB state; our in-memory representation is
        # already authoritative. Resolve server-side defaults so the response
        # serialises cleanly.
        if isinstance(entity, DeviceToken) and not isinstance(
            getattr(entity, "last_seen_at", None), datetime
        ):
            entity.last_seen_at = datetime.now(UTC)


def _extract_uuid_binds(stmt: Any) -> list[UUID]:
    out: list[UUID] = []
    try:
        compiled = stmt.compile(compile_kwargs={"literal_binds": False})
        for val in compiled.params.values():
            if isinstance(val, UUID):
                out.append(val)
    except Exception:
        return []
    return out


def _extract_str_bind(stmt: Any) -> str | None:
    try:
        compiled = stmt.compile(compile_kwargs={"literal_binds": False})
        for val in compiled.params.values():
            if isinstance(val, str) and len(val) > 0 and not _looks_like_uuid(val):
                return val
    except Exception:
        return None
    return None


def _looks_like_uuid(s: str) -> bool:
    try:
        UUID(s)
        return True
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------- fixtures


def _make_notification(
    user_id: UUID,
    *,
    created_at: datetime,
    read: bool = False,
    title: str = "t",
) -> Notification:
    n = Notification(
        user_id=user_id,
        notification_type="price_alert",
        title=title,
        body="b",
        payload={"k": 1},
    )
    n.id = uuid4()
    n.created_at = created_at
    n.read_at = datetime.now(UTC) if read else None
    n.sent_at = None
    return n


@pytest_asyncio.fixture
async def api() -> AsyncGenerator[tuple[AsyncClient, _FakeSession, User], None]:
    user = User(id=uuid4(), email="u@example.com", password_hash="x", is_active=True)
    session = _FakeSession(users=[user])

    async def _session_override() -> AsyncGenerator[_FakeSession, None]:
        yield session

    async def _user_override() -> User:
        return user

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = _user_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, session, user
    app.dependency_overrides.clear()


# ------------------------------------------------------- GET /api/notifications


async def test_list_notifications_paginated_desc(
    api: tuple[AsyncClient, _FakeSession, User],
) -> None:
    """AC #5: paginated, sorted by created_at DESC."""
    client, session, user = api
    now = datetime.now(UTC)
    session.notifications = [
        _make_notification(user.id, created_at=now - timedelta(minutes=i), title=f"n{i}")
        for i in range(5)
    ]
    resp = await client.get("/api/notifications?page=1&per_page=20")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["per_page"] == 20
    titles = [item["title"] for item in body["items"]]
    assert titles == ["n0", "n1", "n2", "n3", "n4"]  # newest first


async def test_list_notifications_filter_unread(
    api: tuple[AsyncClient, _FakeSession, User],
) -> None:
    """AC #6: ``read=false`` returns only unread rows."""
    client, session, user = api
    now = datetime.now(UTC)
    session.notifications = [
        _make_notification(user.id, created_at=now, read=True, title="read"),
        _make_notification(
            user.id, created_at=now - timedelta(minutes=1), read=False, title="unread"
        ),
    ]
    resp = await client.get("/api/notifications?read=false")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "unread"


# --------------------------------------------- PATCH /api/notifications/{id}/read


async def test_mark_notification_read_sets_read_at_and_is_idempotent(
    api: tuple[AsyncClient, _FakeSession, User],
) -> None:
    """AC #7: PATCH sets ``read_at``; a repeat call returns the same row."""
    client, session, user = api
    n = _make_notification(user.id, created_at=datetime.now(UTC), read=False)
    session.notifications = [n]

    first = await client.patch(f"/api/notifications/{n.id}/read")
    assert first.status_code == 200, first.text
    body1 = first.json()
    assert body1["read_at"] is not None
    original_read_at = body1["read_at"]

    second = await client.patch(f"/api/notifications/{n.id}/read")
    assert second.status_code == 200
    assert second.json()["read_at"] == original_read_at  # unchanged


async def test_mark_notification_read_404_when_other_user(
    api: tuple[AsyncClient, _FakeSession, User],
) -> None:
    """Another user's notification is invisible → 404."""
    client, session, _user = api
    other = _make_notification(uuid4(), created_at=datetime.now(UTC))
    session.notifications = [other]

    resp = await client.patch(f"/api/notifications/{other.id}/read")
    assert resp.status_code == 404


# ------------------------------------------------- POST /api/devices/register


async def test_register_device_creates_row_then_upserts(
    api: tuple[AsyncClient, _FakeSession, User],
) -> None:
    """AC #8: first register → 201 + DeviceToken row. Repeat → upsert same row."""
    client, session, _user = api
    payload = {"expo_push_token": "ExponentPushToken[abc123]", "platform": "ios"}
    first = await client.post("/api/devices/register", json=payload)
    assert first.status_code == 201, first.text
    created = first.json()
    assert created["is_active"] is True
    assert created["platform"] == "ios"
    first_id = created["id"]

    second = await client.post("/api/devices/register", json=payload)
    assert second.status_code == 201
    assert second.json()["id"] == first_id
    assert second.json()["is_active"] is True
    # Only one row total — the second call upserted rather than inserted.
    assert len(session.device_tokens) == 1


# --------------------------------------------------------------- ExpoPushChannel


class _FakeDeviceTokenSession:
    """Minimal session for ExpoPushChannel: only needs ``execute(select(...))``."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(list(self._tokens))


class _CapturingHTTP:
    def __init__(self, status_code: int = 200, payload: Any = None) -> None:
        self._status = status_code
        self._payload = payload if payload is not None else {"data": []}
        self.calls: list[dict[str, Any]] = []

    async def post(
        self,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self.calls.append({"url": url, "json": json, "headers": headers or {}})
        req = httpx.Request("POST", url)
        return httpx.Response(self._status, json=self._payload, request=req)


async def test_expo_push_channel_posts_for_each_device() -> None:
    """AC #2: ExpoPushChannel.send posts one payload per active device."""
    user_id = uuid4()
    notification = Notification(
        user_id=user_id,
        notification_type="price_alert",
        title="Hello",
        body="World",
        payload={"symbol": "AAPL"},
    )
    notification.id = uuid4()
    notification.created_at = datetime.now(UTC)

    tokens = ["ExponentPushToken[tokA]", "ExponentPushToken[tokB]"]
    session = _FakeDeviceTokenSession(tokens)
    http = _CapturingHTTP(status_code=200, payload={"data": [{"status": "ok"}]})
    channel = ExpoPushChannel(
        session=session,  # type: ignore[arg-type]
        http_client=http,  # type: ignore[arg-type]
        access_token="secret",
    )
    ok = await channel.send(notification)

    assert ok is True
    assert len(http.calls) == 1
    call = http.calls[0]
    assert call["url"] == EXPO_PUSH_URL
    assert call["headers"]["Authorization"] == "Bearer secret"
    messages = call["json"]
    assert isinstance(messages, list)
    assert {m["to"] for m in messages} == set(tokens)
    for msg in messages:
        assert msg["title"] == "Hello"
        assert msg["body"] == "World"
        assert msg["data"] == {"symbol": "AAPL"}


async def test_expo_push_channel_returns_false_when_expo_reports_errors() -> None:
    user_id = uuid4()
    notification = Notification(
        user_id=user_id,
        notification_type="price_alert",
        title="t",
        body="b",
        payload={},
    )
    notification.id = uuid4()
    session = _FakeDeviceTokenSession(["ExponentPushToken[x]"])
    http = _CapturingHTTP(status_code=200, payload={"errors": [{"code": "DeviceNotRegistered"}]})
    channel = ExpoPushChannel(
        session=session,  # type: ignore[arg-type]
        http_client=http,  # type: ignore[arg-type]
    )
    assert await channel.send(notification) is False


async def test_expo_push_channel_no_devices_returns_false() -> None:
    user_id = uuid4()
    notification = Notification(
        user_id=user_id,
        notification_type="price_alert",
        title="t",
        body="b",
        payload={},
    )
    session = _FakeDeviceTokenSession([])
    http = _CapturingHTTP()
    channel = ExpoPushChannel(
        session=session,  # type: ignore[arg-type]
        http_client=http,  # type: ignore[arg-type]
    )
    assert await channel.send(notification) is False


# ------------------------------------------------------------------ EmailChannel


async def test_email_channel_no_config_returns_false() -> None:
    """AC #10/#11: no SMTP config → send gracefully returns False."""
    session = _FakeSession()
    channel = EmailChannel(session=session, smtp_config=None)  # type: ignore[arg-type]
    notification = Notification(
        user_id=uuid4(),
        notification_type="system",
        title="t",
        body="b",
        payload={},
    )
    notification.id = uuid4()
    assert await channel.send(notification) is False


async def test_email_channel_with_config_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    """With SMTP config (mocked smtplib) → returns True."""
    import smtplib

    sent_messages: list[Any] = []

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int = 0) -> None:
            self.host = host
            self.port = port

        def __enter__(self) -> _FakeSMTP:
            return self

        def __exit__(self, *a: Any) -> None:
            return None

        def ehlo(self) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, u: str, p: str) -> None:  # noqa: ARG002
            return None

        def send_message(self, msg: Any) -> None:
            sent_messages.append(msg)

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    user_id = uuid4()
    user = User(id=user_id, email="recipient@example.com", password_hash="x", is_active=True)
    session = _FakeSession(users=[user])
    cfg = SmtpConfig(
        host="smtp.example.com",
        port=587,
        username="u",
        password="p",
        from_email="from@example.com",
    )
    channel = EmailChannel(session=session, smtp_config=cfg)  # type: ignore[arg-type]
    notification = Notification(
        user_id=user_id,
        notification_type="system",
        title="Hello",
        body="World",
        payload={},
    )
    notification.id = uuid4()

    ok = await channel.send(notification)
    assert ok is True
    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert msg["To"] == "recipient@example.com"
    assert msg["Subject"] == "Hello"


# Silence unused-import warnings for AsyncMock in this module — kept as a
# convenience for future tests that want to stub specific session methods.
_ = AsyncMock
