"""Idempotent seed for Zerodha → canonical symbol mappings (Nifty 50).

This module is a thin, broker-scoped wrapper around
:func:`backend.app.seeds.instruments.seed_instruments`. The JSON fixture at
``backend/app/seeds/symbol_mappings.json`` is the canonical source of truth
for both instruments and broker mappings; duplicating that list here would
drift. Instead we expose:

* :func:`upsert_all` — callable from tests / scripts; returns insert counts.
* A ``__main__`` entry point so the seed can be run as
  ``python -m backend.app.brokers.seed_indian_symbols``.

Idempotency is provided by the underlying loader via Postgres
``ON CONFLICT DO NOTHING`` on ``UNIQUE(symbol, exchange)`` and
``UNIQUE(broker, broker_symbol, broker_exchange)``. Re-running the seed
leaves row counts unchanged (verified by the adjacent unit test).

AC #7 (M4-22 S4): after seeding, a Zerodha ``broker_symbol="RELIANCE"`` on
``broker_exchange="NSE"`` resolves to the canonical instrument
``(symbol="RELIANCE", exchange="NSE")`` via
:class:`backend.app.services.symbol_mapping.SymbolMappingService`. The
``XNSE`` MIC-form is produced by
:func:`backend.app.brokers.zerodha.exchange_to_mic` at read-time.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from backend.app.seeds.instruments import seed_instruments

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def upsert_all(session: AsyncSession) -> dict[str, int]:
    """Upsert all NSE/BSE instruments + Zerodha mappings; return counts.

    Safe to re-run. Returns ``{"instruments_inserted": N, "mappings_inserted": M}``
    reflecting rows *newly* inserted on this call (zero on a fully-seeded DB).
    """
    return await seed_instruments(session)


async def _main() -> None:
    from backend.app.db import _session_factory

    factory = _session_factory()
    async with factory() as session:
        counts = await upsert_all(session)
    logger.info("seed_indian_symbols complete: %s", counts)
    # Also print for CLI ergonomics when run as __main__.
    print(f"seed_indian_symbols complete: {counts}")


if __name__ == "__main__":  # pragma: no cover - CLI entry
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
