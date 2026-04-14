"""Tests for :mod:`backend.app.services.corporate_actions`.

``price_history`` is Postgres-partitioned and ``corporate_actions`` uses a
native enum — both awkward for the in-memory SQLite fixtures the rest of
the suite uses. We therefore mock the :class:`AsyncSession` and focus on
the service-level contract:

* ``detect_from_adjustment_factor`` is a no-op at factor == 1 and records a
  split row otherwise.
* ``detect_broker_position_anomaly`` ignores qty changes explained by
  orders and flags those that aren't.
* ``apply_split`` is idempotent (skipped when ``APPLIED_MARKER`` already in
  notes), issues a bulk UPDATE on ``price_history``, invalidates cache keys
  under ``tech:{instrument_id}:*``, and writes an audit log row.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import fakeredis.aioredis
import pytest
from backend.app.models.corporate_actions import CorporateAction
from backend.app.services.corporate_actions import (
    APPLIED_MARKER,
    FLAGGED_MARKER,
    CorporateActionsService,
    SplitDetection,
)

pytestmark = pytest.mark.asyncio


def _mock_session(added: list[object] | None = None) -> MagicMock:
    """Minimal async session that collects ``session.add`` targets and awaits."""
    tracker = added if added is not None else []
    session = MagicMock()

    def _add(obj: object) -> None:
        tracker.append(obj)

    session.add = MagicMock(side_effect=_add)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.get = AsyncMock()
    return session


# ---------------------------------------------------- adjustment-factor detection


async def test_detect_factor_one_is_noop() -> None:
    session = _mock_session()
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    svc = CorporateActionsService(session=session, redis=redis)

    result = await svc.detect_from_adjustment_factor(
        instrument_id=uuid4(),
        ex_date=date(2026, 4, 10),
        factor=Decimal("1"),
    )
    assert result is None
    session.add.assert_not_called()
    await redis.aclose()


async def test_detect_split_factor_records_row() -> None:
    added: list[object] = []
    session = _mock_session(added)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    svc = CorporateActionsService(session=session, redis=redis)

    instrument_id = uuid4()
    result = await svc.detect_from_adjustment_factor(
        instrument_id=instrument_id,
        ex_date=date(2026, 4, 10),
        factor=Decimal("0.5"),  # 2-for-1 split
        notes="seed",
    )

    assert result is not None
    assert result.factor == Decimal("0.5")
    assert result.instrument_id == instrument_id
    assert result.ex_date == date(2026, 4, 10)
    # One CorporateAction row was staged.
    assert len(added) == 1
    action = added[0]
    assert isinstance(action, CorporateAction)
    assert action.action_type == "split"
    assert action.ratio_or_amount == Decimal("0.5")
    assert action.notes == "seed"
    session.flush.assert_awaited()
    await redis.aclose()


# ---------------------------------------------------- broker-anomaly detection


async def test_anomaly_no_change_within_tolerance_returns_none() -> None:
    session = _mock_session()
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    svc = CorporateActionsService(session=session, redis=redis)

    result = await svc.detect_broker_position_anomaly(
        broker_connection_id=uuid4(),
        instrument_id=uuid4(),
        previous_qty=Decimal("100"),
        new_qty=Decimal("100.000000001"),  # within tolerance
        previous_synced_at=datetime.now(UTC) - timedelta(hours=1),
    )
    assert result is None
    await redis.aclose()


async def test_anomaly_explained_by_order_returns_none() -> None:
    """Qty change that matches a filled order delta should NOT be flagged."""
    session = _mock_session()
    # Pretend an explaining buy order exists: +50 qty.
    order = MagicMock()
    order.quantity = Decimal("50")
    order.side = "buy"
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=[order])
    result_proxy = MagicMock()
    result_proxy.scalars = MagicMock(return_value=scalars)
    session.execute = AsyncMock(return_value=result_proxy)

    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    svc = CorporateActionsService(session=session, redis=redis)

    result = await svc.detect_broker_position_anomaly(
        broker_connection_id=uuid4(),
        instrument_id=uuid4(),
        previous_qty=Decimal("100"),
        new_qty=Decimal("150"),  # +50 matches order
        previous_synced_at=datetime.now(UTC) - timedelta(hours=1),
    )
    assert result is None
    session.add.assert_not_called()
    await redis.aclose()


async def test_anomaly_unexplained_is_flagged() -> None:
    """Qty halved (2-for-1 split) with no matching order → flagged row."""
    added: list[object] = []
    session = _mock_session(added)
    # No orders explain the delta.
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=[])
    result_proxy = MagicMock()
    result_proxy.scalars = MagicMock(return_value=scalars)
    session.execute = AsyncMock(return_value=result_proxy)

    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    svc = CorporateActionsService(session=session, redis=redis)

    instrument_id = uuid4()
    broker_connection_id = uuid4()
    result = await svc.detect_broker_position_anomaly(
        broker_connection_id=broker_connection_id,
        instrument_id=instrument_id,
        previous_qty=Decimal("100"),
        new_qty=Decimal("200"),  # 2-for-1 split doubles quantity
        previous_synced_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert result is not None
    assert result.previous_qty == Decimal("100")
    assert result.new_qty == Decimal("200")
    assert len(added) == 1
    action = added[0]
    assert isinstance(action, CorporateAction)
    assert FLAGGED_MARKER in (action.notes or "")
    assert APPLIED_MARKER not in (action.notes or "")
    await redis.aclose()


# ---------------------------------------------------- apply_split pipeline


async def test_apply_split_is_idempotent_when_already_applied() -> None:
    """Re-applying an already-applied action returns 0 rows updated."""
    session = _mock_session()
    existing = CorporateAction(
        id=uuid4(),
        instrument_id=uuid4(),
        action_type="split",
        ex_date=date(2026, 4, 10),
        ratio_or_amount=Decimal("0.5"),
        notes=f"seed {APPLIED_MARKER}",
    )
    session.get = AsyncMock(return_value=existing)

    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    svc = CorporateActionsService(session=session, redis=redis)

    detection = SplitDetection(
        instrument_id=existing.instrument_id,
        ex_date=existing.ex_date,
        factor=Decimal("0.5"),
        corporate_action_id=existing.id,
    )
    rows = await svc.apply_split(detection)

    assert rows == 0
    # No UPDATE issued, no commit.
    session.execute.assert_not_called()
    session.commit.assert_not_called()
    await redis.aclose()


async def test_apply_split_updates_rows_invalidates_cache_and_audits() -> None:
    """Split application issues an UPDATE, wipes tech:* keys, logs audit row."""
    added: list[object] = []
    session = _mock_session(added)
    action_id = uuid4()
    instrument_id = uuid4()
    row = CorporateAction(
        id=action_id,
        instrument_id=instrument_id,
        action_type="split",
        ex_date=date(2026, 4, 10),
        ratio_or_amount=Decimal("0.5"),
        notes="seed",
    )
    session.get = AsyncMock(return_value=row)

    # Fake a rowcount=42 return from the UPDATE statement.
    update_result = MagicMock()
    update_result.rowcount = 42
    session.execute = AsyncMock(return_value=update_result)

    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    # Seed a couple of indicator cache keys that should be wiped.
    await redis.set(f"tech:{instrument_id}:sma:20", "1.0")
    await redis.set(f"tech:{instrument_id}:rsi:14", "55")
    # And a key for a DIFFERENT instrument — must survive.
    other_id = uuid4()
    await redis.set(f"tech:{other_id}:sma:20", "2.0")

    svc = CorporateActionsService(session=session, redis=redis)
    detection = SplitDetection(
        instrument_id=instrument_id,
        ex_date=date(2026, 4, 10),
        factor=Decimal("0.5"),
        corporate_action_id=action_id,
    )

    rows = await svc.apply_split(detection)

    assert rows == 42
    # UPDATE was issued.
    session.execute.assert_awaited_once()
    # Row is marked applied.
    assert APPLIED_MARKER in (row.notes or "")
    # Audit log appended.
    assert any(
        type(obj).__name__ == "AuditLog"
        and getattr(obj, "event_type", None) == "corporate_action.applied"
        for obj in added
    )
    # Commit happened.
    session.commit.assert_awaited()
    # Cache wiped for this instrument only.
    assert await redis.get(f"tech:{instrument_id}:sma:20") is None
    assert await redis.get(f"tech:{instrument_id}:rsi:14") is None
    # Other instrument's cache survives.
    assert await redis.get(f"tech:{other_id}:sma:20") == "2.0"

    await redis.aclose()
