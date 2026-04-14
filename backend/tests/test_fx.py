"""Tests for :class:`backend.app.services.fx.FxRefreshService`.

The refresh pipeline uses a Postgres-specific ``ON CONFLICT DO UPDATE`` for
its upsert, which does not translate to the in-memory SQLite test DB. To
keep these tests focused and deterministic, the DB session is mocked and
only the contract (fetch → upsert call → cache write → return observation)
is verified. End-to-end behaviour against real Postgres is exercised by
integration tests that run against the docker-compose stack.

Lookup-path tests for :class:`FxService` already live in
``test_portfolio_summary.py`` — not duplicated here.
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import httpx
import pytest
from backend.app.data.fred import (
    EcbClient,
    FredClient,
    FredEcbClient,
)
from backend.app.services.fx import (
    FX_CACHE_TTL_SECONDS,
    FxRefreshService,
    fx_cache_key,
)

pytestmark = pytest.mark.asyncio


def test_fx_cache_key_is_uppercase_pair() -> None:
    assert fx_cache_key("usd", "inr") == "fx:USD_INR"
    assert fx_cache_key("USD", "INR") == "fx:USD_INR"


async def _make_composite_fred(rate: str, as_of: str = "2026-04-10") -> FredEcbClient:
    def fred_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"observations": [{"date": as_of, "value": rate}]})

    fred_http = httpx.AsyncClient(transport=httpx.MockTransport(fred_handler))
    ecb_http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    # NB: the tests below don't close these clients — they're GC'd at test end.
    # If cleanup becomes an issue, switch to an async-context fixture.
    return FredEcbClient(
        fred=FredClient(api_key="k", client=fred_http),
        ecb=EcbClient(client=ecb_http),
    )


async def test_refresh_usd_inr_fetches_upserts_and_caches() -> None:
    # Mock session — we only care that execute() and commit() are invoked.
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        composite = await _make_composite_fred("83.25", as_of="2026-04-10")
        service = FxRefreshService(session=session, redis=redis, client=composite)

        obs = await service.refresh_usd_inr()

        # Contract: observation is returned from the composite client.
        assert obs.rate == Decimal("83.25")
        assert obs.base_currency == "USD"
        assert obs.quote_currency == "INR"
        assert obs.source == "fred"

        # Contract: session.execute was called exactly once (the upsert)
        # and committed.
        assert session.execute.await_count == 1
        assert session.commit.await_count == 1

        # Contract: cached under fx:USD_INR with the expected payload.
        cached_raw = await redis.get("fx:USD_INR")
        assert cached_raw is not None
        cached = json.loads(cached_raw)
        assert cached["rate"] == "83.25"
        assert cached["source"] == "fred"
        # TTL is positive and within the configured window.
        ttl = await redis.ttl("fx:USD_INR")
        assert 0 < ttl <= FX_CACHE_TTL_SECONDS
    finally:
        await redis.aclose()


async def test_refresh_falls_back_to_ecb_when_fred_fails() -> None:
    # FRED returns 500; ECB returns a valid SDMX-JSON payload.
    def fred_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    def ecb_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "dataSets": [{"series": {"0:0:0:0:0": {"observations": {"0": [82.10]}}}}],
                "structure": {
                    "dimensions": {
                        "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2026-04-10"}]}]
                    }
                },
            },
        )

    fred_http = httpx.AsyncClient(transport=httpx.MockTransport(fred_handler))
    ecb_http = httpx.AsyncClient(transport=httpx.MockTransport(ecb_handler))
    composite = FredEcbClient(
        fred=FredClient(api_key="k", client=fred_http),
        ecb=EcbClient(client=ecb_http),
    )

    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    try:
        service = FxRefreshService(session=session, redis=redis, client=composite)
        obs = await service.refresh_usd_inr()
        assert obs.source == "ecb"
        assert obs.rate == Decimal("82.1")
    finally:
        await redis.aclose()
