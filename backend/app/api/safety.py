"""Safety API routes (M3-19).

Endpoints::

    POST   /api/safety/kill-switch    — activate
    DELETE /api/safety/kill-switch    — deactivate
    GET    /api/safety/status         — kill-switch + limits + recent violations
    GET    /api/safety/audit-log      — paginated audit-log view

All routes require bearer-token authentication.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from backend.app.safety.audit_query import AuditLogQuery
from backend.app.safety.kill_switch import KillSwitchService
from backend.app.schemas.safety import (
    AuditLogPage,
    KillSwitchResponse,
    SafetyLimitsConfig,
    SafetyStatus,
)
from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/safety", tags=["safety"])


def _kill_switch_service(
    redis: Redis = Depends(get_redis),
    session: AsyncSession = Depends(get_session),
) -> KillSwitchService:
    return KillSwitchService(redis=redis, session=session)


def _audit_query(session: AsyncSession = Depends(get_session)) -> AuditLogQuery:
    """Audit-log query service — overridden in tests to bypass DB specifics."""

    return AuditLogQuery(session=session)


@router.post("/kill-switch", response_model=KillSwitchResponse)
async def activate_kill_switch(
    current_user: User = Depends(get_current_user),
    service: KillSwitchService = Depends(_kill_switch_service),
    session: AsyncSession = Depends(get_session),
) -> KillSwitchResponse:
    """Activate the per-user kill switch; returns latency for observability."""

    start = time.perf_counter()
    await service.activate(current_user.id)
    await session.commit()
    latency_ms = (time.perf_counter() - start) * 1000.0
    return KillSwitchResponse(
        active=True,
        toggled_at=datetime.now(UTC),
        latency_ms=latency_ms,
    )


@router.delete("/kill-switch", response_model=KillSwitchResponse)
async def deactivate_kill_switch(
    current_user: User = Depends(get_current_user),
    service: KillSwitchService = Depends(_kill_switch_service),
    session: AsyncSession = Depends(get_session),
) -> KillSwitchResponse:
    """Deactivate the per-user kill switch."""

    start = time.perf_counter()
    await service.deactivate(current_user.id)
    await session.commit()
    latency_ms = (time.perf_counter() - start) * 1000.0
    return KillSwitchResponse(
        active=False,
        toggled_at=datetime.now(UTC),
        latency_ms=latency_ms,
    )


@router.get("/status", response_model=SafetyStatus)
async def get_status(
    current_user: User = Depends(get_current_user),
    service: KillSwitchService = Depends(_kill_switch_service),
    audit: AuditLogQuery = Depends(_audit_query),
) -> SafetyStatus:
    """Return kill-switch state, default limits, and last 10 safety events."""

    active = await service.is_active(current_user.id)
    rows = await audit.recent_safety_events(user_id=current_user.id, limit=10)
    recent = [
        {
            "id": str(row.id),
            "event_type": row.event_type,
            "event_data": row.event_data,
            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        }
        for row in rows
    ]
    return SafetyStatus(
        kill_switch_active=active,
        limits=SafetyLimitsConfig(),
        recent_violations=recent,
    )


@router.get("/audit-log", response_model=AuditLogPage)
async def get_audit_log(
    current_user: User = Depends(get_current_user),
    audit: AuditLogQuery = Depends(_audit_query),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    event_type: str | None = Query(None),
) -> AuditLogPage:
    """Paginated audit-log view scoped to the current user."""

    return await audit.page(
        user_id=current_user.id,
        page=page,
        per_page=per_page,
        event_type=event_type,
    )


__all__ = ["router"]
