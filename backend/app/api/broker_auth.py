"""Broker OAuth endpoints.

MVP exposes two routes per supported broker:

* ``GET  /api/auth/broker/{broker}/connect`` — returns the redirect URL the
  mobile app should open in a browser / embedded webview.
* ``POST /api/auth/broker/{broker}/callback`` — exchanges the OAuth ``code``
  for access / refresh tokens, encrypts them via
  :mod:`backend.app.services.encryption`, and persists a
  :class:`BrokerConnection` row.

Zerodha returns 501 in MVP (see :mod:`backend.app.brokers.zerodha`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlencode

from backend.app.auth.dependencies import get_current_user
from backend.app.brokers.zerodha import _last_kite_expiry_cutoff
from backend.app.config import get_settings
from backend.app.db import get_session
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.users import User
from backend.app.services.encryption import encrypt_token
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/auth/broker", tags=["broker-auth"])

BrokerName = Literal["alpaca", "zerodha"]


class BrokerConnectResponse(BaseModel):
    """OAuth handoff payload for the mobile client."""

    redirect_url: str = Field(..., description="URL for the client to open.")
    broker: BrokerName


class BrokerCallbackRequest(BaseModel):
    code: str = Field(..., min_length=1, description="OAuth authorization code.")
    state: str | None = None


class BrokerConnectionResponse(BaseModel):
    id: str
    broker: BrokerName
    account_id: str
    status: str


# Surface-level status the dashboard renders. Broader than the DB enum so
# consumers can pattern-match without having to know the underlying
# broker_conn_status_enum values.
ConnectionStatus = Literal["connected", "auth_expired", "error", "disconnected"]


class BrokerConnectionStatusItem(BaseModel):
    """Per-connection status row for the dashboard."""

    id: str
    broker: BrokerName
    account_id: str
    status: ConnectionStatus = Field(
        ...,
        description=(
            "connected | auth_expired | error | disconnected. "
            "``auth_expired`` is derived from the stored token_expires_at + the "
            "broker-specific expiry rule (Zerodha: 06:00 IST daily)."
        ),
    )
    token_expires_at: datetime | None = None


class BrokerConnectionsStatusResponse(BaseModel):
    connections: list[BrokerConnectionStatusItem]


def _derive_connection_status(
    conn: BrokerConnection, *, now_utc: datetime | None = None
) -> ConnectionStatus:
    """Compute surface status from the DB row.

    Mapping (MVP, no extra columns):

    * ``status == "revoked"`` -> ``disconnected``
    * ``status == "expired"`` -> ``auth_expired``
    * ``status == "active"`` but token is past the broker-specific cutoff
      -> ``auth_expired``. For Zerodha we use the 06:00 IST daily rule via
      :func:`_last_kite_expiry_cutoff` against ``token_expires_at``
      (stored as the "valid until" timestamp by the OAuth callback); for
      Alpaca a non-null ``token_expires_at`` in the past is treated as
      expired.
    * Otherwise: ``connected``.

    NOTE: ``last_auth_error`` column does not exist on BrokerConnection in
    MVP, so "error" is currently unreachable here. If a future migration
    adds it, extend this function rather than the endpoint body.
    """
    now_utc = now_utc or datetime.now(UTC)
    if conn.status == "revoked":
        return "disconnected"
    if conn.status == "expired":
        return "auth_expired"

    expires_at = conn.token_expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if conn.broker == "zerodha":
            # Zerodha tokens expire at the next 06:00 IST cutoff after issue;
            # if the stored expiry is at-or-before the most recent cutoff
            # (equivalent to: token was issued before today's cutoff), flag.
            if expires_at <= _last_kite_expiry_cutoff(now_utc):
                return "auth_expired"
        else:
            if expires_at <= now_utc:
                return "auth_expired"
    return "connected"


# --------------------------------------------------------------------- connect


@router.get("/{broker}/connect", response_model=BrokerConnectResponse)
async def broker_connect(
    broker: BrokerName,
    current_user: User = Depends(get_current_user),
) -> BrokerConnectResponse:
    """Return the OAuth redirect URL for the given broker.

    The caller (mobile) opens ``redirect_url`` in a system browser; the
    broker then redirects back to the configured callback URI with an
    authorization ``code`` query parameter.
    """
    settings = get_settings()
    if broker == "alpaca":
        client_id = settings.alpaca_oauth_client_id or settings.alpaca_api_key
        if not client_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Alpaca OAuth is not configured",
            )
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": settings.alpaca_oauth_redirect_uri,
            "scope": "account:write trading",
            "state": str(current_user.id),
        }
        url = f"https://app.alpaca.markets/oauth/authorize?{urlencode(params)}"
        return BrokerConnectResponse(redirect_url=url, broker="alpaca")

    # zerodha — stub
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Zerodha OAuth ships in M4",
    )


# --------------------------------------------------------------------- callback


@router.post(
    "/{broker}/callback",
    response_model=BrokerConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def broker_callback(
    broker: BrokerName,
    payload: BrokerCallbackRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BrokerConnectionResponse:
    """Exchange the OAuth code for tokens, encrypt, and persist.

    The real token-exchange HTTP call is stubbed in MVP — we store the raw
    ``code`` as a placeholder access token so downstream code has a concrete
    encrypt/decrypt path to exercise. When the live Alpaca OAuth app is
    registered, replace the ``placeholder_access_token`` block with an
    ``httpx.AsyncClient.post`` to Alpaca's ``/oauth/token`` endpoint.
    """
    if broker == "zerodha":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Zerodha OAuth ships in M4",
        )

    # TODO(m1-4): replace with real Alpaca token exchange once OAuth app is
    # registered. See TechSpec v1.3 §broker-oauth.
    placeholder_access_token = f"alpaca-access-{payload.code}"
    placeholder_refresh_token = f"alpaca-refresh-{payload.code}"
    account_id = f"paper-{str(current_user.id)[:8]}"

    access_encrypted = encrypt_token(placeholder_access_token, user_id=current_user.id)
    refresh_encrypted = encrypt_token(placeholder_refresh_token, user_id=current_user.id)

    conn = BrokerConnection(
        user_id=current_user.id,
        broker=broker,
        account_id=account_id,
        access_token_encrypted=access_encrypted,
        refresh_token_encrypted=refresh_encrypted,
        status="active",
    )
    session.add(conn)
    await session.commit()
    await session.refresh(conn)

    return BrokerConnectionResponse(
        id=str(conn.id),
        broker=broker,
        account_id=account_id,
        status=conn.status,
    )


# --------------------------------------------------------------------- status


@router.get("/connections", response_model=BrokerConnectionsStatusResponse)
async def list_broker_connections(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BrokerConnectionsStatusResponse:
    """List the caller's broker connections with dashboard-ready status.

    Exposes ``auth_expired`` (AC #4, M4-22) so the mobile dashboard can
    render a re-auth CTA without having to hit a broker-specific read
    endpoint first. Status is derived on-the-fly from the DB row — no
    ``last_auth_error`` column is required in MVP.
    """
    stmt = select(BrokerConnection).where(BrokerConnection.user_id == current_user.id)
    rows = list((await session.execute(stmt)).scalars().all())
    items: list[BrokerConnectionStatusItem] = []
    for row in rows:
        items.append(
            BrokerConnectionStatusItem(
                id=str(row.id),
                broker=row.broker,  # type: ignore[arg-type]
                account_id=row.account_id,
                status=_derive_connection_status(row),
                token_expires_at=row.token_expires_at,
            )
        )
    return BrokerConnectionsStatusResponse(connections=items)
