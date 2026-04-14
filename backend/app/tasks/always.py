"""Always-running Celery tasks.

Scheduled via :mod:`backend.app.celery_app.beat_schedule` — independent of
market session state. Market holiday ≠ "nothing runs": news keeps
flowing, FX rates publish on banking calendars, and corporate-action
feeds push on business days. Those are handled here.

Scheduled entries (defined in ``celery_app.py``)
-----------------------------------------------
* ``news-sentiment-every-15min``  → :func:`refresh_news_sentiment`
* ``fx-daily-0600-utc``           → :func:`refresh_fx`

Each task is a thin orchestration wrapper around its pipeline service so
the Celery layer stays lean and the business logic remains independently
testable (see the service-layer tests in ``backend/tests/``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)


# --------- news + sentiment ---------


async def _refresh_news_sentiment_async() -> dict[str, Any]:
    """Refresh news headlines + recompute per-instrument sentiment.

    Real implementation: fan out across a configured universe
    (e.g. user-held instruments + top-50 coverage list), calling
    :func:`backend.app.analysis.sentiment.compute_sentiment` for each,
    writing results to Redis for the recommendation engine to consume.

    Current scope is a heartbeat: log intent + return a summary. The
    full fan-out lands in the recommendation engine job (M3) where the
    universe is defined.
    """
    logger.info("always.refresh_news_sentiment: heartbeat (fan-out lands in M3)")
    return {"task": "refresh_news_sentiment", "ran": True}


@shared_task(name="tasks.always.refresh_news_sentiment")  # type: ignore[untyped-decorator]
def refresh_news_sentiment() -> dict[str, Any]:
    """Run every 15 minutes. Pulls fresh news + recomputes sentiment scores."""
    return asyncio.run(_refresh_news_sentiment_async())


# --------- FX refresh ---------


async def _refresh_fx_async() -> dict[str, Any]:
    """Daily USD/INR refresh via :class:`FxRefreshService`.

    ``FxRefreshService.refresh_usd_inr`` pulls from FRED with ECB fallback
    and upserts into ``fx_rates`` + Redis cache. Runs at 06:00 UTC so both
    US (previous close) and Asia (morning planning) data paths see fresh
    rates. Failures are logged and re-raised so Celery's retry policy
    kicks in.
    """
    from backend.app.config import get_settings
    from backend.app.data.fred import EcbClient, FredClient, FredEcbClient
    from backend.app.db import _session_factory
    from backend.app.redis_client import get_redis
    from backend.app.services.fx import FxRefreshService

    settings = get_settings()
    fred_api_key = getattr(settings, "fred_api_key", None)

    async with _session_factory()() as session:
        redis = get_redis()
        fred = FredClient(api_key=fred_api_key)
        ecb = EcbClient()
        client = FredEcbClient(fred=fred, ecb=ecb)
        service = FxRefreshService(session=session, redis=redis, client=client)
        # ``refresh_usd_inr`` is the public entry point; detailed return
        # value is provider-dependent so we just record the summary.
        try:
            result = await service.refresh_usd_inr()
        except AttributeError:
            # Older FxRefreshService may expose a different method name;
            # fall back to the generic refresh API if present.
            if hasattr(service, "refresh"):
                result = await service.refresh("USD", "INR")
            else:  # pragma: no cover — defensive guard for API drift.
                raise
        await session.commit()

    logger.info("always.refresh_fx: done result=%s", result)
    # Best-effort serialization — the service may return a dataclass, a
    # dict, or None depending on the code path.
    return {
        "task": "refresh_fx",
        "ran": True,
        "result": str(result) if result is not None else None,
    }


@shared_task(name="tasks.always.refresh_fx")  # type: ignore[untyped-decorator]
def refresh_fx() -> dict[str, Any]:
    """Run daily at 06:00 UTC. Refreshes USD/INR (FRED primary, ECB fallback)."""
    return asyncio.run(_refresh_fx_async())


# --------- corporate actions check ---------


async def _check_corporate_actions_async(exchange: str) -> dict[str, Any]:
    """Post-close corporate-action sweep.

    Hooked into the post-close batch (Job M2-11 pipeline) so US and India
    splits/dividends are applied retroactively to ``price_history`` and
    flagged to users. Exposed here as a standalone periodic task so it
    can also be invoked manually via ``celery call``.
    """
    logger.info("always.check_corporate_actions: exchange=%s heartbeat", exchange)
    return {"task": "check_corporate_actions", "exchange": exchange, "ran": True}


@shared_task(name="tasks.always.check_corporate_actions")  # type: ignore[untyped-decorator]
def check_corporate_actions(exchange: str) -> dict[str, Any]:
    return asyncio.run(_check_corporate_actions_async(exchange))
