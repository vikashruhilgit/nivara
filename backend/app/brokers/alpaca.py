"""Alpaca broker adapter (paper-trading, read-only).

Implementation note
-------------------
The brief suggests ``alpaca-py``; we instead talk to Alpaca's REST API over
:mod:`httpx` (async). Rationale:

* MVP is **read-only** — ``get_positions``, ``get_balances``, ``get_orders``
  are 3 simple GETs. Pulling in ``alpaca-py`` (which has transitive deps on
  websocket / streaming) is overkill.
* ``httpx`` is already a project dependency.
* Conformance tests can mock :class:`httpx.AsyncClient` cleanly.

Write-path (``place_order``) intentionally raises :class:`NotImplementedError`
— MVP is read-only (see TechSpec v1.3 and brief AC #8). When trading ships,
swap to ``alpaca-py``'s ``TradingClient.submit_order`` and honour the
``(broker_connection_id, instrument_id)`` idempotency contract.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx
from backend.app.brokers.base import BrokerAdapter, BrokerFeatures
from backend.app.brokers.errors import BrokerAPIError, BrokerErrorCode
from backend.app.schemas.broker import (
    NormalizedBalance,
    NormalizedOrder,
    NormalizedPosition,
    OrderSide,
    OrderStatus,
    OrderType,
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0

# Alpaca order status → NormalizedOrder.status
_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "new": "new",
    "accepted": "new",
    "pending_new": "pending",
    "accepted_for_bidding": "pending",
    "partially_filled": "partially_filled",
    "filled": "filled",
    "done_for_day": "filled",
    "canceled": "canceled",
    "expired": "expired",
    "rejected": "rejected",
    "stopped": "canceled",
    "suspended": "pending",
    "pending_cancel": "pending",
    "pending_replace": "pending",
    "replaced": "new",
}

_ORDER_TYPE_MAP: dict[str, OrderType] = {
    "market": "market",
    "limit": "limit",
    "stop": "stop",
    "stop_limit": "stop_limit",
}


class AlpacaAdapter(BrokerAdapter):
    """Read-only Alpaca adapter (paper-trading by default)."""

    broker_name = "alpaca"

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str = "https://paper-api.alpaca.markets",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._client = http_client  # injectable for tests
        self._owns_client = http_client is None

    # ------------------------------------------------------------------ features

    @property
    def features(self) -> BrokerFeatures:
        return BrokerFeatures(
            supports_positions=True,
            supports_balances=True,
            supports_orders=True,
            supports_place_order=False,  # MVP read-only
            supports_oauth=True,
        )

    # ------------------------------------------------------------------ helpers

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._api_secret,
            "Accept": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> AlpacaAdapter:
        await self._get_client()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        client = await self._get_client()
        url = f"{self._base_url}{path}"
        try:
            resp = await client.request(
                method, url, headers=self._headers(), **kwargs
            )
        except httpx.TimeoutException as exc:
            raise BrokerAPIError(
                BrokerErrorCode.NETWORK_TIMEOUT,
                f"Alpaca request timed out: {path}",
                broker=self.broker_name,
            ) from exc
        except httpx.TransportError as exc:
            raise BrokerAPIError(
                BrokerErrorCode.UPSTREAM_DOWN,
                f"Alpaca transport error: {exc}",
                broker=self.broker_name,
            ) from exc

        if resp.status_code == 401 or resp.status_code == 403:
            raise BrokerAPIError(
                BrokerErrorCode.AUTH_EXPIRED,
                "Alpaca rejected credentials",
                broker=self.broker_name,
                status_code=resp.status_code,
            )
        if resp.status_code == 404:
            raise BrokerAPIError(
                BrokerErrorCode.INSTRUMENT_UNKNOWN,
                f"Alpaca returned 404 for {path}",
                broker=self.broker_name,
                status_code=404,
            )
        if resp.status_code == 429:
            raise BrokerAPIError(
                BrokerErrorCode.RATE_LIMITED,
                "Alpaca rate limit exceeded",
                broker=self.broker_name,
                status_code=429,
            )
        if 500 <= resp.status_code < 600:
            raise BrokerAPIError(
                BrokerErrorCode.UPSTREAM_DOWN,
                f"Alpaca upstream error {resp.status_code}",
                broker=self.broker_name,
                status_code=resp.status_code,
            )
        if resp.status_code >= 400:
            raise BrokerAPIError(
                BrokerErrorCode.UPSTREAM_DOWN,
                f"Alpaca unexpected status {resp.status_code}: {resp.text[:200]}",
                broker=self.broker_name,
                status_code=resp.status_code,
            )
        return resp.json()

    # ------------------------------------------------------------------ reads

    async def get_positions(self) -> list[NormalizedPosition]:
        raw = await self._request("GET", "/v2/positions")
        return [self._parse_position(p) for p in raw]

    async def get_balances(self) -> NormalizedBalance:
        raw = await self._request("GET", "/v2/account")
        return NormalizedBalance(
            cash=Decimal(str(raw.get("cash", "0"))),
            equity=Decimal(str(raw.get("equity", "0"))),
            currency=raw.get("currency", "USD"),
            account_id=str(raw.get("account_number") or raw.get("id") or ""),
        )

    async def get_orders(self, *, open_only: bool = False) -> list[NormalizedOrder]:
        params: dict[str, str] = {"status": "open" if open_only else "all", "limit": "500"}
        raw = await self._request("GET", "/v2/orders", params=params)
        return [self._parse_order(o) for o in raw]

    # ------------------------------------------------------------------ normalize

    def normalize_symbol(self, broker_symbol: str) -> str:
        """Alpaca symbols are already AAPL / TSLA style. Uppercase + strip."""
        return broker_symbol.strip().upper()

    # ------------------------------------------------------------------ writes

    async def place_order(
        self,
        *,
        broker_symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = "market",
        limit_price: float | None = None,
        idempotency_key: str,
    ) -> NormalizedOrder:
        raise NotImplementedError(
            "AlpacaAdapter.place_order is intentionally not implemented in MVP "
            "(read-only). Trading ships in a later milestone."
        )

    # ------------------------------------------------------------------ parse helpers

    @staticmethod
    def _parse_position(raw: dict[str, Any]) -> NormalizedPosition:
        qty = Decimal(str(raw.get("qty", "0")))
        avg = Decimal(str(raw.get("avg_entry_price", "0")))
        current = Decimal(str(raw.get("current_price", raw.get("market_price", "0"))))
        market_value = Decimal(str(raw.get("market_value", "0")))
        unrealized = Decimal(str(raw.get("unrealized_pl", "0")))
        return NormalizedPosition(
            broker_symbol=str(raw.get("symbol", "")),
            quantity=qty,
            avg_entry_price=avg,
            current_price=current,
            market_value=market_value,
            unrealized_pl=unrealized,
            currency="USD",
            exchange=raw.get("exchange"),
        )

    @staticmethod
    def _parse_order(raw: dict[str, Any]) -> NormalizedOrder:
        status = _ORDER_STATUS_MAP.get(raw.get("status", ""), "pending")
        order_type = _ORDER_TYPE_MAP.get(raw.get("order_type", raw.get("type", "market")), "market")
        side: OrderSide = "buy" if raw.get("side") == "buy" else "sell"
        limit = raw.get("limit_price")
        stop = raw.get("stop_price")
        return NormalizedOrder(
            broker_order_id=str(raw.get("id", "")),
            broker_symbol=str(raw.get("symbol", "")),
            side=side,
            order_type=order_type,
            quantity=Decimal(str(raw.get("qty", "0"))),
            filled_quantity=Decimal(str(raw.get("filled_qty", "0"))),
            limit_price=Decimal(str(limit)) if limit is not None else None,
            stop_price=Decimal(str(stop)) if stop is not None else None,
            status=status,
            submitted_at=raw["submitted_at"],
            filled_at=raw.get("filled_at"),
            currency="USD",
        )
