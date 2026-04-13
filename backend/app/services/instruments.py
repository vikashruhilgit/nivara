"""Instruments service — canonical (symbol, exchange) → instrument_id resolver.

Responsibilities
----------------
* Normalize exchange codes (accepts both seed-style ``NSE``/``NASDAQ`` and MIC
  codes ``XNSE``/``XNAS``/``XNYS``).
* Resolve an existing instrument by (symbol, exchange) or create one when
  ``create_if_missing=True``.
* Concurrent-safe creation using ``INSERT ... ON CONFLICT DO NOTHING`` on the
  ``UNIQUE(symbol, exchange)`` index — if two requests race, only one wins and
  the other falls back to a SELECT.
* Search (prefix match) and full-detail lookup (with broker mappings) used by
  the API layer.
"""

from __future__ import annotations

from uuid import UUID

from backend.app.models.instruments import Instrument
from backend.app.models.symbol_mappings import SymbolMapping
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# ISO 10383 MIC → seed-style exchange code used in instruments.exchange.
# We keep the canonical storage form matching the seeded data to avoid churn.
_MIC_TO_EXCHANGE: dict[str, str] = {
    "XNAS": "NASDAQ",
    "XNYS": "NYSE",
    "XNSE": "NSE",
    "XBOM": "BSE",
    "ARCX": "NYSEARCA",
    "BATS": "BATS",
}

# Default currency per canonical exchange, used only when creating a new row
# without an explicit currency.
_DEFAULT_CURRENCY_BY_EXCHANGE: dict[str, str] = {
    "NASDAQ": "USD",
    "NYSE": "USD",
    "NYSEARCA": "USD",
    "BATS": "USD",
    "NSE": "INR",
    "BSE": "INR",
}


def normalize_exchange(exchange: str) -> str:
    """Return the canonical exchange code used in ``instruments.exchange``.

    Accepts both MIC codes (``XNAS``, ``XNSE``) and seed-style names
    (``NASDAQ``, ``NSE``). Matching is case-insensitive.
    """
    code = exchange.strip().upper()
    return _MIC_TO_EXCHANGE.get(code, code)


class InstrumentsService:
    """Async service for instrument resolution and lookup."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(
        self,
        *,
        symbol: str,
        exchange: str,
        name: str | None = None,
        currency: str | None = None,
        asset_class: str = "equity",
        isin: str | None = None,
        create_if_missing: bool = True,
    ) -> Instrument:
        """Return the canonical instrument for ``(symbol, exchange)``.

        If no row exists and ``create_if_missing`` is ``True``, inserts one
        using ``INSERT ... ON CONFLICT DO NOTHING`` and falls back to a SELECT
        if another concurrent request won the race.

        Raises
        ------
        LookupError
            If the instrument is missing and ``create_if_missing`` is ``False``,
            or if creation is requested without a ``name``.
        """
        canonical_symbol = symbol.strip().upper()
        canonical_exchange = normalize_exchange(exchange)

        existing = await self._get_by_symbol_exchange(canonical_symbol, canonical_exchange)
        if existing is not None:
            return existing

        if not create_if_missing:
            raise LookupError(
                f"Instrument not found: symbol={canonical_symbol} exchange={canonical_exchange}"
            )

        if not name:
            raise LookupError(
                "Cannot create instrument without a name. Pass `name` on first encounter."
            )

        resolved_currency = currency or _DEFAULT_CURRENCY_BY_EXCHANGE.get(canonical_exchange, "USD")

        # Use ON CONFLICT DO NOTHING to handle concurrent create-if-missing
        # without raising IntegrityError on the unique(symbol, exchange) index.
        dialect_name = self._session.bind.dialect.name if self._session.bind else ""
        if dialect_name == "postgresql":
            stmt = (
                pg_insert(Instrument)
                .values(
                    symbol=canonical_symbol,
                    exchange=canonical_exchange,
                    name=name,
                    currency=resolved_currency,
                    asset_class=asset_class,
                    isin=isin,
                    is_active=True,
                )
                .on_conflict_do_nothing(index_elements=["symbol", "exchange"])
                .returning(Instrument.id)
            )
            result = await self._session.execute(stmt)
            inserted_id = result.scalar_one_or_none()
            await self._session.flush()
            if inserted_id is None:
                # Another transaction inserted the same row first — fetch it.
                existing = await self._get_by_symbol_exchange(canonical_symbol, canonical_exchange)
                if existing is None:  # pragma: no cover - defensive
                    raise RuntimeError(
                        "ON CONFLICT DO NOTHING returned no row and SELECT found none."
                    )
                return existing
            loaded = await self._session.get(Instrument, inserted_id)
            assert loaded is not None
            return loaded

        # Non-Postgres fallback (e.g., SQLite in tests): optimistic insert
        # with rollback-to-select on IntegrityError.
        instrument = Instrument(
            symbol=canonical_symbol,
            exchange=canonical_exchange,
            name=name,
            currency=resolved_currency,
            asset_class=asset_class,
            isin=isin,
            is_active=True,
        )
        self._session.add(instrument)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            existing = await self._get_by_symbol_exchange(canonical_symbol, canonical_exchange)
            if existing is None:  # pragma: no cover - defensive
                raise
            return existing
        return instrument

    async def get_by_id(self, instrument_id: UUID) -> Instrument | None:
        """Fetch instrument by primary key."""
        return await self._session.get(Instrument, instrument_id)

    async def get_detail(
        self, instrument_id: UUID
    ) -> tuple[Instrument, list[SymbolMapping]] | None:
        """Fetch instrument + its symbol mappings as a tuple, or None."""
        instrument = await self._session.get(Instrument, instrument_id)
        if instrument is None:
            return None
        mappings_stmt = select(SymbolMapping).where(SymbolMapping.instrument_id == instrument_id)
        mappings = (await self._session.execute(mappings_stmt)).scalars().all()
        return instrument, list(mappings)

    async def search(self, query: str, *, limit: int = 20) -> list[Instrument]:
        """Case-insensitive prefix match on symbol or contains-match on name."""
        q = query.strip()
        if not q:
            return []
        pattern = f"{q}%"
        name_pattern = f"%{q}%"
        stmt = (
            select(Instrument)
            .where(
                Instrument.is_active.is_(True),
                or_(
                    Instrument.symbol.ilike(pattern),
                    Instrument.name.ilike(name_pattern),
                ),
            )
            .order_by(Instrument.symbol)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _get_by_symbol_exchange(self, symbol: str, exchange: str) -> Instrument | None:
        stmt = select(Instrument).where(
            Instrument.symbol == symbol, Instrument.exchange == exchange
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
