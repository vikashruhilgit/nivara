"""Unit tests for :func:`backend.app.api.portfolio._attach_fx_attribution`.

The helper enriches cross-currency positions returned by
``GET /api/portfolio/positions`` with a pre-formatted FX attribution note.
Because the historical-price + trade-level FX pipeline isn't wired yet, the
default resolver is a no-op — these tests inject a stub resolver so we can
exercise the attribution path end-to-end at the helper boundary without
standing up the full FastAPI TestClient / DB fixture.

Covers:

* Same-currency position → ``fx_attribution`` stays ``None``.
* Cross-currency position with resolver stub → ``fx_attribution`` populated
  with a valid ``FxAttribution`` (stock / fx / base percentages consistent
  with the PRD example).
* Resolver raising → position left untouched (helper never propagates).
* Resolver returning ``None`` → position left untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from backend.app.api.portfolio import _attach_fx_attribution
from backend.app.schemas.portfolio import PositionOut, PositionsList


def _make_position(
    *,
    currency: str,
    base_currency: str,
    avg_cost: Decimal,
    fx_rate: Decimal,
    symbol: str = "AAPL",
) -> PositionOut:
    return PositionOut(
        instrument_id=uuid4(),
        symbol=symbol,
        exchange="NASDAQ",
        quantity=Decimal("10"),
        avg_cost=avg_cost,
        currency=currency,
        market_value_native=avg_cost * Decimal("10"),
        unrealized_pl_native=Decimal("0"),
        base_currency=base_currency,
        market_value_base=avg_cost * Decimal("10") * fx_rate,
        unrealized_pl_base=Decimal("0"),
        fx_rate=fx_rate,
        as_of=datetime.now(UTC),
    )


def _list(positions: list[PositionOut], base_currency: str) -> PositionsList:
    return PositionsList(
        positions=positions,
        base_currency=base_currency,
        as_of=datetime.now(UTC),
        is_stale=False,
    )


@pytest.mark.asyncio
async def test_same_currency_position_left_untouched() -> None:
    """Same-currency positions must not receive fx_attribution."""
    pos = _make_position(
        currency="USD",
        base_currency="USD",
        avg_cost=Decimal("150"),
        fx_rate=Decimal("1"),
    )
    result = await _attach_fx_attribution(_list([pos], "USD"), base_currency="USD")
    assert result.positions[0].fx_attribution is None


@pytest.mark.asyncio
async def test_cross_currency_position_gets_attribution() -> None:
    """Resolver provides (current_price, fx_at_open) → attribution populated.

    Uses the PRD example: AAPL bought at $150 (FX 82 INR/USD), now $162
    (FX 84.46 INR/USD). Expected: stock +8%, fx +3%, base +11.2%.
    """
    pos = _make_position(
        currency="USD",
        base_currency="INR",
        avg_cost=Decimal("150"),
        fx_rate=Decimal("84.46"),  # current
    )

    async def resolver(
        position: PositionOut,
    ) -> tuple[Decimal, Decimal] | None:
        return (Decimal("162"), Decimal("82"))

    result = await _attach_fx_attribution(
        _list([pos], "INR"), base_currency="INR", resolver=resolver
    )
    attribution = result.positions[0].fx_attribution
    assert attribution is not None
    # Percentages match the fx_attribution math (1dp rounding).
    assert attribution.stock_return_pct == Decimal("8.0")
    assert attribution.fx_impact_pct == Decimal("3.0")
    assert attribution.base_return_pct == Decimal("11.2")
    assert "AAPL" in attribution.note_text
    assert "INR weakened" in attribution.note_text


@pytest.mark.asyncio
async def test_resolver_exception_leaves_position_untouched() -> None:
    """A raising resolver must not poison the whole response."""
    pos = _make_position(
        currency="USD",
        base_currency="INR",
        avg_cost=Decimal("150"),
        fx_rate=Decimal("84"),
    )

    async def bad_resolver(
        position: PositionOut,
    ) -> tuple[Decimal, Decimal] | None:
        raise RuntimeError("boom")

    result = await _attach_fx_attribution(
        _list([pos], "INR"), base_currency="INR", resolver=bad_resolver
    )
    assert result.positions[0].fx_attribution is None


@pytest.mark.asyncio
async def test_resolver_none_leaves_position_untouched() -> None:
    """Resolver returning None means no historical data — skip silently."""
    pos = _make_position(
        currency="USD",
        base_currency="INR",
        avg_cost=Decimal("150"),
        fx_rate=Decimal("84"),
    )

    async def none_resolver(
        position: PositionOut,
    ) -> tuple[Decimal, Decimal] | None:
        return None

    result = await _attach_fx_attribution(
        _list([pos], "INR"), base_currency="INR", resolver=none_resolver
    )
    assert result.positions[0].fx_attribution is None
