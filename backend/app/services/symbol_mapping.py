"""Symbol mapping service — broker-native ↔ canonical instrument translation.

Two primary jobs:

1. ``normalize_symbol(broker, broker_symbol, broker_exchange=None)`` — Given a
   broker-reported symbol (e.g. Zerodha "RELIANCE" on NSE), return the canonical
   ``Instrument`` the broker symbol maps to, creating the mapping on first
   encounter when the target instrument already exists.

2. ``data_symbol(instrument, provider)`` — Given a canonical instrument, return
   the symbol string used by an external data provider (e.g. Yahoo Finance
   appends ``.NS`` for NSE, ``.BO`` for BSE; US tickers are unchanged).

Design notes
------------
* Lookups are cheap (indexed on ``(broker, broker_symbol, broker_exchange)``).
* Concurrent-safe upserts use ``ON CONFLICT DO NOTHING`` on Postgres; SQLite
  tests fall back to optimistic insert with IntegrityError rollback.
* We never auto-create a canonical instrument from a broker symbol here —
  callers must resolve the instrument separately (keeps responsibility clear).
"""

from __future__ import annotations

from uuid import UUID

from backend.app.models.instruments import Instrument
from backend.app.models.symbol_mappings import SymbolMapping
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Yahoo Finance suffix conventions (subset covering the MVP markets).
# Key is the canonical ``instruments.exchange`` value. Absent key = no suffix.
_YAHOO_SUFFIX: dict[str, str] = {
    "NSE": ".NS",
    "BSE": ".BO",
    # US exchanges have no suffix on Yahoo (AAPL, MSFT, etc.).
    "NASDAQ": "",
    "NYSE": "",
    "NYSEARCA": "",
    "BATS": "",
}


class SymbolNotMappedError(LookupError):
    """Raised when a broker symbol has no mapping and no existing instrument."""


class SymbolMappingService:
    """Async service for broker ↔ canonical symbol translation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def normalize_symbol(
        self,
        *,
        broker: str,
        broker_symbol: str,
        broker_exchange: str | None = None,
    ) -> Instrument:
        """Return the canonical ``Instrument`` for a broker-native symbol.

        Lookup order:

        1. ``symbol_mappings`` row matching ``(broker, broker_symbol, broker_exchange)``.
        2. Fallback: assume ``broker_symbol`` equals the canonical symbol and
           search ``instruments`` for a matching row whose exchange is
           compatible with ``broker_exchange`` (used as a best-effort hint).
           When found, a mapping row is created so future lookups are O(1).

        Raises
        ------
        SymbolNotMappedError
            No mapping exists and no plausible instrument can be inferred.
        """
        bs = broker_symbol.strip()
        be = broker_exchange.strip().upper() if broker_exchange else None

        mapping_stmt = select(SymbolMapping).where(
            SymbolMapping.broker == broker,
            SymbolMapping.broker_symbol == bs,
            SymbolMapping.broker_exchange == be,
        )
        mapping = (await self._session.execute(mapping_stmt)).scalar_one_or_none()
        if mapping is not None:
            inst = await self._session.get(Instrument, mapping.instrument_id)
            if inst is not None:
                return inst
            # Mapping row orphaned — fall through to inference.

        # Fallback inference: broker_symbol == canonical symbol.
        inferred_exchange = _broker_exchange_to_canonical(be) if be else None
        candidate_stmt = select(Instrument).where(Instrument.symbol == bs.upper())
        if inferred_exchange is not None:
            candidate_stmt = candidate_stmt.where(Instrument.exchange == inferred_exchange)
        candidate = (await self._session.execute(candidate_stmt)).scalar_one_or_none()

        if candidate is None:
            raise SymbolNotMappedError(
                f"No mapping or inferred instrument for broker={broker} symbol={bs} exchange={be}"
            )

        # Persist the inferred mapping so we don't repeat the fallback.
        await self._create_mapping(
            instrument_id=candidate.id,
            broker=broker,
            broker_symbol=bs,
            broker_exchange=be,
        )
        return candidate

    async def data_symbol(self, instrument: Instrument, provider: str = "yahoo") -> str:
        """Return the provider-specific symbol string for a canonical instrument.

        Currently supports ``provider="yahoo"``. Example:

        * ``(RELIANCE, NSE)`` → ``RELIANCE.NS``
        * ``(AAPL, NASDAQ)`` → ``AAPL``
        """
        provider_key = provider.strip().lower()
        if provider_key != "yahoo":
            raise ValueError(f"Unsupported data provider: {provider!r}")
        suffix = _YAHOO_SUFFIX.get(instrument.exchange, "")
        return f"{instrument.symbol}{suffix}"

    async def list_for_instrument(self, instrument_id: UUID) -> list[SymbolMapping]:
        stmt = select(SymbolMapping).where(SymbolMapping.instrument_id == instrument_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def _create_mapping(
        self,
        *,
        instrument_id: UUID,
        broker: str,
        broker_symbol: str,
        broker_exchange: str | None,
    ) -> None:
        dialect = self._session.bind.dialect.name if self._session.bind else ""
        if dialect == "postgresql":
            stmt = (
                pg_insert(SymbolMapping)
                .values(
                    instrument_id=instrument_id,
                    broker=broker,
                    broker_symbol=broker_symbol,
                    broker_exchange=broker_exchange,
                )
                .on_conflict_do_nothing(
                    index_elements=["broker", "broker_symbol", "broker_exchange"]
                )
            )
            await self._session.execute(stmt)
            await self._session.flush()
            return

        mapping = SymbolMapping(
            instrument_id=instrument_id,
            broker=broker,
            broker_symbol=broker_symbol,
            broker_exchange=broker_exchange,
        )
        self._session.add(mapping)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()


def _broker_exchange_to_canonical(broker_exchange: str) -> str:
    """Map broker-reported exchange codes to our canonical exchange strings.

    Brokers use varied conventions (Zerodha: "NSE"/"BSE"; Alpaca: "NASDAQ"/"NYSE"
    or MIC "XNAS"/"XNYS"). Accept both.
    """
    code = broker_exchange.upper()
    return {
        "XNSE": "NSE",
        "XBOM": "BSE",
        "XNAS": "NASDAQ",
        "XNYS": "NYSE",
    }.get(code, code)
