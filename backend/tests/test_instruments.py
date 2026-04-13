"""Tests for the instruments service + API.

Covers:
* AC #1 — resolve existing instrument by (symbol, exchange).
* AC #2 — create-if-missing creates a new instrument + returns id.
* AC #5 — GET /api/instruments/search returns matching instruments.
* AC #6 — GET /api/instruments/{id} returns instrument with mappings.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.main import app
from backend.app.models.instruments import Instrument
from backend.app.models.symbol_mappings import SymbolMapping
from backend.app.models.users import User
from backend.app.services.instruments import InstrumentsService, normalize_exchange
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def instruments_session() -> AsyncGenerator[AsyncSession, None]:
    """In-memory SQLite with instruments + symbol_mappings tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Instrument.__table__.create(sync_conn))
        await conn.run_sync(lambda sync_conn: SymbolMapping.__table__.create(sync_conn))
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# ---------- Service tests (AC #1, #2) ----------


async def test_resolve_existing_instrument_returns_seeded_id(
    instruments_session: AsyncSession,
) -> None:
    """AC #1: AAPL on XNAS resolves to the pre-existing seeded id."""
    aapl = Instrument(
        symbol="AAPL",
        exchange="NASDAQ",
        name="Apple Inc.",
        currency="USD",
        asset_class="equity",
    )
    instruments_session.add(aapl)
    await instruments_session.flush()
    svc = InstrumentsService(instruments_session)

    result = await svc.resolve(symbol="AAPL", exchange="XNAS")

    assert result.id == aapl.id
    assert result.symbol == "AAPL"
    assert result.exchange == "NASDAQ"  # canonicalized from XNAS


async def test_resolve_missing_creates_new_instrument(
    instruments_session: AsyncSession,
) -> None:
    """AC #2: MSFT on XNAS is created and returned with a fresh id."""
    svc = InstrumentsService(instruments_session)

    created = await svc.resolve(
        symbol="MSFT",
        exchange="XNAS",
        name="Microsoft Corporation",
        create_if_missing=True,
    )

    assert created.id is not None
    assert created.symbol == "MSFT"
    assert created.exchange == "NASDAQ"
    assert created.currency == "USD"  # default for NASDAQ

    # Second resolve returns the same row (idempotent).
    again = await svc.resolve(symbol="MSFT", exchange="XNAS")
    assert again.id == created.id


async def test_resolve_missing_without_create_flag_raises(
    instruments_session: AsyncSession,
) -> None:
    svc = InstrumentsService(instruments_session)

    with pytest.raises(LookupError):
        await svc.resolve(symbol="UNKNOWN", exchange="NASDAQ", create_if_missing=False)


async def test_resolve_create_without_name_raises(
    instruments_session: AsyncSession,
) -> None:
    svc = InstrumentsService(instruments_session)

    with pytest.raises(LookupError):
        await svc.resolve(symbol="NEW", exchange="NASDAQ", create_if_missing=True)


async def test_normalize_exchange_mic_codes() -> None:
    assert normalize_exchange("XNAS") == "NASDAQ"
    assert normalize_exchange("xnse") == "NSE"
    assert normalize_exchange("XNYS") == "NYSE"
    # Already-canonical codes pass through untouched.
    assert normalize_exchange("NASDAQ") == "NASDAQ"
    assert normalize_exchange("NSE") == "NSE"


async def test_search_by_symbol_prefix(instruments_session: AsyncSession) -> None:
    for sym, name in [("AAPL", "Apple Inc."), ("AMZN", "Amazon.com"), ("MSFT", "Microsoft")]:
        instruments_session.add(
            Instrument(
                symbol=sym,
                exchange="NASDAQ",
                name=name,
                currency="USD",
                asset_class="equity",
            )
        )
    await instruments_session.flush()
    svc = InstrumentsService(instruments_session)

    results = await svc.search("A")
    symbols = {r.symbol for r in results}
    assert {"AAPL", "AMZN"}.issubset(symbols)
    assert "MSFT" not in symbols


# ---------- API tests (AC #5, #6) ----------


@pytest_asyncio.fixture
async def api_client(
    instruments_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client with db + auth dependencies overridden.

    ``get_current_user`` is stubbed to a dummy User so tests don't need to mint
    JWTs; the instruments API treats the user as opaque (only auth gate).
    """
    dummy_user = User(email="test@example.com", password_hash="x", is_active=True)

    async def _session_override() -> AsyncGenerator[AsyncSession, None]:
        yield instruments_session

    async def _user_override() -> User:
        return dummy_user

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user] = _user_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_search_endpoint_returns_matches(
    instruments_session: AsyncSession, api_client: AsyncClient
) -> None:
    """AC #5: GET /api/instruments/search?q=AAPL returns AAPL."""
    inst = Instrument(
        symbol="AAPL",
        exchange="NASDAQ",
        name="Apple Inc.",
        currency="USD",
        asset_class="equity",
    )
    instruments_session.add(inst)
    await instruments_session.flush()

    resp = await api_client.get("/api/instruments/search", params={"q": "AAPL"})
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert any(item["symbol"] == "AAPL" and item["exchange"] == "NASDAQ" for item in body)


async def test_detail_endpoint_returns_mappings(
    instruments_session: AsyncSession, api_client: AsyncClient
) -> None:
    """AC #6: GET /api/instruments/{id} returns instrument + its mappings."""
    inst = Instrument(
        symbol="RELIANCE",
        exchange="NSE",
        name="Reliance Industries Limited",
        currency="INR",
        asset_class="equity",
    )
    instruments_session.add(inst)
    await instruments_session.flush()
    instruments_session.add(
        SymbolMapping(
            instrument_id=inst.id,
            broker="zerodha",
            broker_symbol="RELIANCE",
            broker_exchange="NSE",
        )
    )
    await instruments_session.flush()

    resp = await api_client.get(f"/api/instruments/{inst.id}")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["symbol"] == "RELIANCE"
    assert body["exchange"] == "NSE"
    assert len(body["symbol_mappings"]) == 1
    assert body["symbol_mappings"][0]["broker"] == "zerodha"
    assert body["symbol_mappings"][0]["broker_symbol"] == "RELIANCE"


async def test_detail_endpoint_404(api_client: AsyncClient) -> None:
    from uuid import uuid4

    resp = await api_client.get(f"/api/instruments/{uuid4()}")
    assert resp.status_code == 404


async def test_resolve_endpoint_creates(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/instruments/resolve",
        json={
            "symbol": "MSFT",
            "exchange": "XNAS",
            "name": "Microsoft Corporation",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["symbol"] == "MSFT"
    assert body["exchange"] == "NASDAQ"


async def test_data_symbol_endpoint(
    instruments_session: AsyncSession, api_client: AsyncClient
) -> None:
    inst = Instrument(
        symbol="RELIANCE",
        exchange="NSE",
        name="Reliance Industries Limited",
        currency="INR",
        asset_class="equity",
    )
    instruments_session.add(inst)
    await instruments_session.flush()

    resp = await api_client.get(f"/api/instruments/{inst.id}/data-symbol")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"provider": "yahoo", "symbol": "RELIANCE.NS"}
