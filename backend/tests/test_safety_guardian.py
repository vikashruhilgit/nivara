"""Unit tests for :class:`SafetyGuardian` (M3-19).

Covers the acceptance criteria that can be verified in isolation: position
size limits, daily loss, max drawdown, and duplicate-order suppression. The
guardian writes audit rows via :class:`AuditService`; because audit_log uses
Postgres-only column types we substitute a minimal in-memory fake session
that records ``add(...)`` calls — no real DB required.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Any
from uuid import uuid4

import fakeredis.aioredis
import pytest
import pytest_asyncio
from backend.app.models.audit_log import AuditLog
from backend.app.safety.guardian import (
    CODE_DAILY_LOSS,
    CODE_DUPLICATE_ORDER,
    CODE_MAX_DRAWDOWN,
    CODE_POSITION_SIZE,
    EVENT_SAFETY_VIOLATION,
    SafetyGuardian,
)


class _FakeSession:
    """Captures ``AuditLog`` rows added by AuditService without touching DB."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, entry: Any) -> None:
        self.added.append(entry)

    async def flush(self) -> None:  # pragma: no cover - no-op
        return None


def _audit_rows(session: _FakeSession) -> list[AuditLog]:
    return [e for e in session.added if isinstance(e, AuditLog)]


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def guardian(session: _FakeSession) -> SafetyGuardian:
    # The guardian only uses ``session.add`` / ``session.flush`` — mypy will
    # grumble but the duck-type is compatible at runtime.
    return SafetyGuardian(session=session)  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def redis() -> AsyncGenerator[fakeredis.aioredis.FakeRedis, None]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


# ---------------------------------------------------------------- position size


async def test_position_size_rejected_above_10_percent(
    guardian: SafetyGuardian, session: _FakeSession
) -> None:
    """AC #1: proposed value > 10 % of portfolio is rejected + audited."""
    decision = await guardian.validate_position_size(
        user_id=uuid4(),
        instrument_id=uuid4(),
        proposed_value=Decimal("1500"),
        portfolio_value=Decimal("10000"),  # 15 % > default 10 % cap
    )
    assert decision.allowed is False
    assert decision.code == CODE_POSITION_SIZE
    rows = _audit_rows(session)
    assert len(rows) == 1
    assert rows[0].event_type == EVENT_SAFETY_VIOLATION
    assert rows[0].event_data is not None
    assert rows[0].event_data["code"] == CODE_POSITION_SIZE


async def test_position_size_accepted_within_limit(
    guardian: SafetyGuardian, session: _FakeSession
) -> None:
    """Proposed value at the cap must not be rejected and must not audit."""
    decision = await guardian.validate_position_size(
        user_id=uuid4(),
        instrument_id=uuid4(),
        proposed_value=Decimal("1000"),  # exactly 10 %
        portfolio_value=Decimal("10000"),
    )
    assert decision.allowed is True
    assert _audit_rows(session) == []


async def test_position_size_configurable_max_pct(
    guardian: SafetyGuardian, session: _FakeSession
) -> None:
    """AC #2: a 15 % cap lets a 12 % proposal through but rejects 16 %."""
    ok = await guardian.validate_position_size(
        user_id=uuid4(),
        instrument_id=uuid4(),
        proposed_value=Decimal("1200"),
        portfolio_value=Decimal("10000"),
        max_pct=Decimal("0.15"),
    )
    assert ok.allowed is True

    bad = await guardian.validate_position_size(
        user_id=uuid4(),
        instrument_id=uuid4(),
        proposed_value=Decimal("1600"),
        portfolio_value=Decimal("10000"),
        max_pct=Decimal("0.15"),
    )
    assert bad.allowed is False
    assert bad.code == CODE_POSITION_SIZE


# ---------------------------------------------------------------- daily loss


async def test_daily_loss_breach_at_2_percent(
    guardian: SafetyGuardian, session: _FakeSession
) -> None:
    """AC #3: 2 % drop from start-of-day triggers the daily loss circuit."""
    decision = await guardian.check_daily_loss(
        user_id=uuid4(),
        current_value=Decimal("9800"),
        start_of_day_value=Decimal("10000"),
    )
    assert decision.allowed is False
    assert decision.code == CODE_DAILY_LOSS
    rows = _audit_rows(session)
    assert len(rows) == 1
    assert rows[0].event_data is not None
    assert rows[0].event_data["code"] == CODE_DAILY_LOSS


async def test_daily_loss_ok_when_within_limit(
    guardian: SafetyGuardian, session: _FakeSession
) -> None:
    decision = await guardian.check_daily_loss(
        user_id=uuid4(),
        current_value=Decimal("9850"),  # 1.5 % — under 2 %
        start_of_day_value=Decimal("10000"),
    )
    assert decision.allowed is True
    assert _audit_rows(session) == []


# ---------------------------------------------------------------- max drawdown


async def test_max_drawdown_breach_at_12_percent(
    guardian: SafetyGuardian, session: _FakeSession
) -> None:
    """AC #4: 12 % drop from peak breaches default 10 % drawdown limit."""
    decision = await guardian.check_max_drawdown(
        user_id=uuid4(),
        current_value=Decimal("8800"),
        peak_value=Decimal("10000"),
    )
    assert decision.allowed is False
    assert decision.code == CODE_MAX_DRAWDOWN
    rows = _audit_rows(session)
    assert len(rows) == 1
    assert rows[0].event_data is not None
    assert rows[0].event_data["code"] == CODE_MAX_DRAWDOWN


async def test_max_drawdown_ok_within_limit(
    guardian: SafetyGuardian, session: _FakeSession
) -> None:
    decision = await guardian.check_max_drawdown(
        user_id=uuid4(),
        current_value=Decimal("9500"),  # 5 % — under 10 %
        peak_value=Decimal("10000"),
    )
    assert decision.allowed is True


# --------------------------------------------------------------- duplicate order


async def test_duplicate_order_blocked_within_window(
    guardian: SafetyGuardian,
    session: _FakeSession,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """AC #7: the same (symbol, side, qty) inside 60 s is a duplicate."""
    user_id = uuid4()
    first = await guardian.check_duplicate_order(
        redis,
        user_id=user_id,
        symbol="AAPL",
        side="buy",
        qty=Decimal("10"),
    )
    assert first.allowed is True

    await guardian.record_order(
        redis, user_id=user_id, symbol="AAPL", side="buy", qty=Decimal("10")
    )

    second = await guardian.check_duplicate_order(
        redis,
        user_id=user_id,
        symbol="AAPL",
        side="buy",
        qty=Decimal("10"),
    )
    assert second.allowed is False
    assert second.code == CODE_DUPLICATE_ORDER
    rows = _audit_rows(session)
    assert any(r.event_data and r.event_data.get("code") == CODE_DUPLICATE_ORDER for r in rows)


async def test_duplicate_order_allowed_after_window_expires(
    guardian: SafetyGuardian,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Entries older than the window are treated as fresh orders again.

    We simulate the passage of time by rewriting the sorted-set score to a
    moment outside the 60 s window — no ``freezegun`` dependency needed.
    """
    user_id = uuid4()
    symbol, side, qty = "AAPL", "buy", Decimal("10")
    await guardian.record_order(redis, user_id=user_id, symbol=symbol, side=side, qty=qty)

    key = SafetyGuardian._orders_key(user_id)
    member = SafetyGuardian._order_member(symbol, side, qty)
    # Push the score 5 minutes into the past.
    await redis.zadd(key, {member: time.time() - 300})

    decision = await guardian.check_duplicate_order(
        redis, user_id=user_id, symbol=symbol, side=side, qty=qty, window_seconds=60
    )
    assert decision.allowed is True


async def test_duplicate_order_distinguishes_side_and_qty(
    guardian: SafetyGuardian,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """A different side or quantity is NOT a duplicate."""
    user_id = uuid4()
    await guardian.record_order(
        redis, user_id=user_id, symbol="AAPL", side="buy", qty=Decimal("10")
    )
    # Different side.
    different_side = await guardian.check_duplicate_order(
        redis, user_id=user_id, symbol="AAPL", side="sell", qty=Decimal("10")
    )
    assert different_side.allowed is True
    # Different qty.
    different_qty = await guardian.check_duplicate_order(
        redis, user_id=user_id, symbol="AAPL", side="buy", qty=Decimal("11")
    )
    assert different_qty.allowed is True
