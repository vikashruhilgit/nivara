"""Foreign exchange rate service — lookup + daily refresh pipeline.

Two responsibilities live here:

1. **Lookup** (existing, used across the app): :class:`FxService` reads the
   most recent ``fx_rates`` row for a ``(base, quote)`` pair, with inverse
   fallback and ``Decimal``-safe conversion.

2. **Refresh pipeline** (new in M2-11): :class:`FxRefreshService` fetches
   USD/INR from FRED (primary) with ECB fallback, upserts into ``fx_rates``,
   and caches the latest rate in Redis under ``fx:USD_INR`` (TTL 24h).

   The refresh is designed to be driven by a 6AM-UTC scheduled task (Celery
   Beat in production; currently invoked by a thin task wrapper in
   :mod:`backend.app.tasks`). Weekend / holiday gaps are handled by the
   upstream clients (they return the most recent publication date) and by
   :class:`FxService.get_rate` which already returns the most recent row
   ≤ ``as_of``.

Cache contract
--------------
* Key: ``fx:{BASE}_{QUOTE}`` (upper-case), e.g. ``fx:USD_INR``.
* Value: JSON ``{"rate": "<decimal string>", "as_of": "<ISO-8601 UTC>",
  "source": "fred"|"ecb"}``.
* TTL: 24h (refresh runs daily at 06:00 UTC).
* Consumers SHOULD prefer the ``fx_rates`` table for historical queries; the
  cache is an optimization for the common "current rate" path.

Decimal arithmetic: all rates and conversions use ``Decimal`` to avoid float
drift on monetary aggregations.

Fallback rules (lookup)
-----------------------
* ``convert(amount, from_ccy, to_ccy)`` with ``from_ccy == to_ccy`` returns
  ``amount`` unchanged with rate ``1``.
* If the direct rate is missing, try the inverse and invert (``1 / rate``).
* If neither direction exists, raise :class:`FxRateNotFoundError`.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final

from backend.app.data.fred import (
    EcbClient,
    FredClient,
    FredEcbClient,
    FxFetchError,
    FxObservation,
)
from backend.app.models.fx_rates import FxRate
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Cache TTL for the latest FX rate — matches the 24h refresh cadence.
FX_CACHE_TTL_SECONDS: Final[int] = 24 * 60 * 60


class FxRateNotFoundError(LookupError):
    """Raised when no rate exists for a currency pair (in either direction)."""


def fx_cache_key(base: str, quote: str) -> str:
    """Return the Redis cache key for a currency pair, e.g. ``fx:USD_INR``."""
    return f"fx:{base.upper()}_{quote.upper()}"


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
        else:
            stmt = (
                select(FxRate)
                .where(FxRate.base_currency == base, FxRate.quote_currency == quote)
                .order_by(FxRate.as_of.desc())
                .limit(1)
            )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return row.rate if row is not None else None


class FxRefreshService:
    """Refresh USD/INR from FRED (primary) with ECB fallback and cache result.

    Usage::

        service = FxRefreshService(
            session=session,
            redis=redis,
            client=FredEcbClient(
                fred=FredClient(api_key=settings.fred_api_key),
                ecb=EcbClient(),
            ),
        )
        observation = await service.refresh_usd_inr()
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        redis: Redis,
        client: FredEcbClient,
    ) -> None:
        self._session = session
        self._redis = redis
        self._client = client

    async def refresh_usd_inr(self, *, as_of: date | None = None) -> FxObservation:
        """Fetch, upsert and cache the latest USD/INR rate.

        Raises :class:`FxFetchError` if BOTH FRED and ECB are unavailable.
        """
        observation = await self._client.get_latest_usd_inr(as_of=as_of)
        await self._upsert(observation)
        await self._cache(observation)
        logger.info(
            "fx.refresh usd_inr rate=%s as_of=%s source=%s",
            observation.rate,
            observation.as_of.date().isoformat(),
            observation.source,
        )
        return observation

    async def _upsert(self, obs: FxObservation) -> None:
        """Insert-or-update on the ``(base, quote, as_of)`` unique constraint."""
        # Normalize as_of to midnight UTC for daily granularity.
        as_of_day = datetime(obs.as_of.year, obs.as_of.month, obs.as_of.day, tzinfo=UTC)
        stmt = pg_insert(FxRate).values(
            base_currency=obs.base_currency,
            quote_currency=obs.quote_currency,
            rate=obs.rate,
            as_of=as_of_day,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_fx_rates_base_quote_asof",
            set_={"rate": stmt.excluded.rate},
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def _cache(self, obs: FxObservation) -> None:
        key = fx_cache_key(obs.base_currency, obs.quote_currency)
        payload = json.dumps(
            {
                "rate": str(obs.rate),
                "as_of": obs.as_of.isoformat(),
                "source": obs.source,
            }
        )
        try:
            await self._redis.set(key, payload, ex=FX_CACHE_TTL_SECONDS)
        except Exception:  # pragma: no cover — cache errors shouldn't fail refresh
            logger.warning("fx cache write failed for key=%s", key, exc_info=True)


__all__ = [
    "FX_CACHE_TTL_SECONDS",
    "FxRateNotFoundError",
    "FxRefreshService",
    "FxService",
    "fx_cache_key",
    # re-exports for convenience
    "EcbClient",
    "FredClient",
    "FredEcbClient",
    "FxFetchError",
    "FxObservation",
]
