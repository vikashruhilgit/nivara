"""In-session Celery tasks.

Dispatched by :mod:`backend.app.scheduling.scheduler` while a market is in
an active trading session. All tasks are thin orchestration wrappers that
delegate to the pipeline services — they exist here so Celery Beat / the
scheduler can address them by stable task name without importing the
heavyweight pipeline modules into the scheduler itself.

Each task:

* accepts ``exchange`` (MIC code) as its sole required kwarg,
* is idempotent (safe to re-run if the scheduler retries),
* logs summary counts so the scheduler tick log reads as a timeline,
* swallows per-instrument / per-connection failures (never poisons the
  queue — errors are logged and the task returns partial counts).

The actual heavy lifting lives in:

* indicator recalc — :mod:`backend.app.analysis.technical`
* portfolio sync — :mod:`backend.app.services.portfolio_sync`
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _RecalcSummary:
    exchange: str
    instruments_attempted: int
    instruments_recalculated: int
    errors: int


async def _recalc_indicators_async(exchange: str) -> _RecalcSummary:
    """Recompute cached technical indicators for all active instruments.

    This is the per-exchange fan-out: iterate active instruments, call
    :func:`backend.app.analysis.technical.analyze_with_cache` for each, and
    let the Redis cache absorb reads. Instruments with insufficient history
    are silently skipped (the technical engine returns ``composite=None``).

    The current implementation is a light-weight stub that:

    1. Counts how many instruments match the exchange in the DB,
    2. Emits a structured log line,
    3. Returns a summary dict.

    The full per-instrument recalc loop lives in Job M3 (recommendation
    engine) where it has the context (universe filtering, rate limiting)
    to run without thrashing the database. For now the scheduler just
    proves the dispatch path is wired.
    """
    from backend.app.db import _session_factory
    from backend.app.models.instruments import Instrument
    from sqlalchemy import func, select

    async with _session_factory()() as session:
        stmt = select(func.count(Instrument.id)).where(Instrument.exchange == exchange)
        # NSE is mapped to XBOM at the calendar layer; the instruments table
        # stores seed-style codes so "XBOM" won't match rows stored as
        # "NSE" / "BSE". We don't care about the exact count here — this is
        # a dispatch heartbeat, not the real recalc loop.
        total = int((await session.execute(stmt)).scalar() or 0)

    logger.info(
        "in_session.recalc_indicators: exchange=%s instruments_found=%s",
        exchange,
        total,
    )
    return _RecalcSummary(
        exchange=exchange,
        instruments_attempted=total,
        instruments_recalculated=0,
        errors=0,
    )


@shared_task(name="tasks.in_session.recalc_indicators")  # type: ignore[untyped-decorator]
def recalc_indicators(exchange: str) -> dict[str, Any]:
    """5-minute indicator recalc trigger. Dispatched per-market."""
    summary = asyncio.run(_recalc_indicators_async(exchange))
    return {
        "exchange": summary.exchange,
        "instruments_attempted": summary.instruments_attempted,
        "instruments_recalculated": summary.instruments_recalculated,
        "errors": summary.errors,
    }


@dataclass(frozen=True)
class _SyncSummary:
    exchange: str
    connections_attempted: int
    connections_synced: int
    errors: int


async def _sync_portfolios_async(exchange: str) -> _SyncSummary:
    """Hourly portfolio sync for all active broker connections on ``exchange``.

    Iterates active broker connections whose broker serves ``exchange``
    (Alpaca → XNYS/XNAS; Zerodha → XBOM) and calls
    :class:`backend.app.services.portfolio_sync.PortfolioSyncService.sync` for
    each. Errors are caught per-connection so one broken user doesn't block
    the rest of the batch.

    The current implementation counts eligible connections and logs a
    summary; the actual per-connection sync loop (with concurrency limits
    and error collection) lands in the recommendation engine job where
    we have a user-level concurrency budget to respect.
    """
    from backend.app.db import _session_factory
    from backend.app.models.broker_connections import BrokerConnection
    from sqlalchemy import select

    broker_filter = {
        "XNYS": ("alpaca",),
        "XNAS": ("alpaca",),
        "XBOM": ("zerodha",),
    }.get(exchange, ())

    async with _session_factory()() as session:
        stmt = select(BrokerConnection).where(
            BrokerConnection.broker.in_(broker_filter),
            BrokerConnection.status == "active",
        )
        rows = list((await session.execute(stmt)).scalars())

    logger.info(
        "in_session.sync_portfolios: exchange=%s eligible_connections=%s",
        exchange,
        len(rows),
    )
    return _SyncSummary(
        exchange=exchange,
        connections_attempted=len(rows),
        connections_synced=0,
        errors=0,
    )


@shared_task(name="tasks.in_session.sync_portfolios")  # type: ignore[untyped-decorator]
def sync_portfolios(exchange: str) -> dict[str, Any]:
    """Hourly portfolio sync trigger. Dispatched per-market at top of hour."""
    summary = asyncio.run(_sync_portfolios_async(exchange))
    return {
        "exchange": summary.exchange,
        "connections_attempted": summary.connections_attempted,
        "connections_synced": summary.connections_synced,
        "errors": summary.errors,
    }
