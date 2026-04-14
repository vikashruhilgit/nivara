"""Persistence layer bridging :class:`DataProvider` bars → ``price_history``.

:func:`upsert_ohlcv` takes a list of :class:`OHLCVBar` values and writes them
to the ``price_history`` table (declaratively partitioned by month — see
:mod:`backend.app.models.price_history`). Existing ``(instrument_id, timestamp)``
rows are updated; new rows are inserted. Idempotent by design so a re-fetch
triggered by corporate actions produces consistent data.

Uses PostgreSQL's ``INSERT ... ON CONFLICT DO UPDATE`` for atomic upsert. The
backend SQLite used in some unit tests does not support this clause; storage
tests that need it should run against the Postgres test container. Pure-logic
tests (see :mod:`backend.tests.test_data_provider`) exercise the OHLCV
transform path without touching the DB.
"""

from __future__ import annotations

import logging
from uuid import UUID

from backend.app.data.base import OHLCVBar
from backend.app.models.price_history import PriceHistory
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def upsert_ohlcv(
    session: AsyncSession,
    instrument_id: UUID,
    bars: list[OHLCVBar],
) -> int:
    """Persist ``bars`` for ``instrument_id``; return the row count written.

    Callers own the transaction — this function does not commit. The caller
    should ``await session.commit()`` once all writes for a unit of work are
    queued (matches the broader backend convention in
    :mod:`backend.app.services`).
    """
    if not bars:
        return 0

    rows = [
        {
            "instrument_id": instrument_id,
            "timestamp": bar.timestamp,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
        for bar in bars
    ]

    stmt = pg_insert(PriceHistory).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["instrument_id", "timestamp"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    await session.execute(stmt)
    logger.debug("upsert_ohlcv: wrote %d bars for instrument=%s", len(rows), instrument_id)
    return len(rows)


__all__ = ["upsert_ohlcv"]
