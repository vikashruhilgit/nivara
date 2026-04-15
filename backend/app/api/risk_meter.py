"""Portfolio Risk Meter API routes.

Exposes:

* ``GET /api/portfolio/risk-meter`` — overall score + color (AC #3-6).
* ``GET /api/portfolio/risk-meter/drilldown`` — all four components with
  individual scores, weights, and supporting detail (AC #7).

The engine in :mod:`backend.app.analysis.risk_meter` is pure. This module
handles the data-loading side: pulling the user's positions, reading price
history for each holding, flagging staleness, and projecting the engine
output onto the Pydantic response models.

Staleness (AC #12-13)
---------------------
We compute a single "data age" for the panel: the oldest ``as_of`` timestamp
across the user's positions. < 4 h → ``fresh``; 4-24 h → ``stale``; > 24 h
→ ``very_stale``. The stale reason mentions whichever dimension triggered
the flag so the UI can show context rather than a bare badge.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pandas as pd
from backend.app.analysis.risk_meter import RiskMeterResult, compute_risk_meter
from backend.app.analysis.technical import load_close_series_bulk
from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.instruments import Instrument
from backend.app.models.positions import Position
from backend.app.models.users import User
from backend.app.schemas.risk_meter import (
    RiskMeterComponentOut,
    RiskMeterDrilldownResponse,
    RiskMeterResponse,
)
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

_STALE_THRESHOLD = timedelta(hours=4)
_VERY_STALE_THRESHOLD = timedelta(hours=24)
_PRICE_BARS = 252  # 1 trading year, matches the single-instrument risk engine.


async def _load_portfolio_context(
    session: AsyncSession,
    user_id: UUID,
) -> tuple[list[float], dict[str, float], dict[str, pd.Series], datetime | None]:
    """Pull positions + price history needed for all four Risk Meter components.

    Returns:
      * ``holding_weights`` — positional weight list for concentration.
      * ``weights_by_symbol`` — symbol-keyed dict for VaR / drawdown.
      * ``price_series`` — symbol-keyed close-price series (may be partial
        when price history is missing for some holdings).
      * ``oldest_position_as_of`` — used for staleness classification.
    """
    stmt = (
        select(Position, Instrument)
        .join(BrokerConnection, BrokerConnection.id == Position.broker_connection_id)
        .join(Instrument, Instrument.id == Position.instrument_id)
        .where(BrokerConnection.user_id == user_id)
    )
    rows = list((await session.execute(stmt)).all())

    holding_weights: list[float] = []
    weights_by_symbol: dict[str, float] = {}
    price_series: dict[str, pd.Series] = {}
    oldest: datetime | None = None

    # Market-value weight proxy: quantity * avg_cost (same placeholder used
    # by PortfolioSummaryService until a live price feed lands).
    raw_values: list[tuple[Position, Instrument, Decimal]] = []
    total_value = Decimal("0")
    for position, instrument in rows:
        if position.quantity == 0:
            continue
        value = position.quantity * position.avg_cost
        raw_values.append((position, instrument, value))
        total_value += value
        if oldest is None or position.as_of < oldest:
            oldest = position.as_of

    if total_value > 0:
        # Single bulk load of close series across all holdings to avoid an
        # N+1 query (one DB round-trip instead of one per holding).
        instrument_ids = [instrument.id for _, instrument, _ in raw_values]
        closes_by_id = await load_close_series_bulk(session, instrument_ids, bars=_PRICE_BARS)
        for _position, instrument, value in raw_values:
            weight = float(value / total_value)
            holding_weights.append(weight)
            weights_by_symbol[instrument.symbol] = weight
            series = closes_by_id.get(instrument.id)
            if series is not None and not series.empty:
                price_series[instrument.symbol] = series

    return holding_weights, weights_by_symbol, price_series, oldest


def _classify_staleness(oldest: datetime | None) -> tuple[str, str | None]:
    if oldest is None:
        return "fresh", None
    now = datetime.now(UTC)
    comparable = oldest if oldest.tzinfo else oldest.replace(tzinfo=UTC)
    age = now - comparable
    if age > _VERY_STALE_THRESHOLD:
        hours = int(age.total_seconds() // 3600)
        return "very_stale", f"Data outdated — last sync {hours} h ago."
    if age > _STALE_THRESHOLD:
        hours = int(age.total_seconds() // 3600)
        return "stale", f"Underlying data {hours} h old."
    return "fresh", None


async def _compute_for_user(
    session: AsyncSession,
    user_id: UUID,
) -> tuple[RiskMeterResult, str, str | None]:
    holding_weights, weights_by_symbol, price_series, oldest = await _load_portfolio_context(
        session, user_id
    )
    result = compute_risk_meter(
        holding_weights=holding_weights,
        weights_by_symbol=weights_by_symbol,
        price_series=price_series,
        upcoming_events=None,  # no earnings calendar at MVP (per job risk mitigation)
        today=date.today(),
    )
    staleness, reason = _classify_staleness(oldest)
    return result, staleness, reason


@router.get("/risk-meter", response_model=RiskMeterResponse)
async def get_risk_meter(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RiskMeterResponse:
    """Return the overall Risk Meter score + color classification (AC #6)."""
    result, staleness, reason = await _compute_for_user(session, current_user.id)
    return RiskMeterResponse(
        overall_score=result.overall_score,
        color=result.color,
        staleness=staleness,
        stale_reason=reason,
    )


@router.get("/risk-meter/drilldown", response_model=RiskMeterDrilldownResponse)
async def get_risk_meter_drilldown(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RiskMeterDrilldownResponse:
    """Return all four component scores + weights + detail fields (AC #7)."""
    result, staleness, reason = await _compute_for_user(session, current_user.id)
    return RiskMeterDrilldownResponse(
        overall_score=result.overall_score,
        color=result.color,
        staleness=staleness,
        stale_reason=reason,
        components=[
            RiskMeterComponentOut(
                name=c.name, score=c.score, weight=c.weight, detail=dict(c.detail)
            )
            for c in result.components
        ],
    )


__all__ = ["router"]
