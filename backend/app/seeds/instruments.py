"""Idempotent seed loader for instruments + symbol_mappings.

Reads ``symbol_mappings.json`` (co-located fixture), upserts each instrument
(keyed on UNIQUE(symbol, exchange)) and its broker mapping (keyed on
UNIQUE(broker, broker_symbol, broker_exchange)). Safe to re-run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.models.instruments import Instrument
from backend.app.models.symbol_mappings import SymbolMapping
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

_FIXTURE_PATH = Path(__file__).parent / "symbol_mappings.json"


def _load_fixture() -> dict[str, Any]:
    with _FIXTURE_PATH.open(encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


async def seed_instruments(session: AsyncSession) -> dict[str, int]:
    """Upsert instruments + symbol_mappings; return counts.

    Returns
    -------
    dict[str, int]
        ``{"instruments_inserted": N, "mappings_inserted": M}`` — counts reflect
        rows actually inserted (not upserted on conflict).
    """
    fixture = _load_fixture()
    instruments_inserted = 0
    mappings_inserted = 0

    # ---- NSE (India) ----
    for row in fixture.get("nse", []):
        instrument_stmt = (
            insert(Instrument)
            .values(
                symbol=row["symbol"],
                exchange="NSE",
                name=row["name"],
                currency="INR",
                asset_class="equity",
                isin=row.get("isin"),
                is_active=True,
            )
            .on_conflict_do_nothing(index_elements=["symbol", "exchange"])
            .returning(Instrument.id)
        )
        result = await session.execute(instrument_stmt)
        inserted_id = result.scalar_one_or_none()
        if inserted_id is not None:
            instruments_inserted += 1
            instrument_id = inserted_id
        else:
            # Row already exists — fetch its id
            from sqlalchemy import select

            instrument_id = (
                await session.execute(
                    select(Instrument.id).where(
                        Instrument.symbol == row["symbol"], Instrument.exchange == "NSE"
                    )
                )
            ).scalar_one()

        mapping_stmt = (
            insert(SymbolMapping)
            .values(
                instrument_id=instrument_id,
                broker="zerodha",
                broker_symbol=row["broker_symbol"],
                broker_exchange=row.get("broker_exchange", "NSE"),
            )
            .on_conflict_do_nothing(index_elements=["broker", "broker_symbol", "broker_exchange"])
            .returning(SymbolMapping.id)
        )
        mapping_result = await session.execute(mapping_stmt)
        if mapping_result.scalar_one_or_none() is not None:
            mappings_inserted += 1

    # ---- US (NASDAQ/NYSE) ----
    for row in fixture.get("us", []):
        exchange = row["exchange"]
        instrument_stmt = (
            insert(Instrument)
            .values(
                symbol=row["symbol"],
                exchange=exchange,
                name=row["name"],
                currency="USD",
                asset_class="equity",
                isin=None,
                is_active=True,
            )
            .on_conflict_do_nothing(index_elements=["symbol", "exchange"])
            .returning(Instrument.id)
        )
        result = await session.execute(instrument_stmt)
        inserted_id = result.scalar_one_or_none()
        if inserted_id is not None:
            instruments_inserted += 1
            instrument_id = inserted_id
        else:
            from sqlalchemy import select

            instrument_id = (
                await session.execute(
                    select(Instrument.id).where(
                        Instrument.symbol == row["symbol"],
                        Instrument.exchange == exchange,
                    )
                )
            ).scalar_one()

        mapping_stmt = (
            insert(SymbolMapping)
            .values(
                instrument_id=instrument_id,
                broker="alpaca",
                broker_symbol=row["broker_symbol"],
                broker_exchange=row.get("broker_exchange", exchange),
            )
            .on_conflict_do_nothing(index_elements=["broker", "broker_symbol", "broker_exchange"])
            .returning(SymbolMapping.id)
        )
        mapping_result = await session.execute(mapping_stmt)
        if mapping_result.scalar_one_or_none() is not None:
            mappings_inserted += 1

    await session.commit()
    return {
        "instruments_inserted": instruments_inserted,
        "mappings_inserted": mappings_inserted,
    }
