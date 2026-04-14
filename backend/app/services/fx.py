"""Foreign exchange rate lookup service.

Reads from the ``fx_rates`` table (populated by a separate data pipeline in
later milestones; seeded USD/INR in M1). Looks up the most recent rate for a
``(base, quote)`` pair as of a given timestamp.

Decimal arithmetic: all rates and conversions use ``Decimal`` to avoid float
drift on monetary aggregations.

Fallback rules
--------------
* ``convert(amount, from_ccy, to_ccy)`` with ``from_ccy == to_ccy`` returns
  ``amount`` unchanged with rate ``1``.
* If the direct rate is missing, try the inverse and invert (``1 / rate``).
* If neither direction exists, raise :class:`FxRateNotFoundError`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from backend.app.models.fx_rates import FxRate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class FxRateNotFoundError(LookupError):
    """Raised when no rate exists for a currency pair (in either direction)."""


class FxService:
    """Async service for currency conversion using stored rates."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_rate(
        self,
        *,
        base: str,
        quote: str,
        as_of: datetime | None = None,
    ) -> Decimal:
        """Return ``1 base == <rate> quote`` as of the given time (or latest).

        Tries the direct pair first, then the inverse (and inverts it).
        """
        base_u = base.upper()
        quote_u = quote.upper()
        if base_u == quote_u:
            return Decimal("1")

        rate = await self._lookup(base=base_u, quote=quote_u, as_of=as_of)
        if rate is not None:
            return rate

        inverse = await self._lookup(base=quote_u, quote=base_u, as_of=as_of)
        if inverse is not None and inverse != 0:
            return Decimal("1") / inverse

        raise FxRateNotFoundError(f"No FX rate for {base_u}/{quote_u}")

    async def convert(
        self,
        amount: Decimal,
        *,
        from_currency: str,
        to_currency: str,
        as_of: datetime | None = None,
    ) -> tuple[Decimal, Decimal]:
        """Convert ``amount`` from ``from_currency`` to ``to_currency``.

        Returns a ``(converted_amount, rate_used)`` tuple so callers can log
        the rate alongside the result.
        """
        rate = await self.get_rate(base=from_currency, quote=to_currency, as_of=as_of)
        return (amount * rate, rate)

    async def _lookup(
        self,
        *,
        base: str,
        quote: str,
        as_of: datetime | None,
    ) -> Decimal | None:
        stmt = (
            select(FxRate)
            .where(FxRate.base_currency == base, FxRate.quote_currency == quote)
            .order_by(FxRate.as_of.desc())
            .limit(1)
        )
        if as_of is not None:
            stmt = (
                select(FxRate)
                .where(
                    FxRate.base_currency == base,
                    FxRate.quote_currency == quote,
                    FxRate.as_of <= as_of,
                )
                .order_by(FxRate.as_of.desc())
                .limit(1)
            )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return row.rate if row is not None else None
