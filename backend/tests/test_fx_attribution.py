"""Tests for :mod:`backend.app.intelligence.fx_attribution`.

Covers:

* PRD example — AAPL +8% USD, INR weakened 3%, INR return +11.2%
  (cross-term included: 1.08 * 1.03 - 1 = 0.1124).
* Same-currency case returns ``None``.
* Negative stock / negative FX combinations.
* ValueError on non-positive inputs.
* ``note_text`` formatting & sign rendering.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from backend.app.intelligence.fx_attribution import (
    FxAttribution,
    compute_fx_attribution,
)


def test_prd_example_aapl_inr_base() -> None:
    """AAPL +8% USD, INR weakened 3% → INR return +11.2% (cross-term)."""
    result = compute_fx_attribution(
        cost_basis_native=Decimal("150"),
        current_price_native=Decimal("162"),  # +8%
        native_ccy="USD",
        base_ccy="INR",
        fx_at_open=Decimal("82.00"),
        fx_current=Decimal("84.46"),  # +3%
        symbol="AAPL",
    )
    assert result is not None
    assert result.stock_return_pct == Decimal("8.0")
    assert result.fx_impact_pct == Decimal("3.0")
    # 1.08 * 1.03 - 1 = 0.1124 → 11.2% (1 dp)
    assert result.base_return_pct == Decimal("11.2")
    assert "AAPL +8.0% USD" in result.note_text
    assert "INR weakened 3.0%" in result.note_text
    assert "your INR return: +11.2%" in result.note_text


def test_same_currency_returns_none() -> None:
    """Native == base → nothing to attribute."""
    result = compute_fx_attribution(
        cost_basis_native=Decimal("100"),
        current_price_native=Decimal("110"),
        native_ccy="USD",
        base_ccy="USD",
        fx_at_open=Decimal("1.0"),
        fx_current=Decimal("1.0"),
        symbol="MSFT",
    )
    assert result is None


def test_same_currency_case_insensitive() -> None:
    assert (
        compute_fx_attribution(
            cost_basis_native=Decimal("100"),
            current_price_native=Decimal("110"),
            native_ccy="usd",
            base_ccy="USD",
            fx_at_open=Decimal("1.0"),
            fx_current=Decimal("1.0"),
        )
        is None
    )


def test_negative_stock_positive_fx() -> None:
    """Stock -5%, FX +2% → base = 0.95 * 1.02 - 1 = -3.1%."""
    result = compute_fx_attribution(
        cost_basis_native=Decimal("200"),
        current_price_native=Decimal("190"),  # -5%
        native_ccy="USD",
        base_ccy="INR",
        fx_at_open=Decimal("80"),
        fx_current=Decimal("81.60"),  # +2%
        symbol="FOO",
    )
    assert result is not None
    assert result.stock_return_pct == Decimal("-5.0")
    assert result.fx_impact_pct == Decimal("2.0")
    assert result.base_return_pct == Decimal("-3.1")
    assert "FOO -5.0% USD" in result.note_text
    assert "INR weakened 2.0%" in result.note_text


def test_positive_stock_negative_fx_base_strengthened() -> None:
    """Stock +10%, FX -5% → base = 1.10 * 0.95 - 1 = +4.5%. Base currency
    strengthened (INR got stronger → INR-base user loses some of the
    USD gain)."""
    result = compute_fx_attribution(
        cost_basis_native=Decimal("100"),
        current_price_native=Decimal("110"),
        native_ccy="USD",
        base_ccy="INR",
        fx_at_open=Decimal("80"),
        fx_current=Decimal("76"),  # -5%
    )
    assert result is not None
    assert result.stock_return_pct == Decimal("10.0")
    assert result.fx_impact_pct == Decimal("-5.0")
    assert result.base_return_pct == Decimal("4.5")
    assert "INR strengthened 5.0%" in result.note_text
    # Default symbol label when not provided.
    assert result.note_text.startswith("Position ")


def test_flat_fx_phrase() -> None:
    """FX unchanged → 'X flat' phrasing."""
    result = compute_fx_attribution(
        cost_basis_native=Decimal("100"),
        current_price_native=Decimal("105"),
        native_ccy="USD",
        base_ccy="INR",
        fx_at_open=Decimal("83"),
        fx_current=Decimal("83"),
    )
    assert result is not None
    assert result.fx_impact_pct == Decimal("0.0")
    assert "INR flat" in result.note_text


@pytest.mark.parametrize(
    "field,kwargs",
    [
        (
            "cost_basis_native",
            {
                "cost_basis_native": Decimal("0"),
                "current_price_native": Decimal("10"),
                "fx_at_open": Decimal("80"),
                "fx_current": Decimal("82"),
            },
        ),
        (
            "current_price_native",
            {
                "cost_basis_native": Decimal("10"),
                "current_price_native": Decimal("0"),
                "fx_at_open": Decimal("80"),
                "fx_current": Decimal("82"),
            },
        ),
        (
            "fx_at_open",
            {
                "cost_basis_native": Decimal("10"),
                "current_price_native": Decimal("11"),
                "fx_at_open": Decimal("0"),
                "fx_current": Decimal("82"),
            },
        ),
        (
            "fx_current",
            {
                "cost_basis_native": Decimal("10"),
                "current_price_native": Decimal("11"),
                "fx_at_open": Decimal("80"),
                "fx_current": Decimal("-1"),
            },
        ),
    ],
)
def test_rejects_non_positive_inputs(field: str, kwargs: dict[str, Decimal]) -> None:
    with pytest.raises(ValueError, match=field):
        compute_fx_attribution(
            native_ccy="USD",
            base_ccy="INR",
            **kwargs,  # type: ignore[arg-type]
        )


def test_return_type_is_pydantic_frozen() -> None:
    """Result is an immutable pydantic model."""
    from pydantic import ValidationError

    result = compute_fx_attribution(
        cost_basis_native=Decimal("150"),
        current_price_native=Decimal("162"),
        native_ccy="USD",
        base_ccy="INR",
        fx_at_open=Decimal("82"),
        fx_current=Decimal("84.46"),
    )
    assert isinstance(result, FxAttribution)
    with pytest.raises(ValidationError):
        result.stock_return_pct = Decimal("0")


def test_display_rounded_to_one_decimal() -> None:
    """Percent values are rounded to 1 dp for display."""
    # 101.234 / 100 = 1.01234 → +1.2% (banker's rounding from Decimal.quantize)
    result = compute_fx_attribution(
        cost_basis_native=Decimal("100"),
        current_price_native=Decimal("101.234"),
        native_ccy="USD",
        base_ccy="INR",
        fx_at_open=Decimal("80"),
        fx_current=Decimal("80"),
    )
    assert result is not None
    # Must have exactly one decimal place in display value.
    assert result.stock_return_pct.as_tuple().exponent == -1
    assert result.fx_impact_pct.as_tuple().exponent == -1
    assert result.base_return_pct.as_tuple().exponent == -1
