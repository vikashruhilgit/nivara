"""FX impact attribution on cross-currency holdings.

Decomposes a position's return (from open to current) into three components
when the instrument's native currency differs from the user's base currency:

* ``stock_return_pct`` — pure price move in the native currency.
* ``fx_impact_pct`` — move in the native->base FX rate.
* ``base_return_pct`` — total return the user actually experiences in their
  base currency. This includes the cross-term between stock and FX moves
  (``(1 + s)(1 + f) - 1``), which is why it is NOT simply the sum of the
  other two components.

Example
-------
AAPL held by an INR-base user, bought at $150 (FX 82 INR/USD), now at $162
(FX 84.46 INR/USD):

* stock_return_pct = +8.0%
* fx_impact_pct   = +3.0%
* base_return_pct = 1.08 * 1.03 - 1 = +11.24%

Same-currency holdings return :data:`None` — there's nothing to attribute.

This module is intentionally pure: no DB, no I/O. Callers wire it up in
the API layer where position + FX-at-open data is available.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field

# Rounding helper: 1 decimal place for display percentages.
_ONE_DP = Decimal("0.1")


class FxAttribution(BaseModel):
    """Decomposition of a cross-currency position's return."""

    model_config = ConfigDict(frozen=True)

    stock_return_pct: Decimal = Field(
        ...,
        description="Native-currency price return from open to current, in %.",
    )
    fx_impact_pct: Decimal = Field(
        ...,
        description="Native->base FX rate change from open to current, in %.",
    )
    base_return_pct: Decimal = Field(
        ...,
        description=(
            "Total return in the user's base currency: "
            "(1+stock)*(1+fx) - 1. Includes the cross-term."
        ),
    )
    note_text: str = Field(
        ...,
        description="Pre-formatted human-readable attribution note.",
    )


def _fmt_pct(value: Decimal) -> str:
    """Format a Decimal percent as ``+X.Y%`` / ``-X.Y%`` (1 decimal place)."""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


def _currency_move_phrase(ccy: str, pct: Decimal) -> str:
    """Human phrase describing the base currency's move.

    A positive ``fx_impact_pct`` means 1 unit of native buys more base, i.e.
    the base currency weakened relative to the native currency. From the
    user's perspective (base-currency holder), that's a favourable move.

    For the PRD example: "AAPL +8% USD, INR weakened 3%" — the INR-base
    user's 3% FX tailwind means INR weakened vs USD. So we phrase the move
    on the *base* currency.
    """
    abs_pct = abs(pct).quantize(_ONE_DP)
    if pct > 0:
        return f"{ccy} weakened {abs_pct}%"
    if pct < 0:
        return f"{ccy} strengthened {abs_pct}%"
    return f"{ccy} flat"


def compute_fx_attribution(
    *,
    cost_basis_native: Decimal,
    current_price_native: Decimal,
    native_ccy: str,
    base_ccy: str,
    fx_at_open: Decimal,
    fx_current: Decimal,
    symbol: str | None = None,
) -> FxAttribution | None:
    """Decompose return into stock + FX + base components.

    Parameters
    ----------
    cost_basis_native:
        Purchase price per unit, in native currency.
    current_price_native:
        Current price per unit, in native currency.
    native_ccy:
        Instrument's native currency (e.g. ``"USD"``).
    base_ccy:
        User's base currency (e.g. ``"INR"``).
    fx_at_open:
        Native->base FX rate at the time the position was opened.
    fx_current:
        Native->base FX rate now.
    symbol:
        Optional ticker for the note text. Falls back to a generic label.

    Returns
    -------
    FxAttribution | None
        ``None`` when ``native_ccy == base_ccy`` (same-currency, nothing to
        attribute). Otherwise a fully-populated attribution.

    Raises
    ------
    ValueError
        If any numeric input is non-positive (can't compute ratios).
    """
    if native_ccy.upper() == base_ccy.upper():
        return None

    for name, val in (
        ("cost_basis_native", cost_basis_native),
        ("current_price_native", current_price_native),
        ("fx_at_open", fx_at_open),
        ("fx_current", fx_current),
    ):
        if val <= 0:
            raise ValueError(f"{name} must be > 0, got {val!r}")

    try:
        stock_ratio = current_price_native / cost_basis_native
        fx_ratio = fx_current / fx_at_open
    except (InvalidOperation, ZeroDivisionError) as exc:  # pragma: no cover — guarded above
        raise ValueError(f"invalid inputs for fx attribution: {exc}") from exc

    stock_return = (stock_ratio - Decimal("1")) * Decimal("100")
    fx_impact = (fx_ratio - Decimal("1")) * Decimal("100")
    base_return = (stock_ratio * fx_ratio - Decimal("1")) * Decimal("100")

    stock_return_disp = stock_return.quantize(_ONE_DP)
    fx_impact_disp = fx_impact.quantize(_ONE_DP)
    base_return_disp = base_return.quantize(_ONE_DP)

    label = symbol or "Position"
    note_text = (
        f"{label} {_fmt_pct(stock_return_disp)} {native_ccy.upper()}, "
        f"{_currency_move_phrase(base_ccy.upper(), fx_impact_disp)}, "
        f"your {base_ccy.upper()} return: {_fmt_pct(base_return_disp)}"
    )

    return FxAttribution(
        stock_return_pct=stock_return_disp,
        fx_impact_pct=fx_impact_disp,
        base_return_pct=base_return_disp,
        note_text=note_text,
    )
