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

from typing import Literal
from urllib.parse import urlencode

from backend.app.auth.dependencies import get_current_user
from backend.app.config import get_settings
from backend.app.db import get_session
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.users import User
from backend.app.services.encryption import encrypt_token
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
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
