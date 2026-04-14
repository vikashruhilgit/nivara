"""Audit log writer.

Thin helper around the append-only ``audit_log`` table. Callers should never
construct :class:`AuditLog` rows directly — going through this service keeps
event-type strings centralized and makes it easy to add observability hooks
(metrics, traces) later.

Immutability is enforced at the DB layer by migration ``002_audit_immutability``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from backend.app.models.audit_log import AuditLog
from sqlalchemy.ext.asyncio import AsyncSession

# Canonical event-type constants. Add new entries here rather than hard-coding
# string literals at call sites.
EVENT_PORTFOLIO_SYNC = "portfolio.sync"


class AuditService:
    """Async append-only audit writer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        event_type: str,
        user_id: UUID | None = None,
        event_data: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            user_id=user_id,
            event_type=event_type,
            event_data=event_data,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry
