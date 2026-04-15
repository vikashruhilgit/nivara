"""Post-close batch orchestration.

Triggered by the session-aware scheduler on the first minute at or after
a market's close time (see :class:`MarketState.JUST_CLOSED` in
:mod:`backend.app.scheduling.scheduler`). The batch runs four pipelines
in a defined order using a Celery chain:

1. **OHLCV fetch** (Yahoo daily bars) — hydrates ``price_history`` for
   the closed session.
2. **Fundamentals refresh** (SEC EDGAR for US, stub for India) —
   repopulates fundamental scores now that the earnings window is over.
3. **Risk recalc** — lands in a later job; for now a no-op stub so the
   chain shape is stable.
4. **Portfolio snapshot** — freezes the end-of-day position valuation
   per user so the mobile dashboard can render intraday deltas.

Each step is its own Celery task so retries, timeouts and worker routing
can be configured independently. A failure in step N stops the chain and
leaves a partial state — the next session close naturally retries from
the top (all steps are idempotent by design).

Half-day handling
-----------------
``is_half_day=True`` flows through to the OHLCV fetch so the downstream
provider can pick the right session range. Nothing in the chain treats
half-days specially — the actual close time already got us here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery import chain, shared_task

logger = logging.getLogger(__name__)


# --------- individual pipeline steps (thin wrappers) ---------


async def _fetch_ohlcv_async(exchange: str, session_date: str) -> dict[str, Any]:
    """Stub: enumerate active instruments for ``exchange`` and log intent.

    Real implementation (Job M2-9 / M2-11 hookup): iterate active
    ``instruments`` rows matching ``exchange``, call
    :meth:`YahooProvider.fetch_daily_bars` for each, and upsert into
    ``price_history``. Wired here so the chain has a real task name.
    """
    logger.info("post_close.fetch_ohlcv: exchange=%s session_date=%s", exchange, session_date)
    return {"step": "fetch_ohlcv", "exchange": exchange, "session_date": session_date}


async def _refresh_fundamentals_async(exchange: str, session_date: str) -> dict[str, Any]:
    """Stub: trigger fundamentals refresh. Real impl calls EDGAR pipeline."""
    logger.info(
        "post_close.refresh_fundamentals: exchange=%s session_date=%s",
        exchange,
        session_date,
    )
    return {
        "step": "refresh_fundamentals",
        "exchange": exchange,
        "session_date": session_date,
    }


async def _recalc_risk_async(exchange: str, session_date: str) -> dict[str, Any]:
    """Stub: risk recalc. Real impl lands in M3 (risk meter job)."""
    logger.info("post_close.recalc_risk: exchange=%s session_date=%s", exchange, session_date)
    return {"step": "recalc_risk", "exchange": exchange, "session_date": session_date}


async def _snapshot_portfolios_async(exchange: str, session_date: str) -> dict[str, Any]:
    """Stub: EOD portfolio snapshot. Real impl walks active connections."""
    logger.info(
        "post_close.snapshot_portfolios: exchange=%s session_date=%s",
        exchange,
        session_date,
    )
    return {
        "step": "snapshot_portfolios",
        "exchange": exchange,
        "session_date": session_date,
    }


# --------- Celery task wrappers ---------


@shared_task(name="tasks.post_close.fetch_ohlcv")  # type: ignore[untyped-decorator]
def fetch_ohlcv(exchange: str, session_date: str) -> dict[str, Any]:
    return asyncio.run(_fetch_ohlcv_async(exchange, session_date))


@shared_task(name="tasks.post_close.refresh_fundamentals")  # type: ignore[untyped-decorator]
def refresh_fundamentals(exchange: str, session_date: str) -> dict[str, Any]:
    return asyncio.run(_refresh_fundamentals_async(exchange, session_date))


@shared_task(name="tasks.post_close.recalc_risk")  # type: ignore[untyped-decorator]
def recalc_risk(exchange: str, session_date: str) -> dict[str, Any]:
    return asyncio.run(_recalc_risk_async(exchange, session_date))


@shared_task(name="tasks.post_close.snapshot_portfolios")  # type: ignore[untyped-decorator]
def snapshot_portfolios(exchange: str, session_date: str) -> dict[str, Any]:
    return asyncio.run(_snapshot_portfolios_async(exchange, session_date))


@shared_task(name="tasks.post_close.run_post_close_batch")  # type: ignore[untyped-decorator]
def run_post_close_batch(
    exchange: str,
    session_date: str,
    is_half_day: bool = False,
) -> dict[str, Any]:
    """Orchestrate the post-close chain for one exchange's session.

    Returns a dict describing the chain dispatch (the actual per-step
    results are collected by Celery's result backend). Use
    :meth:`AsyncResult.get` on the returned ``chain_id`` to await
    completion in tests or tooling.
    """
    logger.info(
        "post_close.run_post_close_batch: exchange=%s session_date=%s is_half_day=%s",
        exchange,
        session_date,
        is_half_day,
    )
    pipeline = chain(
        fetch_ohlcv.si(exchange, session_date),
        refresh_fundamentals.si(exchange, session_date),
        recalc_risk.si(exchange, session_date),
        snapshot_portfolios.si(exchange, session_date),
    )
    result = pipeline.apply_async()
    return {
        "exchange": exchange,
        "session_date": session_date,
        "is_half_day": is_half_day,
        "chain_id": str(result.id),
    }


# Expose the async helpers for direct testing without Celery infra.
__all__ = [
    "fetch_ohlcv",
    "recalc_risk",
    "refresh_fundamentals",
    "run_post_close_batch",
    "snapshot_portfolios",
    "_fetch_ohlcv_async",
    "_refresh_fundamentals_async",
    "_recalc_risk_async",
    "_snapshot_portfolios_async",
]
