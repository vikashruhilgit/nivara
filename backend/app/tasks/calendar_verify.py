"""Weekly calendar verification job (stub).

The full implementation will:

1. Enumerate the next 14 sessions for each supported exchange (XNYS, XNAS,
   XBOM) using ``exchange_calendars``.
2. Cross-check each against a second authoritative source (broker's
   ``/v2/calendar`` endpoint for Alpaca, NSE/BSE holiday notices scraped
   into the ``calendar_overrides`` table for India).
3. For every mismatch, emit a structured log line and enqueue an override
   candidate for human review.
4. Emit a Prometheus counter ``calendar_drift_total{exchange=...}`` so we
   can alert on chronic drift between library and broker reality.

For now we only expose the Celery task signature and a pure-Python helper
that returns an empty drift report — the downstream scheduler, broker API
clients, and metrics plumbing land in later M1 / M2 jobs.

See `plan/implementation.md` M2 "Session-aware scheduling" for the full
plan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from celery import shared_task

logger = logging.getLogger(__name__)

SUPPORTED_EXCHANGES: tuple[str, ...] = ("XNYS", "XNAS", "XBOM")


@dataclass(frozen=True)
class DriftReport:
    """Result of a verification run."""

    run_at: datetime
    exchanges_checked: tuple[str, ...]
    drifts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_drift(self) -> bool:
        return bool(self.drifts)


async def verify_calendars(
    exchanges: tuple[str, ...] = SUPPORTED_EXCHANGES,
    horizon_days: int = 14,
) -> DriftReport:
    """Pure-Python entry point — testable without Celery.

    Currently a stub: returns an empty report. Kept async so the real
    implementation can query the DB + broker APIs without rewriting callers.
    """
    logger.info("calendar_verify stub run: exchanges=%s horizon_days=%s", exchanges, horizon_days)
    # TODO(m2): walk exchange_calendars for each MIC, compare to broker
    # calendar, write overrides or emit alerts for any drift detected.
    _ = (date.today(), horizon_days)  # silence unused-var linters for the stub
    return DriftReport(
        run_at=datetime.now(UTC),
        exchanges_checked=exchanges,
        drifts=(),
    )


@shared_task(name="calendar.verify_weekly")  # type: ignore[untyped-decorator]
def verify_weekly() -> dict[str, object]:
    """Celery entrypoint for the weekly beat schedule.

    Wired into ``celery beat`` in a later job. Returns a JSON-friendly
    summary so Celery's result backend + logs stay readable.
    """
    import asyncio

    report = asyncio.run(verify_calendars())
    return {
        "run_at": report.run_at.isoformat(),
        "exchanges_checked": list(report.exchanges_checked),
        "drifts": list(report.drifts),
        "has_drift": report.has_drift,
    }
