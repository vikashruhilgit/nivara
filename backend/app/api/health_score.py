"""Portfolio Health Score API route.

Exposes ``GET /api/portfolio/health-score`` — the daily, four-component
quality score for the user's portfolio. The engine in
:mod:`backend.app.analysis.health_score` is pure; this module handles data
loading, Redis-backed daily caching (AC #11), and staleness flagging
(AC #14).

Caching model
-------------
We cache the computed response per user under ``portfolio:health_score:{uid}``
with a 24-hour TTL. This gives "updated daily" semantics (AC #11) without
requiring a separate scheduled job: the first request of each day recomputes
and seeds the cache. If Redis is unavailable the endpoint falls through to
live computation and simply serves it uncached.

Benchmark data
--------------
The current ``DataProvider`` layer does not expose "benchmark close series"
as a first-class thing, so the risk-adjusted component degrades to ``None``
at MVP. That is the intended behaviour per the risk assessment in the job
brief.
"""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pandas as pd
from backend.app.analysis.health_score import compute_health_score
from backend.app.analysis.technical import load_ohlcv_from_db
from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.instruments import Instrument
from backend.app.models.positions import Position
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from backend.app.schemas.health_score import HealthScoreComponentOut, HealthScoreResponse
from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

_PRICE_BARS = 252
_CACHE_TTL_SECONDS = 24 * 60 * 60
_VERY_STALE_THRESHOLD = timedelta(hours=24)
_STALE_THRESHOLD = timedelta(hours=4)
_STALE_WARNING = "Data outdated — score may not reflect current conditions"  # AC #14


def _cache_key(user_id: UUID) -> str:
    return f"portfolio:health_score:{user_id}"


async def _compute_response(session: AsyncSession, user_id: UUID) -> HealthScoreResponse:
    stmt = (
        select(Position, Instrument)
        .join(BrokerConnection, BrokerConnection.id == Position.broker_connection_id)
        .join(Instrument, Instrument.id == Position.instrument_id)
        .where(BrokerConnection.user_id == user_id)
    )
    rows = list((await session.execute(stmt)).all())

    holding_weights: list[float] = []
    portfolio_value_series: list[pd.Series] = []
    total_value = Decimal("0")
    oldest: datetime | None = None

    raw: list[tuple[Position, Instrument, Decimal]] = []
    for position, instrument in rows:
        if position.quantity == 0:
            continue
        value = position.quantity * position.avg_cost
        raw.append((position, instrument, value))
        total_value += value
        if oldest is None or position.as_of < oldest:
            oldest = position.as_of

    # Fundamental and technical inputs are plumbed through as optional
    # per-holding scores. At MVP there's no on-disk cache of these per user,
    # so we seed them as None — the engine then renormalises across the
    # remaining components rather than pretending.
    fundamental_scores: list[float | None] = [None] * len(raw)
    technical_scores: list[float | None] = [None] * len(raw)

    if total_value > 0:
        for _position, instrument, value in raw:
            weight = float(value / total_value)
            holding_weights.append(weight)
            frame = await load_ohlcv_from_db(session, instrument.id, bars=_PRICE_BARS)
            if frame.empty:
                continue
            base = float(frame["close"].iloc[0])
            if base <= 0:
                continue
            normalised = (frame["close"].astype(float) / base) * weight
            portfolio_value_series.append(normalised)

    if portfolio_value_series:
        portfolio_values = pd.concat(portfolio_value_series, axis=1).ffill().sum(axis=1).dropna()
        portfolio_returns = portfolio_values.pct_change().dropna()
    else:
        portfolio_returns = pd.Series(dtype=float)

    result = compute_health_score(
        holding_weights=holding_weights,
        fundamental_scores=fundamental_scores,
        technical_scores=technical_scores,
        portfolio_returns=portfolio_returns,
        benchmark_returns=None,  # benchmark ingestion deferred — AC mitigation in brief
    )

    staleness, warning = _classify_staleness(oldest)
    return HealthScoreResponse(
        overall_score=result.overall_score,
        components=[
            HealthScoreComponentOut(
                name=c.name, score=c.score, weight=c.weight, detail=dict(c.detail)
            )
            for c in result.components
        ],
        staleness=staleness,
        stale_warning=warning,
        computed_at=datetime.now(UTC).isoformat(),
    )


def _classify_staleness(oldest: datetime | None) -> tuple[str, str | None]:
    if oldest is None:
        return "fresh", None
    now = datetime.now(UTC)
    comparable = oldest if oldest.tzinfo else oldest.replace(tzinfo=UTC)
    age = now - comparable
    if age > _VERY_STALE_THRESHOLD:
        return "very_stale", _STALE_WARNING
    if age > _STALE_THRESHOLD:
        return "stale", None
    return "fresh", None


@router.get("/health-score", response_model=HealthScoreResponse)
async def get_health_score(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> HealthScoreResponse:
    """Return the portfolio Health Score with a 24 h Redis cache (AC #10, #11)."""
    key = _cache_key(current_user.id)
    # Cache read is best-effort — Redis failures must not break the endpoint.
    cached: str | None = None
    try:
        cached_bytes = await redis.get(key)
        if cached_bytes is not None:
            cached = (
                cached_bytes.decode()
                if isinstance(cached_bytes, bytes | bytearray)
                else str(cached_bytes)
            )
    except Exception as exc:  # noqa: BLE001 — Redis optional in dev / tests
        logger.warning("Health-score cache read failed: %s", exc)

    if cached is not None:
        try:
            return HealthScoreResponse.model_validate_json(cached)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Health-score cache payload invalid, recomputing: %s", exc)

    response = await _compute_response(session, current_user.id)
    with contextlib.suppress(Exception):
        await redis.set(key, json.dumps(response.model_dump()), ex=_CACHE_TTL_SECONDS)
    return response


__all__ = ["router"]
