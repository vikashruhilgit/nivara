"""Broker OAuth endpoints.

Routes:

* ``GET  /api/auth/broker/{broker}/connect`` — returns the redirect URL the
  mobile app should open in a browser / embedded webview.
* ``POST /api/auth/broker/alpaca/credentials`` — Alpaca's primary connect path:
  verifies per-user API keys against Alpaca, encrypts them via
  :mod:`backend.app.services.encryption`, and persists a
  :class:`BrokerConnection` row.
* ``POST /api/auth/broker/{broker}/callback`` — the legacy OAuth callback;
  Alpaca is retired here (returns 410 Gone) in favour of the credentials
  endpoint.

Zerodha returns 501 in MVP (see :mod:`backend.app.brokers.zerodha`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlencode

from backend.app.auth.dependencies import get_current_user
from backend.app.brokers.alpaca import AlpacaAdapter
from backend.app.brokers.errors import BrokerAPIError, BrokerErrorCode
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


class AlpacaCredentialsRequest(BaseModel):
    api_key_id: str = Field(..., min_length=1, description="Alpaca API Key ID.")
    api_secret: str = Field(..., min_length=1, description="Alpaca API Secret.")


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


# --------------------------------------------------------- alpaca credentials


async def _verify_alpaca_account(api_key_id: str, api_secret: str) -> str:
    """Verify Alpaca credentials by calling GET /v2/account; return the account_id.

    Raises BrokerAPIError on any broker-side failure (caller maps to HTTP).
    Never logs the key id or secret.
    """
    settings = get_settings()
    adapter = AlpacaAdapter(
        api_key=api_key_id,
        api_secret=api_secret,
        base_url=settings.alpaca_base_url,
    )
    async with adapter:
        balance = await adapter.get_balances()
    return balance.account_id


@router.post(
    "/alpaca/credentials",
    response_model=BrokerConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def connect_alpaca_credentials(
    payload: AlpacaCredentialsRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BrokerConnectionResponse:
    """Connect Alpaca using per-user API keys (Key ID + Secret).

    Verifies the credentials against Alpaca's ``GET /v2/account`` before
    persisting. On success, encrypts and stores them on a
    :class:`BrokerConnection` row; on failure no row is created.
    """
    try:
        account_id = await _verify_alpaca_account(payload.api_key_id, payload.api_secret)
    except BrokerAPIError as exc:
        if exc.code == BrokerErrorCode.AUTH_EXPIRED:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Alpaca rejected the provided credentials",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not verify Alpaca credentials — try again",
        ) from exc

    # Storage shape (per-user Alpaca API keys, no migration): Key ID -> access_token_encrypted,
    # API Secret -> refresh_token_encrypted (reuses the existing nullable LargeBinary column).
    access_token_encrypted = encrypt_token(payload.api_key_id, user_id=current_user.id)
    refresh_token_encrypted = encrypt_token(payload.api_secret, user_id=current_user.id)

    conn = BrokerConnection(
        user_id=current_user.id,
        broker="alpaca",
        account_id=account_id,
        access_token_encrypted=access_token_encrypted,
        refresh_token_encrypted=refresh_token_encrypted,
        status="active",
    )
    session.add(conn)
    await session.commit()
    await session.refresh(conn)

    return BrokerConnectionResponse(
        id=str(conn.id),
        broker="alpaca",
        account_id=conn.account_id,
        status=conn.status,
    )


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

    NOTE: Alpaca now primarily connects via the per-user credentials endpoint
    (``POST /api/auth/broker/alpaca/credentials``); this OAuth-URL behaviour is
    retained scaffolding for a future real-OAuth follow-up.
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
    """Retired OAuth callback handler.

    The Alpaca OAuth callback is retired in favour of the per-user credentials
    endpoint (``POST /api/auth/broker/alpaca/credentials``); it previously
    stored insecure placeholder tokens and now returns 410 Gone. Zerodha
    remains a 501 stub until its OAuth ships.
    """
    if broker == "zerodha":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Zerodha OAuth ships in M4",
        )

    if broker == "alpaca":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Alpaca now connects via POST /api/auth/broker/alpaca/credentials "
                "(per-user API keys)"
            ),
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
