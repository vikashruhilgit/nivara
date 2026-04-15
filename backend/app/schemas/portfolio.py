"""Portfolio response schemas (Pydantic v2).

Shapes returned by ``/api/portfolio/*`` endpoints. All money values carry an
explicit currency, and dual-currency views (native + base) are expressed as
two separate fields rather than nesting so clients don't need to know the
conversion rule.

Stale detection
---------------
``PortfolioSummaryOut.is_stale`` flips to ``True`` when the most recent
position sync for the user's active broker connection is older than the
configured threshold (2h per TechSpec). Confidence is reduced via
``confidence`` (1.0 = fresh, 0.5 = stale).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SyncResult(BaseModel):
    """Outcome of a manual portfolio sync trigger."""

    model_config = ConfigDict(from_attributes=True)

    broker_connection_id: UUID
    synced_at: datetime
    positions_upserted: int = Field(..., ge=0)
    positions_closed: int = Field(..., ge=0)
    orders_upserted: int = Field(..., ge=0)
    positions_skipped: int = Field(
        default=0,
        ge=0,
        description="Positions skipped because instrument resolution failed.",
    )
    warnings: list[str] = Field(default_factory=list)


class FxAttributionOut(BaseModel):
    """Cross-currency return attribution attached to a position.

    ``None`` for same-currency positions.
    """

    model_config = ConfigDict(from_attributes=True)

    stock_return_pct: Decimal
    fx_impact_pct: Decimal
    base_return_pct: Decimal
    note_text: str


class PositionOut(BaseModel):
    """Single position with dual-currency valuation."""

    model_config = ConfigDict(from_attributes=True)

    instrument_id: UUID
    symbol: str
    exchange: str | None = None
    quantity: Decimal
    avg_cost: Decimal
    # Native currency (broker currency)
    currency: str
    market_value_native: Decimal
    unrealized_pl_native: Decimal
    # Base currency (user's preferred / USD by default)
    base_currency: str
    market_value_base: Decimal
    unrealized_pl_base: Decimal
    fx_rate: Decimal = Field(..., description="Native -> base conversion rate applied.")
    as_of: datetime
    fx_attribution: FxAttributionOut | None = Field(
        default=None,
        description=(
            "Cross-currency return decomposition. None when the position's "
            "native currency matches the user's base currency."
        ),
    )


class PositionsList(BaseModel):
    positions: list[PositionOut]
    base_currency: str
    as_of: datetime
    is_stale: bool = False


class PortfolioSummaryOut(BaseModel):
    """Aggregated portfolio value in the user's base currency."""

    model_config = ConfigDict(from_attributes=True)

    base_currency: str
    total_value: Decimal
    total_cost_basis: Decimal
    total_unrealized_pl: Decimal
    daily_pl: Decimal = Field(default=Decimal("0"))
    position_count: int = Field(..., ge=0)
    as_of: datetime
    is_stale: bool = False
    confidence: Decimal = Field(
        default=Decimal("1.0"),
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Data confidence: 1.0 = fresh, 0.5 = stale (>2h old).",
    )
