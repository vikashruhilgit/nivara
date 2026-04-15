"""Portfolio API routes.

Exposes:

* ``POST /api/portfolio/sync`` — manual sync trigger; pulls positions and
  orders from the user's active broker connection into local tables.
* ``GET  /api/portfolio/summary`` — aggregated value in the user's base
  currency, with stale-data flag.
* ``GET  /api/portfolio/positions`` — all positions with native + base
  currency views.

All routes require an authenticated user. Sync is guarded by a per-user
Redis lock so two concurrent triggers for the same user don't race.
"""

from __future__ import annotations

import contextlib
import logging

from backend.app.auth.dependencies import get_current_user
from backend.app.brokers.alpaca import AlpacaAdapter
from backend.app.brokers.base import BrokerAdapter
from backend.app.brokers.errors import BrokerAPIError, BrokerErrorCode
from backend.app.brokers.rate_limiter import get_zerodha_rate_limiter
from backend.app.brokers.zerodha import ZerodhaAdapter
from backend.app.config import get_settings
from backend.app.db import get_session
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from backend.app.schemas.portfolio import (
    PortfolioSummaryOut,
    PositionsList,
    SyncResult,
)
from backend.app.services.audit import AuditService
from backend.app.services.encryption import decrypt_token
from backend.app.services.fx import FxService
from backend.app.services.portfolio_summary import PortfolioSummaryService
from backend.app.services.portfolio_sync import PortfolioSyncService
from backend.app.services.symbol_mapping import SymbolMappingService
from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

# Redis lock TTL per user sync (seconds). Guards against stuck locks if the
# process dies mid-sync — the lock naturally expires.
_SYNC_LOCK_TTL = 60


def _summary_service(session: AsyncSession = Depends(get_session)) -> PortfolioSummaryService:
    return PortfolioSummaryService(session=session, fx=FxService(session))


def _build_adapter(connection: BrokerConnection, user_id_bytes: bytes) -> BrokerAdapter:
    """Construct a broker adapter for the given connection.

    Injected into sync routes so tests can override via
    ``app.dependency_overrides``. Raises 501 for brokers not yet supported in
    the read path.
    """
    settings = get_settings()
    if connection.broker == "alpaca":
        # Alpaca's read API uses the api-key/secret headers directly; we decrypt
        # the stored access token and reuse settings' API secret. In MVP the
        # token stored IS the api key; full OAuth flow lands in a later job.
        access_key = decrypt_token(connection.access_token_encrypted, user_id=connection.user_id)
        api_secret = settings.alpaca_api_secret or ""
        return AlpacaAdapter(
            api_key=access_key,
            api_secret=api_secret,
            base_url=settings.alpaca_base_url,
        )
    if connection.broker == "zerodha":
        # Kite Connect requires the app's api_key + api_secret (from settings)
        # plus the user-scoped daily access_token (stored encrypted on the
        # connection row). The global rate limiter is shared across workers
        # via the Redis-backed singleton.
        api_key = settings.zerodha_api_key or ""
        api_secret = settings.zerodha_api_secret or ""
        if not api_key or not api_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Zerodha (Kite Connect) is not configured",
            )
        access_token = decrypt_token(connection.access_token_encrypted, user_id=connection.user_id)
        return ZerodhaAdapter(
            api_key=api_key,
            api_secret=api_secret,
            access_token=access_token,
            access_token_issued_at=connection.token_expires_at,
            rate_limiter=get_zerodha_rate_limiter(),
        )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Sync not implemented for broker: {connection.broker}",
    )


@router.post(
    "/sync",
    response_model=SyncResult,
    status_code=status.HTTP_200_OK,
)
async def sync_portfolio(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> SyncResult:
    """Trigger a manual portfolio sync for the user's active broker connection.

    Returns a :class:`SyncResult` with counts. Idempotent — re-running produces
    no duplicate rows (positions keyed by ``(broker_connection_id, instrument_id)``,
    orders by ``broker_order_id``).
    """
    conn_stmt = (
        select(BrokerConnection)
        .where(
            BrokerConnection.user_id == current_user.id,
            BrokerConnection.status == "active",
        )
        .limit(1)
    )
    connection = (await session.execute(conn_stmt)).scalar_one_or_none()
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active broker connection",
        )

    lock_key = f"portfolio:sync:lock:{current_user.id}"
    lock_acquired = False
    try:
        # ``set(..., nx=True, ex=TTL)`` — acquire-or-fail without blocking.
        try:
            lock_acquired = bool(await redis.set(lock_key, "1", nx=True, ex=_SYNC_LOCK_TTL))
        except Exception as exc:  # noqa: BLE001 — Redis optional in dev / tests
            logger.warning("Redis lock unavailable, proceeding without lock: %s", exc)
            lock_acquired = True  # treat as acquired so we still run

        if not lock_acquired:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Sync already in progress for this user",
            )

        adapter = _build_adapter(connection, current_user.id.bytes)
        mapping_svc = SymbolMappingService(session)
        audit_svc = AuditService(session)
        sync_svc = PortfolioSyncService(
            session=session, mapping_service=mapping_svc, audit_service=audit_svc
        )

        try:
            async with adapter:  # type: ignore[attr-defined]
                result = await sync_svc.sync_connection(
                    connection=connection,
                    adapter=adapter,
                    user_id=current_user.id,
                )
        except BrokerAPIError as exc:
            logger.exception("Broker sync failed: %s", exc)
            # Surface token-expired state on the connection row so the
            # dashboard's /api/auth/broker/connections endpoint reports
            # ``auth_expired`` without re-hitting the broker. We piggy-back
            # on the existing broker_conn_status_enum ("expired") rather
            # than adding a ``last_auth_error`` column in this job.
            if exc.code == BrokerErrorCode.AUTH_EXPIRED:
                connection.status = "expired"
                await session.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Broker sync failed: {exc}",
            ) from exc

        await session.commit()

        return SyncResult(
            broker_connection_id=result.broker_connection_id,
            synced_at=result.synced_at,
            positions_upserted=result.positions_upserted,
            positions_closed=result.positions_closed,
            orders_upserted=result.orders_upserted,
            positions_skipped=result.positions_skipped,
            warnings=result.warnings,
        )
    finally:
        if lock_acquired:
            with contextlib.suppress(Exception):
                await redis.delete(lock_key)


@router.get("/summary", response_model=PortfolioSummaryOut)
async def get_summary(
    current_user: User = Depends(get_current_user),
    svc: PortfolioSummaryService = Depends(_summary_service),
) -> PortfolioSummaryOut:
    """Return aggregated portfolio value in the user's base currency."""
    base = get_settings().default_base_currency.upper()
    return await svc.summary(user_id=current_user.id, base_currency=base)


@router.get("/positions", response_model=PositionsList)
async def get_positions(
    current_user: User = Depends(get_current_user),
    svc: PortfolioSummaryService = Depends(_summary_service),
) -> PositionsList:
    """Return all positions with native + base currency valuation."""
    base = get_settings().default_base_currency.upper()
    return await svc.list_positions(user_id=current_user.id, base_currency=base)
