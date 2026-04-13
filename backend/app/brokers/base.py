"""Abstract broker adapter.

Every concrete broker integration (Alpaca, Zerodha, future: IBKR) subclasses
:class:`BrokerAdapter` and fills in the async read methods plus symbol
normalization. Write-path (:meth:`place_order`) is intentionally abstract but
MVP adapters raise :class:`NotImplementedError` to reinforce read-only scope.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from backend.app.schemas.broker import (
    NormalizedBalance,
    NormalizedOrder,
    NormalizedPosition,
    OrderSide,
    OrderType,
)


@dataclass(frozen=True)
class BrokerFeatures:
    """Capability flags exposed by a broker adapter.

    Consumers consult this dict before invoking methods so the abstraction
    stays honest — e.g. Zerodha MVP stub has ``supports_positions=False``.
    """

    supports_positions: bool
    supports_balances: bool
    supports_orders: bool
    supports_place_order: bool
    supports_oauth: bool


class BrokerAdapter(ABC):
    """Abstract interface every broker integration must satisfy."""

    #: Short broker identifier matching the ``broker_enum`` DB enum
    #: (e.g. ``"alpaca"``, ``"zerodha"``).
    broker_name: str

    @property
    @abstractmethod
    def features(self) -> BrokerFeatures:
        """Capability flags for this adapter."""

    @abstractmethod
    async def get_positions(self) -> list[NormalizedPosition]:
        """Return open positions for the authenticated account.

        Raises:
            BrokerAPIError: transport, auth, or upstream failure.
        """

    @abstractmethod
    async def get_balances(self) -> NormalizedBalance:
        """Return the account cash / equity snapshot.

        Raises:
            BrokerAPIError: transport, auth, or upstream failure.
        """

    @abstractmethod
    async def get_orders(self, *, open_only: bool = False) -> list[NormalizedOrder]:
        """Return orders (open + historical, unless ``open_only=True``)."""

    @abstractmethod
    def normalize_symbol(self, broker_symbol: str) -> str:
        """Normalize a broker-specific symbol to the platform-canonical form."""

    @abstractmethod
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
        """Submit an order. MVP adapters raise :class:`NotImplementedError`.

        The ``idempotency_key`` MUST be derived from
        ``(broker_connection_id, instrument_id)`` per CLAUDE.md — never from
        the raw broker symbol.
        """
