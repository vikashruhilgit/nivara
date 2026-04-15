"""Audit-log query service for the safety API.

Isolating the audit-log read paths behind a small service lets tests swap in
an in-memory fake without having to set up a full Postgres-compatible schema
(``audit_log`` uses JSONB, INET, and PG_UUID column types).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from backend.app.models.audit_log import AuditLog
from backend.app.schemas.safety import AuditLogEntry, AuditLogPage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class AuditLogQuery:
    """Thin async read-only accessor for ``audit_log`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def recent_safety_events(self, *, user_id: UUID, limit: int = 10) -> Sequence[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.user_id == user_id,
                AuditLog.event_type.like("safety.%"),
            )
            .order_by(AuditLog.occurred_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def page(
        self,
        *,
        user_id: UUID,
        page: int,
        per_page: int,
        event_type: str | None,
    ) -> AuditLogPage:
        filters = [AuditLog.user_id == user_id]
        if event_type is not None:
            filters.append(AuditLog.event_type == event_type)

        total_stmt = select(func.count()).select_from(AuditLog).where(*filters)
        total = int((await self._session.execute(total_stmt)).scalar_one())

        offset = (page - 1) * per_page
        rows_stmt = (
            select(AuditLog)
            .where(*filters)
            .order_by(AuditLog.occurred_at.desc())
            .offset(offset)
            .limit(per_page)
        )
        rows = (await self._session.execute(rows_stmt)).scalars().all()
        items = [AuditLogEntry.model_validate(row) for row in rows]
        return AuditLogPage(items=items, page=page, per_page=per_page, total=total)


__all__ = ["AuditLogQuery"]
