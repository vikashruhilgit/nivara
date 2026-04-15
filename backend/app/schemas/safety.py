"""Pydantic v2 schemas for the safety layer (M3-19).

These models cover:

* :class:`SafetyDecision` — return value from any guardian check.
* :class:`SafetyLimitsConfig` — configurable per-user safety limits.
* :class:`SafetyStatus` — kill-switch + limits + recent violations payload.
* :class:`AuditLogEntry`, :class:`AuditLogPage` — paginated audit-log views.
* :class:`KillSwitchResponse` — kill-switch toggle response with latency.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SafetyDecision(BaseModel):
    """Outcome of a single safety check.

    ``allowed`` is ``True`` when the proposed action is within limits. When
    ``allowed`` is ``False``, ``reason`` and ``code`` carry a human-readable
    explanation and a stable machine code respectively. ``details`` carries
    structured context (proposed value, limit, observed value, ...).
    """

    allowed: bool
    reason: str | None = None
    code: str | None = None
    details: dict[str, Any] | None = None


class SafetyLimitsConfig(BaseModel):
    """Per-user safety limit configuration.

    Defaults match the brief: 2 % daily loss, 10 % max drawdown, 10 % max
    position size. Validators enforce sane minimums / maximums so the API
    cannot accept obviously broken values.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    daily_loss_pct: Decimal = Field(default=Decimal("0.02"))
    max_drawdown_pct: Decimal = Field(default=Decimal("0.10"))
    max_position_size_pct: Decimal = Field(default=Decimal("0.10"))

    @field_validator("daily_loss_pct")
    @classmethod
    def _validate_daily_loss(cls, value: Decimal) -> Decimal:
        if value < Decimal("0.01"):
            raise ValueError("daily_loss_pct must be >= 0.01")
        return value

    @field_validator("max_drawdown_pct")
    @classmethod
    def _validate_drawdown(cls, value: Decimal) -> Decimal:
        if value < Decimal("0.05"):
            raise ValueError("max_drawdown_pct must be >= 0.05")
        return value

    @field_validator("max_position_size_pct")
    @classmethod
    def _validate_position_size(cls, value: Decimal) -> Decimal:
        if value > Decimal("0.25"):
            raise ValueError("max_position_size_pct must be <= 0.25")
        return value


class SafetyStatus(BaseModel):
    """Aggregate safety status returned by ``GET /api/safety/status``."""

    kill_switch_active: bool
    limits: SafetyLimitsConfig
    recent_violations: list[dict[str, Any]] = Field(default_factory=list)


class AuditLogEntry(BaseModel):
    """Single audit-log row, for API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    event_data: dict[str, Any] | None = None
    occurred_at: datetime


class AuditLogPage(BaseModel):
    """Paginated audit-log payload for ``GET /api/safety/audit-log``."""

    items: list[AuditLogEntry]
    page: int
    per_page: int
    total: int


class KillSwitchResponse(BaseModel):
    """Response from kill-switch activation/deactivation."""

    active: bool
    toggled_at: datetime
    latency_ms: float


__all__ = [
    "AuditLogEntry",
    "AuditLogPage",
    "KillSwitchResponse",
    "SafetyDecision",
    "SafetyLimitsConfig",
    "SafetyStatus",
]
