"""Unit tests for :class:`RiskGuardian` (M3-20, Subtask 7).

The Risk Guardian reads from ``positions``, ``price_history``, ``instruments``,
``broker_connections``, and ``users``. Several of those tables use
Postgres-only column types (JSONB, partitioning, native enums) and cannot be
rendered under SQLite, so we drive the guardian through a tiny fake async
session that answers queries from in-memory dictionaries. This mirrors the
pattern used by ``test_safety_guardian.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from backend.app.models.notifications import Notification
from backend.app.notifications.base import AlertDispatcher, DispatchResult
from backend.app.safety.risk_guardian import (
    MACRO_CHANGE_THRESHOLD,
    RiskGuardian,
    build_default_dispatcher,
    run_risk_guardian_once,
)
from backend.app.schemas.notification import AlertEvent

# --------------------------------------------------------------------- helpers


class _Row:
    """Lightweight stand-in for ORM rows — we only read a handful of attrs."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _ScalarResult:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return list(self._values)

    def scalar_one_or_none(self) -> Any:
        return self._values[0] if self._values else None


class _ExecResult:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._values)

    def scalar_one_or_none(self) -> Any:
        return self._values[0] if self._values else None


@dataclass
class _FakeSession:
    """Routes ``execute(stmt)`` to the right in-memory list by target entity."""

    positions: list[Any] = field(default_factory=list)
    broker_connections: dict[UUID, UUID] = field(default_factory=dict)  # conn_id -> user_id
    instruments: dict[UUID, Any] = field(default_factory=dict)
    price_history: dict[UUID, list[Any]] = field(default_factory=dict)  # inst_id -> rows desc
    users: list[UUID] = field(default_factory=list)
    added: list[Any] = field(default_factory=list)

    async def execute(self, stmt: Any) -> _ExecResult:
        # Identify the target by string-ifying the statement — crude but fine
        # for the narrow set of queries the guardian issues.
        sql = str(stmt).lower()
        if "from positions" in sql:
            return _ExecResult(list(self.positions))
        if "from broker_connections" in sql:
            # caller wants user_id for a specific connection id
            conn_id = self._extract_uuid_filter(stmt)
            user_id = self.broker_connections.get(conn_id) if conn_id else None
            return _ExecResult([user_id] if user_id is not None else [])
        if "from instruments" in sql:
            inst_id = self._extract_uuid_filter(stmt)
            inst = self.instruments.get(inst_id) if inst_id else None
            return _ExecResult([inst] if inst is not None else [])
        if "from price_history" in sql:
            inst_id = self._extract_uuid_filter(stmt)
            rows = self.price_history.get(inst_id, []) if inst_id else []
            return _ExecResult(list(rows))
        if "from users" in sql:
            return _ExecResult(list(self.users))
        # Default
        return _ExecResult([])

    @staticmethod
    def _extract_uuid_filter(stmt: Any) -> UUID | None:
        # Walk the compiled binds of the statement to find the UUID bound value.
        try:
            compiled = stmt.compile(compile_kwargs={"literal_binds": False})
            for val in compiled.params.values():
                if isinstance(val, UUID):
                    return val
        except Exception:
            return None
        return None

    def add(self, entity: Any) -> None:
        if isinstance(entity, Notification) and entity.id is None:
            entity.id = uuid4()
            entity.created_at = datetime.now(UTC)
        self.added.append(entity)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


def _price_row(instrument_id: UUID, ts: datetime, high: float, low: float) -> Any:
    return _Row(
        instrument_id=instrument_id,
        timestamp=ts,
        open=Decimal("100"),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal("100"),
        volume=1_000_000,
    )


def _position(broker_conn_id: UUID, instrument_id: UUID) -> Any:
    return _Row(
        id=uuid4(),
        broker_connection_id=broker_conn_id,
        instrument_id=instrument_id,
        quantity=Decimal("10"),
        avg_cost=Decimal("100"),
        currency="USD",
        as_of=datetime.now(UTC),
    )


def _instrument(inst_id: UUID, symbol: str) -> Any:
    return _Row(
        id=inst_id,
        symbol=symbol,
        exchange="NASDAQ",
        name=symbol,
        currency="USD",
        asset_class="equity",
    )


# -------------------------------------------------------------- volatility AC#1


async def test_detect_volatility_emits_alert_when_range_exceeds_adr() -> None:
    """AC #1: today's range > 2× ADR triggers a price_alert."""
    user_id = uuid4()
    conn_id = uuid4()
    inst_id = uuid4()
    session = _FakeSession(
        positions=[_position(conn_id, inst_id)],
        broker_connections={conn_id: user_id},
        instruments={inst_id: _instrument(inst_id, "AAPL")},
        price_history={
            inst_id: [
                # Today's row (desc order, index 0) — big range.
                _price_row(inst_id, datetime(2024, 1, 21, tzinfo=UTC), high=110, low=100),
                # Prior 20 days — range ~1.0 each.
                *[
                    _price_row(
                        inst_id,
                        datetime(2024, 1, 20, tzinfo=UTC) - timedelta(days=i),
                        high=101.0,
                        low=100.0,
                    )
                    for i in range(20)
                ],
            ]
        },
    )
    guardian = RiskGuardian(session=session)  # type: ignore[arg-type]
    alerts = await guardian.detect_volatility_alerts(lookback_days=20, multiplier=2.0)

    assert len(alerts) == 1
    event = alerts[0]
    assert isinstance(event, AlertEvent)
    assert event.user_id == user_id
    assert event.notification_type == "price_alert"
    assert event.payload["symbol"] == "AAPL"
    assert event.payload["today_range"] == pytest.approx(10.0)
    assert event.payload["adr"] == pytest.approx(1.0)
    assert event.payload["multiplier"] == 2.0


async def test_detect_volatility_no_alert_when_range_within_threshold() -> None:
    """AC #1 negative: today's range ≤ 2× ADR emits nothing."""
    user_id = uuid4()
    conn_id = uuid4()
    inst_id = uuid4()
    session = _FakeSession(
        positions=[_position(conn_id, inst_id)],
        broker_connections={conn_id: user_id},
        instruments={inst_id: _instrument(inst_id, "AAPL")},
        price_history={
            inst_id: [
                _price_row(inst_id, datetime(2024, 1, 21, tzinfo=UTC), high=101.5, low=100.0),
                *[
                    _price_row(
                        inst_id,
                        datetime(2024, 1, 20, tzinfo=UTC) - timedelta(days=i),
                        high=101.0,
                        low=100.0,
                    )
                    for i in range(20)
                ],
            ]
        },
    )
    guardian = RiskGuardian(session=session)  # type: ignore[arg-type]
    alerts = await guardian.detect_volatility_alerts(lookback_days=20, multiplier=2.0)
    assert alerts == []


# ---------------------------------------------------------------- earnings AC#3


async def test_detect_earnings_alert_within_horizon() -> None:
    """AC #3: earnings date 3 days out triggers a system alert."""
    user_id = uuid4()
    conn_id = uuid4()
    inst_id = uuid4()
    three_days_out = date.today() + timedelta(days=3)

    session = _FakeSession(
        positions=[_position(conn_id, inst_id)],
        broker_connections={conn_id: user_id},
        instruments={inst_id: _instrument(inst_id, "AAPL")},
    )

    def lookup(symbol: str) -> date | None:
        return three_days_out if symbol == "AAPL" else None

    guardian = RiskGuardian(session=session, get_earnings_date=lookup)  # type: ignore[arg-type]
    alerts = await guardian.detect_earnings_alerts(days_ahead=5)

    assert len(alerts) == 1
    event = alerts[0]
    assert event.user_id == user_id
    assert event.notification_type == "system"
    assert event.payload["symbol"] == "AAPL"
    assert event.payload["days_until"] == 3
    assert event.payload["earnings_date"] == three_days_out.isoformat()


async def test_detect_earnings_no_alert_when_outside_horizon() -> None:
    """A symbol whose earnings are beyond ``days_ahead`` is skipped."""
    user_id = uuid4()
    conn_id = uuid4()
    inst_id = uuid4()
    session = _FakeSession(
        positions=[_position(conn_id, inst_id)],
        broker_connections={conn_id: user_id},
        instruments={inst_id: _instrument(inst_id, "AAPL")},
    )
    far = date.today() + timedelta(days=30)
    guardian = RiskGuardian(
        session=session,  # type: ignore[arg-type]
        get_earnings_date=lambda _s: far,
    )
    assert await guardian.detect_earnings_alerts(days_ahead=5) == []


# ------------------------------------------------------------------- macro AC#4


class _StubAsyncClient:
    """Minimal duck-type of :class:`httpx.AsyncClient` for macro tests."""

    def __init__(self, response_payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = response_payload
        self._status = status_code
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        self.calls.append({"url": url, "params": params or {}})
        # Build a real httpx.Response so ``raise_for_status`` + ``json`` work.
        req = httpx.Request("GET", url, params=params)
        return httpx.Response(self._status, json=self._payload, request=req)

    async def aclose(self) -> None:  # pragma: no cover - defensive
        return None


async def test_detect_macro_alerts_emits_per_user_on_material_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #4: FRED change > threshold emits one alert per active user."""
    from backend.app.safety import risk_guardian as rg_module

    # Ensure get_settings returns a FRED key.
    class _FakeSettings:
        fred_api_key = "fake-key"

    monkeypatch.setattr(rg_module, "get_settings", lambda: _FakeSettings())

    user_a = uuid4()
    user_b = uuid4()
    session = _FakeSession(users=[user_a, user_b])

    payload = {
        "observations": [
            {"date": "2024-01-02", "value": "5.50"},
            {"date": "2024-01-01", "value": "5.25"},
        ]
    }
    client = _StubAsyncClient(payload)
    guardian = RiskGuardian(session=session, http_client=client)  # type: ignore[arg-type]

    alerts = await guardian.detect_macro_alerts(fred_series=["DFF"])

    assert len(alerts) == 2  # one alert per user
    users = {a.user_id for a in alerts}
    assert users == {user_a, user_b}
    for event in alerts:
        assert event.notification_type == "system"
        assert event.payload["series_id"] == "DFF"
        assert event.payload["delta"] == pytest.approx(0.25)


async def test_detect_macro_alerts_no_alert_when_change_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.safety import risk_guardian as rg_module

    class _FakeSettings:
        fred_api_key = "fake-key"

    monkeypatch.setattr(rg_module, "get_settings", lambda: _FakeSettings())

    # Change below MACRO_CHANGE_THRESHOLD
    payload = {
        "observations": [
            {"date": "2024-01-02", "value": "5.01"},
            {"date": "2024-01-01", "value": "5.00"},
        ]
    }
    small_delta = 0.01
    assert small_delta < MACRO_CHANGE_THRESHOLD

    session = _FakeSession(users=[uuid4()])
    client = _StubAsyncClient(payload)
    guardian = RiskGuardian(session=session, http_client=client)  # type: ignore[arg-type]

    alerts = await guardian.detect_macro_alerts(fred_series=["DFF"])
    assert alerts == []


async def test_detect_macro_alerts_noop_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.safety import risk_guardian as rg_module

    class _FakeSettings:
        fred_api_key = None

    monkeypatch.setattr(rg_module, "get_settings", lambda: _FakeSettings())

    session = _FakeSession(users=[uuid4()])
    guardian = RiskGuardian(session=session)  # type: ignore[arg-type]
    assert await guardian.detect_macro_alerts() == []


# ------------------------------------------------------------------- persist


async def test_persist_alerts_inserts_notification_rows() -> None:
    session = _FakeSession()
    guardian = RiskGuardian(session=session)  # type: ignore[arg-type]
    user_id = uuid4()
    events = [
        AlertEvent(
            user_id=user_id,
            notification_type="price_alert",
            title="t",
            body="b",
            payload={"k": 1},
        ),
        AlertEvent(
            user_id=user_id,
            notification_type="system",
            title="t2",
            body="b2",
            payload={"k": 2},
        ),
    ]

    persisted = await guardian.persist_alerts(events)

    assert len(persisted) == 2
    notifications = [n for n in session.added if isinstance(n, Notification)]
    assert len(notifications) == 2
    assert {n.notification_type for n in notifications} == {"price_alert", "system"}
    assert all(n.title and n.body for n in notifications)


# ------------------------------------------------------------------- run_all


async def test_run_all_round_trips_dispatch() -> None:
    """``run_all`` persists alerts and fans them out through the dispatcher."""
    user_id = uuid4()
    session = _FakeSession(users=[user_id])

    # Pre-seed one volatility-triggering position.
    conn_id = uuid4()
    inst_id = uuid4()
    session.positions = [_position(conn_id, inst_id)]
    session.broker_connections = {conn_id: user_id}
    session.instruments = {inst_id: _instrument(inst_id, "AAPL")}
    session.price_history = {
        inst_id: [
            _price_row(inst_id, datetime(2024, 1, 21, tzinfo=UTC), high=110, low=100),
            *[
                _price_row(
                    inst_id,
                    datetime(2024, 1, 20, tzinfo=UTC) - timedelta(days=i),
                    high=101.0,
                    low=100.0,
                )
                for i in range(20)
            ],
        ]
    }

    class _CapturingDispatcher:
        def __init__(self) -> None:
            self.calls: list[Notification] = []

        async def dispatch(self, notification: Notification) -> DispatchResult:
            self.calls.append(notification)
            # Mirror the real AlertDispatcher: mark as sent on successful
            # delivery. ``run_all`` no longer sets ``sent_at`` itself.
            if notification.sent_at is None:
                notification.sent_at = datetime.now(tz=UTC)
            return DispatchResult(
                notification_id=notification.id,
                channels_attempted=["_CapturingDispatcher"],
                channels_succeeded=["_CapturingDispatcher"],
            )

        async def dispatch_many(self, notifications: list[Notification]) -> list[DispatchResult]:
            return [await self.dispatch(n) for n in notifications]

    dispatcher = _CapturingDispatcher()
    guardian = RiskGuardian(session=session)  # type: ignore[arg-type]
    notifications = await guardian.run_all(dispatcher=dispatcher)  # type: ignore[arg-type]

    assert len(notifications) == 1
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0].notification_type == "price_alert"
    # dispatch success sets sent_at
    assert notifications[0].sent_at is not None


# ----------------------------------------------------- helpers for top-level API


async def test_build_default_dispatcher_constructs_expo_channel() -> None:
    session = _FakeSession()
    async with httpx.AsyncClient() as http:
        dispatcher = build_default_dispatcher(session, http)  # type: ignore[arg-type]
    assert isinstance(dispatcher, AlertDispatcher)
    # Internal attribute is hidden; we only assert the type was constructed.


async def test_run_risk_guardian_once_commits_and_returns_notifications() -> None:
    """``run_risk_guardian_once`` commits and returns the persisted list."""
    session = _FakeSession()
    session.commit = AsyncMock()  # type: ignore[method-assign]

    async with httpx.AsyncClient() as http:
        result = await run_risk_guardian_once(session, http_client=http)  # type: ignore[arg-type]

    assert result == []  # no positions / users seeded → no alerts
    session.commit.assert_awaited()
