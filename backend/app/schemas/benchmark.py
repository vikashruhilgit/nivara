"""Pydantic schemas for benchmark (index) returns.

Used by the portfolio intelligence engine to compare per-market portfolio
performance against market benchmarks (Nifty 50 for IN, S&P 500 for US) in
native currency — no FX conflation.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class BenchmarkReturn(BaseModel):
    """Period return for a benchmark index, quoted in its native currency.

    ``stale=True`` means we couldn't fetch fresh data from Yahoo and fell
    back to a ``0.0`` placeholder. Callers should surface this flag in the
    API response so the UI can annotate the value.
    """

    model_config = ConfigDict(from_attributes=True)

    symbol: str = Field(..., description="Yahoo symbol, e.g. '^NSEI' or '^GSPC'.")
    currency: str = Field(..., description="Native currency of the index (INR / USD).")
    period_days: int = Field(..., ge=1)
    period_start: datetime
    period_end: datetime
    close_start: Decimal | None = Field(
        None, description="Close on the first bar in the window (None when stale)."
    )
    close_end: Decimal | None = Field(
        None, description="Close on the last bar in the window (None when stale)."
    )
    total_return: Decimal = Field(..., description="(close_end / close_start) - 1 over the period.")
    stale: bool = Field(False, description="True when fetch failed and values are a fallback.")


__all__ = ["BenchmarkReturn"]
