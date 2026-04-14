"""Pydantic schemas for the instruments API.

Exchange values accept both seed-style codes (``NSE``, ``NASDAQ``, ``NYSE``) and
ISO 10383 MIC codes (``XNSE``, ``XNAS``, ``XNYS``). The service normalizes
them to the seed-style form before persistence.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InstrumentResolveRequest(BaseModel):
    """Payload for POST /api/instruments/resolve."""

    symbol: str = Field(..., min_length=1, max_length=32)
    exchange: str = Field(..., min_length=1, max_length=16)
    name: str | None = Field(
        default=None,
        max_length=255,
        description="Required only when the instrument must be created.",
    )
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    asset_class: str | None = Field(default=None, max_length=32)
    isin: str | None = Field(default=None, min_length=12, max_length=12)


class SymbolMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    broker: str
    broker_symbol: str
    broker_exchange: str | None


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    symbol: str
    exchange: str
    name: str
    currency: str
    asset_class: str
    isin: str | None
    is_active: bool


class InstrumentDetail(InstrumentOut):
    """Instrument with its full list of broker symbol mappings."""

    symbol_mappings: list[SymbolMappingOut] = Field(default_factory=list)


class InstrumentSearchItem(InstrumentOut):
    """Lightweight item returned by /api/instruments/search."""


class DataSymbolOut(BaseModel):
    provider: str
    symbol: str
