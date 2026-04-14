"""Zerodha (Kite Connect) adapter — MVP stub.

Every method except :pyattr:`features` raises :class:`NotImplementedError` so
integration paths (portfolio sync, recommendations) can route requests here
and fail fast during development. Full implementation ships in M4 (see brief
``m4-22-zerodha-adapter.md``).
"""

from __future__ import annotations

from backend.app.brokers.base import BrokerAdapter, BrokerFeatures
from backend.app.schemas.broker import (
    NormalizedBalance,
    NormalizedOrder,
    NormalizedPosition,
    OrderSide,
    OrderType,
)


class ZerodhaAdapter(BrokerAdapter):
    broker_name = "zerodha"

    def __init__(self, *, api_key: str | None = None, api_secret: str | None = None) -> None:
        self._api_key = api_key
        self._api_secret = api_secret

    @property
    def features(self) -> BrokerFeatures:
        return BrokerFeatures(
            supports_positions=False,
            supports_balances=False,
            supports_orders=False,
            supports_place_order=False,
            supports_oauth=False,
        )

    async def get_positions(self) -> list[NormalizedPosition]:
        raise NotImplementedError("ZerodhaAdapter.get_positions ships in M4")

    async def get_balances(self) -> NormalizedBalance:
        raise NotImplementedError("ZerodhaAdapter.get_balances ships in M4")

    async def get_orders(self, *, open_only: bool = False) -> list[NormalizedOrder]:
        raise NotImplementedError("ZerodhaAdapter.get_orders ships in M4")

    def normalize_symbol(self, broker_symbol: str) -> str:
        raise NotImplementedError("ZerodhaAdapter.normalize_symbol ships in M4")

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
        raise NotImplementedError("ZerodhaAdapter.place_order ships post-MVP")
