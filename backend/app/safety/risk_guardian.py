"""Risk Guardian (M3-20, Mode E).

Monitoring / alert-detection engine. Separate from :mod:`backend.app.safety.guardian`
(which is the *pre-trade* safety layer) — this module watches the portfolio
and market for events worth notifying the user about:

1. **Volatility** — today's intraday range exceeds ``multiplier × ADR``
   (Average Daily Range) over a lookback window.
2. **Earnings** — an upcoming earnings date for a held instrument falls
   within ``days_ahead``. The earnings calendar is not yet modelled in the
   DB, so we accept an injected ``get_earnings_date`` callable; when it
   returns ``None`` for a symbol, that symbol is silently skipped.
3. **Macro** — a FRED series (default Fed Funds + Unemployment) has
   materially changed between its two latest observations.

Each detector returns a list of :class:`AlertEvent` objects. ``persist_alerts``
writes them as ``Notification`` rows (no commit — caller owns the txn).
``run_all`` is the orchestration entry-point and optionally dispatches each
persisted notification via an injected :class:`AlertDispatcher` (Subtask 2).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pandas as pd
from backend.app.config import get_settings
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.instruments import Instrument
from backend.app.models.notifications import Notification
from backend.app.models.positions import Position
from backend.app.models.price_history import PriceHistory
from backend.app.models.users import User
from backend.app.notifications import AlertDispatcher, ExpoPushChannel, NotificationChannel
from backend.app.schemas.notification import AlertEvent
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# Any absolute change greater than this between the two latest FRED
# observations emits a macro alert. Kept small & generic per AC — specific
# per-series thresholds can be layered later without changing the API.
MACRO_CHANGE_THRESHOLD = 0.1

EarningsLookup = Callable[[str], date | None]


def _default_earnings_lookup(_symbol: str) -> date | None:
    """Default earnings resolver — returns ``None`` (no calendar wired)."""

    return None


class RiskGuardian:
    """Portfolio / market monitoring and alert generator.

    The guardian is stateless beyond its injected dependencies. It holds an
    :class:`AsyncSession` for reads + pending inserts but never commits;
    callers own the transaction boundary (consistent with
    :class:`SafetyGuardian` and the portfolio sync pattern).
    """

    def __init__(
        self,
        session: AsyncSession,
        http_client: httpx.AsyncClient | None = None,
        *,
        get_earnings_date: EarningsLookup | None = None,
    ) -> None:
        self._session = session
        self._http = http_client
        self._get_earnings_date: EarningsLookup = get_earnings_date or _default_earnings_lookup

    # ------------------------------------------------------------------ helpers

    async def _user_id_for_connection(self, broker_connection_id: UUID) -> UUID | None:
        stmt = select(BrokerConnection.user_id).where(BrokerConnection.id == broker_connection_id)
        result = (await self._session.execute(stmt)).scalar_one_or_none()
        return result

    async def _load_instrument(self, instrument_id: UUID) -> Instrument | None:
        stmt = select(Instrument).where(Instrument.id == instrument_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # --------------------------------------------------------------- volatility

    async def detect_volatility_alerts(
        self,
        *,
        lookback_days: int = 20,
        multiplier: float = 2.0,
    ) -> list[AlertEvent]:
        """Flag positions where today's range >> historical ADR.

        For every open position we pull the last ``lookback_days + 1`` rows
        of ``price_history`` (desc), compute ADR over the prior window, and
        compare it to the most recent bar's ``high - low``. A position emits
        at most one event per run.
        """

        alerts: list[AlertEvent] = []
        pos_stmt = select(Position)
        positions = (await self._session.execute(pos_stmt)).scalars().all()

        for position in positions:
            user_id = await self._user_id_for_connection(position.broker_connection_id)
            if user_id is None:
                continue

            instrument = await self._load_instrument(position.instrument_id)
            if instrument is None:
                continue

            price_stmt = (
                select(PriceHistory)
                .where(PriceHistory.instrument_id == position.instrument_id)
                .order_by(desc(PriceHistory.timestamp))
                .limit(lookback_days + 1)
            )
            rows = (await self._session.execute(price_stmt)).scalars().all()
            if len(rows) < lookback_days + 1:
                # Not enough history to compute a stable ADR — skip quietly.
                continue

            df = pd.DataFrame(
                [
                    {"high": float(r.high), "low": float(r.low), "timestamp": r.timestamp}
                    for r in rows
                ]
            )
            # rows are DESC; row 0 is "today", rows 1..lookback are the window.
            today_range = float(df.iloc[0]["high"] - df.iloc[0]["low"])
            window = df.iloc[1 : lookback_days + 1]
            adr = float((window["high"] - window["low"]).mean())

            if adr <= 0:
                continue

            if today_range > multiplier * adr:
                payload: dict[str, Any] = {
                    "symbol": instrument.symbol,
                    "today_range": today_range,
                    "adr": adr,
                    "multiplier": multiplier,
                }
                alerts.append(
                    AlertEvent(
                        user_id=user_id,
                        notification_type="price_alert",
                        title=f"Volatility alert: {instrument.symbol}",
                        body=(
                            f"{instrument.symbol} traded a {today_range:.2f} range today "
                            f"vs {adr:.2f} average ({multiplier:g}× threshold)."
                        ),
                        payload=payload,
                    )
                )

        return alerts

    # ----------------------------------------------------------------- earnings

    async def detect_earnings_alerts(self, *, days_ahead: int = 5) -> list[AlertEvent]:
        """Flag held instruments whose earnings date falls inside ``days_ahead``.

        The project does not yet model an earnings calendar; we consult the
        ``get_earnings_date`` callable injected at construction time. When it
        returns ``None`` for a symbol (the default), that holding is skipped.
        Once a real earnings source is wired, swap the callable and the rest
        of the pipeline continues to work unchanged.
        """

        alerts: list[AlertEvent] = []
        today = date.today()
        horizon = today + timedelta(days=days_ahead)

        pos_stmt = select(Position)
        positions = (await self._session.execute(pos_stmt)).scalars().all()

        # Collapse multi-account duplicates: only one alert per (user, symbol).
        seen: set[tuple[UUID, str]] = set()

        for position in positions:
            user_id = await self._user_id_for_connection(position.broker_connection_id)
            if user_id is None:
                continue
            instrument = await self._load_instrument(position.instrument_id)
            if instrument is None:
                continue

            earnings_date = self._get_earnings_date(instrument.symbol)
            if earnings_date is None:
                continue
            if not (today <= earnings_date <= horizon):
                continue

            key = (user_id, instrument.symbol)
            if key in seen:
                continue
            seen.add(key)

            days_until = (earnings_date - today).days
            alerts.append(
                AlertEvent(
                    user_id=user_id,
                    notification_type="system",
                    title=f"Earnings in {days_until} days: {instrument.symbol}",
                    body=(
                        f"{instrument.symbol} reports earnings on "
                        f"{earnings_date.isoformat()} ({days_until} days away)."
                    ),
                    payload={
                        "symbol": instrument.symbol,
                        "earnings_date": earnings_date.isoformat(),
                        "days_until": days_until,
                    },
                )
            )

        return alerts

    # -------------------------------------------------------------------- macro

    async def detect_macro_alerts(
        self,
        *,
        fred_series: list[str] | None = None,
    ) -> list[AlertEvent]:
        """Flag material changes in the latest FRED observations.

        For each configured series we fetch the two latest observations and
        emit one alert per active user when the absolute change exceeds
        :data:`MACRO_CHANGE_THRESHOLD`. No FRED key → quietly no-op (the
        detector is best-effort and should never crash a monitoring run).
        """

        settings = get_settings()
        api_key = settings.fred_api_key
        if not api_key:
            logger.info("risk_guardian.macro: FRED_API_KEY not set — skipping macro alerts")
            return []

        series = fred_series if fred_series is not None else ["DFF", "UNRATE"]
        client = self._http or httpx.AsyncClient(timeout=10.0)
        owns_client = self._http is None

        try:
            changes: list[dict[str, Any]] = []
            for series_id in series:
                params: dict[str, str | int] = {
                    "series_id": series_id,
                    "api_key": api_key,
                    "file_type": "json",
                    "limit": 2,
                    "sort_order": "desc",
                }
                try:
                    resp = await client.get(FRED_BASE_URL, params=params)
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    logger.warning(
                        "risk_guardian.macro: FRED fetch failed for %s: %s", series_id, exc
                    )
                    continue

                data = resp.json()
                observations = data.get("observations", [])
                if len(observations) < 2:
                    continue
                try:
                    latest = float(observations[0]["value"])
                    previous = float(observations[1]["value"])
                except (KeyError, TypeError, ValueError):
                    continue

                delta = latest - previous
                if abs(delta) > MACRO_CHANGE_THRESHOLD:
                    changes.append(
                        {
                            "series_id": series_id,
                            "latest": latest,
                            "previous": previous,
                            "delta": delta,
                            "latest_date": observations[0].get("date"),
                        }
                    )
        finally:
            if owns_client:
                await client.aclose()

        if not changes:
            return []

        user_stmt = select(User.id).where(User.is_active.is_(True))
        user_ids = (await self._session.execute(user_stmt)).scalars().all()

        alerts: list[AlertEvent] = []
        for uid in user_ids:
            for change in changes:
                alerts.append(
                    AlertEvent(
                        user_id=uid,
                        notification_type="system",
                        title=f"Macro alert: {change['series_id']} moved {change['delta']:+.2f}",
                        body=(
                            f"{change['series_id']} changed from {change['previous']} to "
                            f"{change['latest']} (as of {change['latest_date']})."
                        ),
                        payload=change,
                    )
                )
        return alerts

    # ----------------------------------------------------------------- persist

    async def persist_alerts(self, alerts: list[AlertEvent]) -> list[Notification]:
        """Insert ``AlertEvent`` objects as ``Notification`` rows.

        No commit — the caller owns the transaction. We flush so callers
        that need the generated primary keys (e.g. dispatchers) see them.
        """

        persisted: list[Notification] = []
        for alert in alerts:
            notification = Notification(
                user_id=alert.user_id,
                notification_type=alert.notification_type,
                title=alert.title,
                body=alert.body,
                payload=alert.payload,
            )
            self._session.add(notification)
            persisted.append(notification)

        if persisted:
            await self._session.flush()
        return persisted

    # --------------------------------------------------------------- run all

    async def run_all(
        self,
        *,
        dispatcher: AlertDispatcher | None = None,
    ) -> list[Notification]:
        """Run all detectors, persist, and optionally dispatch.

        Dispatch failures are logged but do not roll back persistence — the
        Notification row is the system-of-record and the dispatcher is a
        best-effort fan-out.
        """

        events: list[AlertEvent] = []
        events.extend(await self.detect_volatility_alerts())
        events.extend(await self.detect_earnings_alerts())
        events.extend(await self.detect_macro_alerts())

        notifications = await self.persist_alerts(events)

        if dispatcher is not None:
            for notification in notifications:
                try:
                    await dispatcher.dispatch(notification)
                    notification.sent_at = datetime.now(tz=UTC)
                except Exception:  # noqa: BLE001 — best-effort fan-out
                    logger.exception(
                        "risk_guardian.dispatch_failed",
                        extra={"notification_id": str(notification.id)},
                    )

        return notifications


def build_default_dispatcher(
    session: AsyncSession,
    http_client: httpx.AsyncClient,
) -> AlertDispatcher:
    """Construct the default :class:`AlertDispatcher` for scheduled runs.

    Email is intentionally omitted here: SMTP credentials are (or will be)
    per-user opt-in and will be attached in a follow-up. Push-to-Expo is
    the only always-on channel for now.
    """

    settings = get_settings()
    channels: list[NotificationChannel] = [
        ExpoPushChannel(
            session=session,
            http_client=http_client,
            access_token=settings.expo_push_access_token,
        ),
    ]
    return AlertDispatcher(session=session, channels=channels)


async def run_risk_guardian_once(
    session: AsyncSession,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> list[Notification]:
    """Run the risk guardian once and dispatch resulting notifications.

    Suitable for use from a Celery task or cron entrypoint. When no
    ``http_client`` is provided, a short-lived one is created and closed
    before return. The caller's session is committed on success so the
    persisted notifications are durable even if the dispatcher partially
    fails (dispatch is best-effort).
    """

    close_http = False
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=10.0)
        close_http = True
    try:
        guardian = RiskGuardian(session, http_client=http_client)
        dispatcher = build_default_dispatcher(session, http_client)
        notifications = await guardian.run_all(dispatcher=dispatcher)
        await session.commit()
        return notifications
    finally:
        if close_http:
            await http_client.aclose()


__all__ = [
    "FRED_BASE_URL",
    "MACRO_CHANGE_THRESHOLD",
    "EarningsLookup",
    "RiskGuardian",
    "build_default_dispatcher",
    "run_risk_guardian_once",
]


# Silence unused-import warnings for decimal (reserved for future threshold
# comparisons without floating-point drift). Keeping the import near the
# others costs nothing at runtime.
_ = Decimal
