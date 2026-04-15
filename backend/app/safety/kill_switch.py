"""Kill switch service (M3-19).

A per-user flag stored in Redis under ``safety:kill_switch:{user_id}``.
Activation and deactivation are single-round-trip Redis operations so the
<500ms activation AC is met with margin (the network RTT dominates).

Activation is also audit-logged via :class:`AuditService` so the flip can
be traced after the fact.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from backend.app.services.audit import AuditService
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

KILL_SWITCH_KEY_PREFIX = "safety:kill_switch:"
EVENT_KILL_SWITCH_ACTIVATED = "safety.kill_switch_activated"
EVENT_KILL_SWITCH_DEACTIVATED = "safety.kill_switch_deactivated"


class KillSwitchService:
    """Per-user Redis-backed kill switch with audit trail."""

    def __init__(self, redis: Redis, session: AsyncSession) -> None:
        self._redis = redis
        self._audit = AuditService(session)

    @staticmethod
    def _key(user_id: UUID) -> str:
        return f"{KILL_SWITCH_KEY_PREFIX}{user_id}"

    async def activate(self, user_id: UUID) -> dict[str, Any]:
        """Flip the kill switch on. Idempotent — re-activating is a no-op."""

        await self._redis.set(self._key(user_id), "1")
        await self._audit.record(
            event_type=EVENT_KILL_SWITCH_ACTIVATED,
            user_id=user_id,
            event_data={"active": True},
        )
        return {"active": True}

    async def deactivate(self, user_id: UUID) -> None:
        """Flip the kill switch off. Idempotent."""

        await self._redis.delete(self._key(user_id))
        await self._audit.record(
            event_type=EVENT_KILL_SWITCH_DEACTIVATED,
            user_id=user_id,
            event_data={"active": False},
        )

    async def is_active(self, user_id: UUID) -> bool:
        value = await self._redis.get(self._key(user_id))
        return value is not None


__all__ = [
    "EVENT_KILL_SWITCH_ACTIVATED",
    "EVENT_KILL_SWITCH_DEACTIVATED",
    "KILL_SWITCH_KEY_PREFIX",
    "KillSwitchService",
]
