"""Celery application factory.

Single entry point for all scheduled and background tasks. Keeping the app
instance here (rather than inside ``tasks/__init__.py``) lets us import
``celery_app`` from both the worker process (``celery -A backend.app.celery_app
worker``) and the beat process (``celery -A backend.app.celery_app beat``)
without circular imports.

Task discovery is explicit: every task module is listed in ``include`` so
Celery autoloads them when the worker starts. This is safer than the
``autodiscover_tasks`` dance when the project layout isn't a Django app.

Configuration (broker, backend, timezone, custom scheduler) comes from
:func:`backend.app.config.get_settings` so tests can override via
``Settings(...)`` without touching environment variables.
"""

from __future__ import annotations

from backend.app.config import get_settings
from celery import Celery
from celery.schedules import crontab


def create_celery_app() -> Celery:
    """Build the Celery app with broker/backend wired from settings.

    Beat schedule here covers the *always-running* and *weekly* jobs that run
    on a plain clock (news, FX, calendar verify). In-session and post-close
    jobs are dispatched dynamically by the custom scheduler
    (see :mod:`backend.app.scheduling.scheduler`) rather than via crontab,
    because their timing depends on live market session state.
    """
    settings = get_settings()
    app = Celery(
        "investiq",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=[
            "backend.app.tasks.in_session",
            "backend.app.tasks.post_close",
            "backend.app.tasks.always",
            "backend.app.tasks.calendar_verify",
            "backend.app.tasks.ai_analysis",
        ],
    )
    app.conf.update(
        timezone="UTC",
        enable_utc=True,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        # Short default timeouts — individual tasks can override via
        # ``@shared_task(..., time_limit=...)`` when they genuinely need more.
        task_time_limit=600,  # hard kill at 10min
        task_soft_time_limit=540,  # SIGTERM at 9min for graceful shutdown
        # Each market and pipeline gets its own queue so we can isolate
        # expensive workers (e.g. FinBERT-loaded sentiment worker) from
        # latency-sensitive ones.
        task_default_queue="default",
        task_routes={
            "tasks.sentiment.*": {"queue": "sentiment"},
            "tasks.ai_analysis.*": {"queue": "ai_analysis"},
        },
        # Always-running + weekly jobs. Session-sensitive jobs (in-session,
        # post-close) are NOT listed here — the custom scheduler dispatches
        # them based on live session state.
        beat_schedule={
            "news-sentiment-every-15min": {
                "task": "tasks.always.refresh_news_sentiment",
                "schedule": crontab(minute="*/15"),
            },
            "fx-daily-0600-utc": {
                "task": "tasks.always.refresh_fx",
                "schedule": crontab(minute=0, hour=6),
            },
            "calendar-verify-weekly-sun-0300-utc": {
                "task": "calendar.verify_weekly",
                "schedule": crontab(minute=0, hour=3, day_of_week="sun"),
            },
            # Tick the session-aware scheduler every minute. It decides
            # which in-session / post-close jobs to dispatch based on
            # current market state.
            "session-scheduler-tick-every-minute": {
                "task": "tasks.scheduler.tick",
                "schedule": crontab(minute="*"),
            },
        },
    )
    return app


# Module-level app instance for `celery -A backend.app.celery_app` CLI.
celery_app = create_celery_app()
