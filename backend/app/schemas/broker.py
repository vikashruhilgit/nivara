"""Normalized Pydantic v2 schemas shared across broker adapters.

Adapters MUST return these shapes (not broker-native dicts) so downstream
consumers — portfolio sync, risk engine, UI — stay broker-agnostic.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OrderSide = Literal["buy", "sell"]
OrderStatus = Literal[
    "new", "partially_filled", "filled", "canceled", "rejected", "expired", "pending"
]
OrderType = Literal["market", "limit", "stop", "stop_limit"]
Currency = Literal["USD", "INR", "EUR", "GBP"]


class NormalizedPosition(BaseModel):
    """Single open position at a broker, normalized across vendors."""

    model_config = ConfigDict(frozen=True)

    broker_symbol: str = Field(..., description="Raw symbol as reported by broker (pre-mapping).")
    quantity: Decimal = Field(..., description="Signed position quantity (negative = short).")
    avg_entry_price: Decimal = Field(..., ge=0)
    current_price: Decimal = Field(..., ge=0)
    market_value: Decimal
    unrealized_pl: Decimal
    currency: Currency = "USD"
    exchange: str | None = None


class NormalizedBalance(BaseModel):
    """Cash / equity snapshot for a brokerage account."""

    model_config = ConfigDict(frozen=True)

    cash: Decimal = Field(..., description="Buying-power / available cash.")
    equity: Decimal = Field(..., description="Total account equity (cash + positions).")
    currency: Currency = "USD"
    account_id: str


class NormalizedOrder(BaseModel):
    """Order record (open or historical), normalized across vendors."""

    model_config = ConfigDict(frozen=True)

    broker_order_id: str
    broker_symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal = Field(..., gt=0)
    filled_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    status: OrderStatus
    submitted_at: datetime
    filled_at: datetime | None = None
    currency: Currency = "USD"
