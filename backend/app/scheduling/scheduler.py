"""Session-aware scheduler core.

What this does
--------------
Every Celery Beat tick (currently once per minute — see
``celery_app.beat_schedule``), :func:`tick` computes the current market
state for each supported exchange and dispatches the right set of Celery
tasks:

* **Pre-open / closed / holiday:** dispatch nothing (in-session jobs
  skipped). Holiday does not suppress always-running jobs; those run on
  their own crontab entries in the Celery Beat schedule and do not go
  through this scheduler.
* **In-session (market open):**
  - indicator recalculation every 5 minutes (``tasks.in_session.recalc_indicators``)
  - portfolio sync every 60 minutes (``tasks.in_session.sync_portfolios``)
* **At session close** (the first tick on or after ``close_utc`` for a
  session we haven't yet flagged as closed): dispatch the post-close
  batch (``tasks.post_close.run_post_close_batch``). The "already
  dispatched for this (exchange, session_date)" flag lives in Redis under
  ``sched:post_close_done:{MIC}:{YYYY-MM-DD}`` with a 48h TTL so DST,
  duplicate beats and worker restarts can't double-fire the batch.
* **Half-day sessions:** detected by :class:`CalendarService.get_session_hours`
  (``is_half_day=True``). The close-time is the library's actual close for
  that date, so post-close batch fires at 1:00 PM ET on the day before
  Thanksgiving rather than the standard 4:00 PM.

Timing cadence
--------------
In-session tasks use a "dispatch at N-minute boundaries" policy rather
than "every N minutes since midnight" so restarts don't shift cadence.
For the 5-minute indicator recalc we dispatch when ``minute % 5 == 0``;
for the hourly portfolio sync when ``minute == 0``. A Redis de-dupe key
(``sched:last_dispatch:{task}:{MIC}:{YYYY-MM-DD-HHMM}``) prevents double
dispatch when beat runs more often than once per minute during catch-up.

Why not pure crontab?
---------------------
Because session hours change per date (half-days, early closes, holidays
across multiple markets) and we want post-close triggered by actual close
rather than 4:00 PM local — which would miss half-days entirely.

All timestamps are UTC. Per-market state is independent: NYSE being open
does not affect BSE's schedule.

Testability
-----------
:func:`compute_market_state` and :class:`SessionAwareScheduler.plan` are
pure async functions that take an explicit ``now_utc`` and return a
structured :class:`SchedulerTick` describing what would be dispatched.
The Celery ``tick`` entrypoint is a thin wrapper that calls ``plan`` +
``apply`` so tests can exercise the planning logic without a live broker.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from backend.app.services.calendar import CalendarService, SessionHours
from celery import shared_task

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Exchanges we schedule. Matches calendar service + tasks.calendar_verify.
SUPPORTED_EXCHANGES: tuple[str, ...] = ("XNYS", "XNAS", "XBOM")

# Cadence policies.
INDICATOR_RECALC_EVERY_MINUTES: int = 5
PORTFOLIO_SYNC_EVERY_MINUTES: int = 60

# Redis TTLs (seconds). Long enough to survive DST transitions and weekends.
_DEDUPE_TTL = 7 * 24 * 60 * 60  # 7 days for per-minute dedupe keys
_POST_CLOSE_TTL = 48 * 60 * 60  # 48h for "post-close batch done" flag


class MarketState(StrEnum):
    """Discrete market state used by the scheduler."""

    HOLIDAY = "holiday"  # library says no session today (or override closed)
    CLOSED = "closed"  # session exists, but we're outside open/close window
    OPEN = "open"  # currently in-session
    JUST_CLOSED = "just_closed"  # first tick on/after close_utc today


@dataclass(frozen=True)
class MarketSnapshot:
    """Per-market status at a given instant."""

    exchange: str
    now_utc: datetime
    state: MarketState
    session_hours: SessionHours
    is_half_day: bool


@dataclass(frozen=True)
class DispatchPlan:
    """One scheduled task to dispatch at this tick."""

    task_name: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    queue: str | None = None
    # Redis dedupe key. If a SET NX succeeds we dispatch; otherwise we skip.
    dedupe_key: str | None = None
    dedupe_ttl: int = _DEDUPE_TTL


@dataclass(frozen=True)
class SchedulerTick:
    """Result of a planning pass — one snapshot per market + a dispatch list."""

    now_utc: datetime
    snapshots: tuple[MarketSnapshot, ...]
    planned: tuple[DispatchPlan, ...]


def _minute_floor(ts: datetime) -> datetime:
    """Strip seconds/microseconds — all cadence math is in whole minutes."""
    return ts.replace(second=0, microsecond=0)


async def compute_market_state(
    calendar: CalendarService,
    exchange: str,
    now_utc: datetime,
) -> MarketSnapshot:
    """Classify one market's state at ``now_utc``.

    JUST_CLOSED is defined as: we are within 60 seconds after ``close_utc``.
    The tick runs once per minute, so this window guarantees the post-close
    batch fires exactly once per session (deduplicated via Redis flag
    regardless of tick jitter).
    """
    now_utc = now_utc.astimezone(UTC)
    # Query local-date for the exchange (not UTC date) so half-days and
    # DST-transition dates resolve to the right session row.
    from backend.app.services.calendar import _get_calendar

    tz = _get_calendar(exchange).tz
    session_date = now_utc.astimezone(tz).date()
    hours = await calendar.get_session_hours(exchange, session_date)

    if not hours.is_open or hours.open_utc is None or hours.close_utc is None:
        return MarketSnapshot(
            exchange=exchange,
            now_utc=now_utc,
            state=MarketState.HOLIDAY,
            session_hours=hours,
            is_half_day=False,
        )

    if now_utc < hours.open_utc:
        state = MarketState.CLOSED  # pre-open
    elif hours.open_utc <= now_utc < hours.close_utc:
        state = MarketState.OPEN
    elif hours.close_utc <= now_utc < (hours.close_utc + timedelta(minutes=1)):
        state = MarketState.JUST_CLOSED
    else:
        state = MarketState.CLOSED  # after close (or before next day's open)

    return MarketSnapshot(
        exchange=exchange,
        now_utc=now_utc,
        state=state,
        session_hours=hours,
        is_half_day=hours.is_half_day,
    )


class SessionAwareScheduler:
    """Plans and dispatches session-aware Celery tasks.

    Stateless across ticks — all dedupe/coordination state lives in Redis.
    A single instance is created per tick; nothing to share across ticks.
    """

    def __init__(self, calendar: CalendarService, redis: Redis | None) -> None:
        self._calendar = calendar
        self._redis = redis

    async def plan(
        self,
        now_utc: datetime,
        exchanges: tuple[str, ...] = SUPPORTED_EXCHANGES,
    ) -> SchedulerTick:
        """Build the dispatch plan for ``now_utc`` across ``exchanges``."""
        now_utc = _minute_floor(now_utc.astimezone(UTC))
        snaps: list[MarketSnapshot] = []
        plans: list[DispatchPlan] = []

        for mic in exchanges:
            snap = await compute_market_state(self._calendar, mic, now_utc)
            snaps.append(snap)

            session_date_str = (
                snap.session_hours.session_date.isoformat()
                if snap.session_hours.session_date
                else "unknown"
            )
            minute_stamp = now_utc.strftime("%Y%m%dT%H%M")

            if snap.state is MarketState.OPEN:
                # 5-minute indicator recalc (aligned to wall-clock boundary).
                if now_utc.minute % INDICATOR_RECALC_EVERY_MINUTES == 0:
                    plans.append(
                        DispatchPlan(
                            task_name="tasks.in_session.recalc_indicators",
                            kwargs={"exchange": mic},
                            dedupe_key=(
                                f"sched:last_dispatch:recalc:{mic}:{minute_stamp}"
                            ),
                        )
                    )
                # Hourly portfolio sync (top of the hour).
                if now_utc.minute % PORTFOLIO_SYNC_EVERY_MINUTES == 0:
                    plans.append(
                        DispatchPlan(
                            task_name="tasks.in_session.sync_portfolios",
                            kwargs={"exchange": mic},
                            dedupe_key=(
                                f"sched:last_dispatch:sync:{mic}:{minute_stamp}"
                            ),
                        )
                    )
            elif snap.state is MarketState.JUST_CLOSED:
                plans.append(
                    DispatchPlan(
                        task_name="tasks.post_close.run_post_close_batch",
                        kwargs={
                            "exchange": mic,
                            "session_date": session_date_str,
                            "is_half_day": snap.is_half_day,
                        },
                        dedupe_key=(
                            f"sched:post_close_done:{mic}:{session_date_str}"
                        ),
                        dedupe_ttl=_POST_CLOSE_TTL,
                    )
                )
            # HOLIDAY and CLOSED: in-session dispatch skipped. Always-running
            # jobs (news, FX) run via their own beat crontab entries.

        return SchedulerTick(
            now_utc=now_utc,
            snapshots=tuple(snaps),
            planned=tuple(plans),
        )

    async def apply(self, tick_result: SchedulerTick) -> list[DispatchPlan]:
        """Dispatch every plan whose Redis dedupe key can be claimed.

        Returns the list of actually-dispatched plans (useful for logs/tests).
        Plans whose dedupe key was already taken are silently skipped.
        """
        from backend.app.celery_app import celery_app

        dispatched: list[DispatchPlan] = []
        for plan in tick_result.planned:
            if not await self._claim(plan):
                logger.debug(
                    "scheduler: dedupe hit, skipping dispatch task=%s key=%s",
                    plan.task_name,
                    plan.dedupe_key,
                )
                continue
            celery_app.send_task(
                plan.task_name,
                args=plan.args,
                kwargs=plan.kwargs,
                queue=plan.queue,
            )
            dispatched.append(plan)
            logger.info(
                "scheduler: dispatched task=%s kwargs=%s",
                plan.task_name,
                plan.kwargs,
            )
        return dispatched

    async def _claim(self, plan: DispatchPlan) -> bool:
        """Atomically claim a dedupe key. No Redis → always claim (dev/test)."""
        if plan.dedupe_key is None:
            return True
        if self._redis is None:
            return True
        # SET NX EX — returns True only if the key was newly set.
        ok = await self._redis.set(
            plan.dedupe_key, "1", ex=plan.dedupe_ttl, nx=True
        )
        return bool(ok)


async def _tick_async(now_utc: datetime | None = None) -> dict[str, Any]:
    """Async entry — used by the Celery task wrapper and by tests."""
    from backend.app.db import _session_factory
    from backend.app.redis_client import get_redis

    now = now_utc or datetime.now(UTC)
    session: AsyncSession
    async with _session_factory()() as session:
        calendar = CalendarService(session)
        redis = get_redis()
        scheduler = SessionAwareScheduler(calendar, redis)
        plan = await scheduler.plan(now)
        dispatched = await scheduler.apply(plan)

    return {
        "now_utc": plan.now_utc.isoformat(),
        "snapshots": [
            {
                "exchange": s.exchange,
                "state": s.state.value,
                "is_half_day": s.is_half_day,
            }
            for s in plan.snapshots
        ],
        "dispatched": [
            {"task": p.task_name, "kwargs": p.kwargs} for p in dispatched
        ],
        "skipped": len(plan.planned) - len(dispatched),
    }


@shared_task(name="tasks.scheduler.tick")  # type: ignore[untyped-decorator]
def tick() -> dict[str, Any]:
    """Celery Beat entry point — runs once per minute.

    Schedules per-market tasks based on live session state. See module
    docstring for the full decision table.
    """
    return asyncio.run(_tick_async())
