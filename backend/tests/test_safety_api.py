"""Integration tests for the safety API (M3-19).

The production ``audit_log`` table uses Postgres-only column types, so rather
than standing up a throwaway Postgres per test we inject a fake implementation
of :class:`AuditLogQuery` that returns rows from an in-memory list. This keeps
the HTTP surface under test while avoiding SQLAlchemy/aiosqlite quirks around
shared-session state across ASGI request boundaries.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import fakeredis.aioredis
import pytest_asyncio
from backend.app.api.safety import _audit_query
from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.main import app
from backend.app.models.audit_log import AuditLog
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from backend.app.safety.audit_query import AuditLogQuery
from backend.app.schemas.safety import AuditLogEntry, AuditLogPage
from httpx import ASGITransport, AsyncClient


class _FakeAuditQuery(AuditLogQuery):
    """In-memory stand-in that the endpoint can call directly."""

    def __init__(self) -> None:  # intentionally skip parent init (no session)
        self.rows: list[AuditLog] = []

    def add(
        self,
        *,
        user_id: UUID,
        event_type: str,
        event_data: dict[str, object] | None = None,
    ) -> None:
        self.rows.append(
            AuditLog(
                id=uuid4(),
                user_id=user_id,
                event_type=event_type,
                event_data=event_data,
                occurred_at=datetime.now(UTC),
            )
        )

    def _for_user(self, user_id: UUID) -> list[AuditLog]:
        return [r for r in self.rows if r.user_id == user_id]

    async def recent_safety_events(self, *, user_id: UUID, limit: int = 10) -> Sequence[AuditLog]:
        matches = [r for r in self._for_user(user_id) if r.event_type.startswith("safety.")]
        matches.sort(key=lambda r: r.occurred_at, reverse=True)
        return matches[:limit]

    async def page(
        self,
        *,
        user_id: UUID,
        page: int,
        per_page: int,
        event_type: str | None,
    ) -> AuditLogPage:
        matches = self._for_user(user_id)
        if event_type is not None:
            matches = [r for r in matches if r.event_type == event_type]
        matches.sort(key=lambda r: r.occurred_at, reverse=True)
        total = len(matches)
        offset = (page - 1) * per_page
        window = matches[offset : offset + per_page]
        items = [AuditLogEntry.model_validate(row) for row in window]
        return AuditLogPage(items=items, page=page, per_page=per_page, total=total)


@pytest_asyncio.fixture
async def api() -> AsyncGenerator[tuple[AsyncClient, _FakeAuditQuery, User], None]:
    dummy_user = User(id=uuid4(), email="s@example.com", password_hash="x", is_active=True)
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    fake_query = _FakeAuditQuery()

    async def _session_override() -> AsyncGenerator[None, None]:
        # Kill-switch service still needs a session but only calls ``commit``
        # and ``add``; a minimal stub keeps us off the DB entirely.
        yield _StubSession()  # type: ignore[misc]

    async def _user_override() -> User:
        return dummy_user

    def _redis_override() -> fakeredis.aioredis.FakeRedis:
        return fake_redis

    def _audit_override() -> AuditLogQuery:
        return fake_query

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_redis] = _redis_override
    app.dependency_overrides[_audit_query] = _audit_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, fake_query, dummy_user

    app.dependency_overrides.clear()
    await fake_redis.aclose()


class _StubSession:
    """Captures ``add`` / ``commit`` / ``flush`` from kill-switch service."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, entry: object) -> None:
        self.added.append(entry)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


async def test_activate_kill_switch_returns_latency_and_active(
    api: tuple[AsyncClient, _FakeAuditQuery, User],
) -> None:
    """AC #5: kill switch activates in <500 ms and reports active=true."""
    client, _query, _user = api
    resp = await client.post("/api/safety/kill-switch")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active"] is True
    assert body["latency_ms"] < 500.0


async def test_status_reflects_kill_switch(
    api: tuple[AsyncClient, _FakeAuditQuery, User],
) -> None:
    """AC #9: GET /status reports kill switch + default limits."""
    client, _query, _user = api
    pre = await client.get("/api/safety/status")
    assert pre.status_code == 200
    assert pre.json()["kill_switch_active"] is False

    await client.post("/api/safety/kill-switch")
    post = await client.get("/api/safety/status")
    assert post.status_code == 200
    body = post.json()
    assert body["kill_switch_active"] is True
    assert body["limits"]["max_position_size_pct"] == "0.10"
    assert body["limits"]["daily_loss_pct"] == "0.02"
    assert body["limits"]["max_drawdown_pct"] == "0.10"


async def test_audit_log_pagination_after_violation(
    api: tuple[AsyncClient, _FakeAuditQuery, User],
) -> None:
    """AC #8: audit-log endpoint paginates the captured rows."""
    client, query, user = api
    for _ in range(3):
        query.add(
            user_id=user.id,
            event_type="safety.violation",
            event_data={"code": "position_size_exceeded"},
        )
    # Noise from another user must not leak into this user's page.
    query.add(user_id=uuid4(), event_type="safety.violation")

    resp = await client.get("/api/safety/audit-log?page=1&per_page=2")
    assert resp.status_code == 200, resp.text
    page = resp.json()
    assert page["total"] == 3
    assert page["page"] == 1
    assert page["per_page"] == 2
    assert len(page["items"]) == 2
    for item in page["items"]:
        assert item["event_type"] == "safety.violation"

    filt = await client.get("/api/safety/audit-log?event_type=safety.violation")
    assert filt.status_code == 200
    assert filt.json()["total"] == 3


async def test_status_includes_recent_violations(
    api: tuple[AsyncClient, _FakeAuditQuery, User],
) -> None:
    """AC #9 + AC #10: recent safety events surface in /status."""
    client, query, user = api
    query.add(
        user_id=user.id,
        event_type="safety.violation",
        event_data={"code": "daily_loss_exceeded"},
    )
    resp = await client.get("/api/safety/status")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["recent_violations"]) == 1
    assert body["recent_violations"][0]["event_type"] == "safety.violation"
