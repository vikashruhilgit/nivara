"""Weekly calendar verification job.

Compares ``exchange_calendars`` output against authoritative broker holiday
lists (Alpaca ``/v2/calendar`` for US; NSE/BSE override table for India).
Any mismatch is:

1. Emitted as a structured log line (operator visibility).
2. Recorded in :class:`DriftReport.drifts` for downstream alerting.
3. Surfaced by the ``calendar_drift_total`` Prometheus counter when the
   metrics plumbing lands (exposed via a stub hook here so the taskname
   stays stable).

The task runs weekly (Sunday 03:00 UTC — see ``celery_app.beat_schedule``).
Running less often than daily is intentional: library updates ship weekly
at most, and broker calendars are stable week-over-week. A weekly cadence
minimises API quota consumption on the broker side.

The real broker-side fetch isn't wired yet (blocked on the broker adapter's
``/v2/calendar`` endpoint landing in M4). Until then :func:`verify_calendars`
only compares the library against ``calendar_overrides`` rows, which is
still useful: it catches the case where a manual override got out of sync
with a library release.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from celery import shared_task

logger = logging.getLogger(__name__)

SUPPORTED_EXCHANGES: tuple[str, ...] = ("XNYS", "XNAS", "XBOM")

# How far forward to verify. Two weeks is the sweet spot: long enough to
# catch an upcoming mismatch before it bites, short enough that the sweep
# doesn't thrash when a library release reshuffles far-future dates.
DEFAULT_HORIZON_DAYS: int = 14


@dataclass(frozen=True)
class Drift:
    """One calendar discrepancy."""

    exchange: str
    on: date
    library_says_open: bool
    override_says_open: bool
    reason: str


@dataclass(frozen=True)
class DriftReport:
    """Result of a verification run."""

    run_at: datetime
    exchanges_checked: tuple[str, ...]
    horizon_days: int
    drifts: tuple[Drift, ...] = field(default_factory=tuple)

    @property
    def has_drift(self) -> bool:
        return bool(self.drifts)


async def verify_calendars(
    exchanges: tuple[str, ...] = SUPPORTED_EXCHANGES,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> DriftReport:
    """Compare library sessions vs override rows over the next ``horizon_days``.

    Testable without Celery: a plain async function that takes an explicit
    exchange list + horizon and returns a structured report.
    """
    from backend.app.db import _session_factory
    from backend.app.models.calendar_overrides import CalendarOverride
    from backend.app.services.calendar import _get_calendar
    from sqlalchemy import select

    today = date.today()
    horizon_end = today + timedelta(days=horizon_days)
    drifts: list[Drift] = []

    async with _session_factory()() as session:
        for mic in exchanges:
            cal = _get_calendar(mic)
            # Pull all override rows in the horizon, keyed by date.
            stmt = select(CalendarOverride).where(
                CalendarOverride.exchange == mic,
                CalendarOverride.date >= today,
                CalendarOverride.date <= horizon_end,
            )
            overrides = {
                row.date: row for row in (await session.execute(stmt)).scalars()
            }

            # Walk each day. Only flag a drift when the override's is_open
            # disagrees with the library's session classification.
            d = today
            while d <= horizon_end:
                library_says_open = bool(cal.is_session(d))
                if d in overrides:
                    override_says_open = bool(overrides[d].is_open)
                    if library_says_open != override_says_open:
                        drifts.append(
                            Drift(
                                exchange=mic,
                                on=d,
                                library_says_open=library_says_open,
                                override_says_open=override_says_open,
                                reason=overrides[d].reason or "(no reason recorded)",
                            )
                        )
                        logger.warning(
                            "calendar_verify: drift exchange=%s date=%s library=%s override=%s",
                            mic,
                            d.isoformat(),
                            library_says_open,
                            override_says_open,
                        )
                d = d + timedelta(days=1)

    report = DriftReport(
        run_at=datetime.now(UTC),
        exchanges_checked=exchanges,
        horizon_days=horizon_days,
        drifts=tuple(drifts),
    )
    logger.info(
        "calendar_verify: run complete exchanges=%s horizon_days=%s drifts=%s",
        exchanges,
        horizon_days,
        len(drifts),
    )
    return report


@shared_task(name="calendar.verify_weekly")  # type: ignore[untyped-decorator]
def verify_weekly() -> dict[str, object]:
    """Celery entrypoint for the weekly beat schedule."""
    import asyncio

    report = asyncio.run(verify_calendars())
    return {
        "run_at": report.run_at.isoformat(),
        "exchanges_checked": list(report.exchanges_checked),
        "horizon_days": report.horizon_days,
        "drifts": [
            {
                "exchange": d.exchange,
                "date": d.on.isoformat(),
                "library_says_open": d.library_says_open,
                "override_says_open": d.override_says_open,
                "reason": d.reason,
            }
            for d in report.drifts
        ],
        "has_drift": report.has_drift,
    }
