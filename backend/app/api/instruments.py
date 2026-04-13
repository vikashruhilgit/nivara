"""Instruments API routes.

Exposes:

* ``POST /api/instruments/resolve`` — resolve or create an instrument.
* ``GET  /api/instruments/search?q=...`` — prefix/name search.
* ``GET  /api/instruments/{id}`` — full detail including symbol mappings.
* ``GET  /api/instruments/{id}/data-symbol?provider=yahoo`` — provider symbol.

All routes require an authenticated user (bearer token).
"""

from __future__ import annotations

from uuid import UUID

from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.models.users import User
from backend.app.schemas.instrument import (
    DataSymbolOut,
    InstrumentDetail,
    InstrumentOut,
    InstrumentResolveRequest,
    InstrumentSearchItem,
    SymbolMappingOut,
)
from backend.app.services.instruments import InstrumentsService
from backend.app.services.symbol_mapping import SymbolMappingService
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


def _instruments_service(session: AsyncSession = Depends(get_session)) -> InstrumentsService:
    return InstrumentsService(session=session)


def _mapping_service(session: AsyncSession = Depends(get_session)) -> SymbolMappingService:
    return SymbolMappingService(session=session)


@router.post(
    "/resolve",
    response_model=InstrumentOut,
    status_code=status.HTTP_200_OK,
)
async def resolve_instrument(
    payload: InstrumentResolveRequest,
    svc: InstrumentsService = Depends(_instruments_service),
    _user: User = Depends(get_current_user),
) -> InstrumentOut:
    """Resolve or create an instrument by ``(symbol, exchange)``."""
    try:
        instrument = await svc.resolve(
            symbol=payload.symbol,
            exchange=payload.exchange,
            name=payload.name,
            currency=payload.currency,
            asset_class=payload.asset_class or "equity",
            isin=payload.isin,
            create_if_missing=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return InstrumentOut.model_validate(instrument)


@router.get("/search", response_model=list[InstrumentSearchItem])
async def search_instruments(
    q: str = Query(..., min_length=1, max_length=64, description="Symbol or name prefix."),
    limit: int = Query(20, ge=1, le=100),
    svc: InstrumentsService = Depends(_instruments_service),
    _user: User = Depends(get_current_user),
) -> list[InstrumentSearchItem]:
    """Search active instruments by symbol prefix or name substring."""
    results = await svc.search(q, limit=limit)
    return [InstrumentSearchItem.model_validate(r) for r in results]


@router.get("/{instrument_id}", response_model=InstrumentDetail)
async def get_instrument(
    instrument_id: UUID,
    svc: InstrumentsService = Depends(_instruments_service),
    _user: User = Depends(get_current_user),
) -> InstrumentDetail:
    """Return instrument detail including all broker symbol mappings."""
    detail = await svc.get_detail(instrument_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="instrument not found")
    instrument, mappings = detail
    return InstrumentDetail(
        id=instrument.id,
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        name=instrument.name,
        currency=instrument.currency,
        asset_class=instrument.asset_class,
        isin=instrument.isin,
        is_active=instrument.is_active,
        symbol_mappings=[SymbolMappingOut.model_validate(m) for m in mappings],
    )


@router.get("/{instrument_id}/data-symbol", response_model=DataSymbolOut)
async def get_data_symbol(
    instrument_id: UUID,
    provider: str = Query("yahoo", description="Data provider key (currently only 'yahoo')."),
    svc: InstrumentsService = Depends(_instruments_service),
    mapping_svc: SymbolMappingService = Depends(_mapping_service),
    _user: User = Depends(get_current_user),
) -> DataSymbolOut:
    """Return the provider-specific symbol string (e.g. ``RELIANCE.NS``)."""
    instrument = await svc.get_by_id(instrument_id)
    if instrument is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="instrument not found")
    try:
        symbol = await mapping_svc.data_symbol(instrument, provider=provider)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DataSymbolOut(provider=provider, symbol=symbol)
