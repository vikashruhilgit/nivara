"""Position-sizing helpers (M3-19).

Computes the maximum allowed quantity for a given (portfolio_value, price,
max_position_pct) tuple and verifies that a proposed position value sits
within the configured per-position cap. All math is done in :class:`Decimal`
— the safety layer never touches floats for money.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal


class PositionSizer:
    """Pure helper: no state, no I/O — safe to construct once per request."""

    _QUANTIZE = Decimal("0.00000001")  # 8 decimal places

    @classmethod
    def max_allowed_qty(
        cls,
        portfolio_value: Decimal,
        price: Decimal,
        max_position_pct: Decimal,
    ) -> Decimal:
        """Return the largest quantity that keeps the new position within limit.

        Formula: ``floor((portfolio_value * max_pct) / price)`` quantised to
        8 decimal places. Returns ``Decimal("0")`` when ``price`` is zero
        (degenerate input) to avoid a divide-by-zero crash.
        """

        if price <= Decimal("0"):
            return Decimal("0")
        raw = (portfolio_value * max_position_pct) / price
        return raw.quantize(cls._QUANTIZE, rounding=ROUND_DOWN)

    @staticmethod
    def is_within_limit(
        proposed_value: Decimal,
        portfolio_value: Decimal,
        max_pct: Decimal,
    ) -> bool:
        """``True`` when ``proposed_value <= portfolio_value * max_pct``."""

        if portfolio_value <= Decimal("0"):
            return False
        return proposed_value <= (portfolio_value * max_pct)


__all__ = ["PositionSizer"]
