"""Tests for :class:`backend.app.data.edgar.EdgarClient` and the XBRL reducer.

SEC's HTTP surface is mocked via ``httpx.MockTransport`` so tests run offline
and deterministically. Focus areas:

* AC #1: ``get_fundamentals`` returns reduced fundamentals on a happy path.
* Caching: second call within TTL hits Redis instead of HTTP.
* CIK resolution: unknown ticker → :class:`SymbolNotFoundError`.
* Error mapping: 403, 404, 429, 5xx → correct exception subclasses.
* Reducer: picks the first matching US-GAAP tag; handles missing equity/debt.
"""

from __future__ import annotations

from decimal import Decimal

import fakeredis.aioredis
import httpx
import pytest
from backend.app.data.edgar import (
    EdgarClient,
    EdgarFundamentals,
    _reduce_company_facts,
)
from backend.app.data.errors import (
    DataProviderError,
    RateLimitError,
    SymbolNotFoundError,
)


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


def _ticker_payload() -> dict:
    return {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft"},
    }


def _company_facts_payload() -> dict:
    """Minimal synthetic XBRL payload covering Revenue, NetIncome, Debt, Equity, OCF."""
    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "end": "2024-09-28",
                                "val": 383_000_000_000,
                                "fy": 2024,
                                "form": "10-K",
                            },
                            {
                                "end": "2023-09-30",
                                "val": 383_000_000_000,
                                "fy": 2023,
                                "form": "10-K",
                            },
                            {
                                "end": "2022-09-24",
                                "val": 365_817_000_000,
                                "fy": 2022,
                                "form": "10-K",
                            },
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "end": "2024-09-28",
                                "val": 93_700_000_000,
                                "fy": 2024,
                                "form": "10-K",
                            },
                            {
                                "end": "2023-09-30",
                                "val": 96_995_000_000,
                                "fy": 2023,
                                "form": "10-K",
                            },
                        ]
                    }
                },
                "LongTermDebt": {
                    "units": {
                        "USD": [
                            {
                                "end": "2024-09-28",
                                "val": 100_000_000_000,
                                "fy": 2024,
                                "form": "10-K",
                            },
                        ]
                    }
                },
                "StockholdersEquity": {
                    "units": {
                        "USD": [
                            {
                                "end": "2024-09-28",
                                "val": 50_000_000_000,
                                "fy": 2024,
                                "form": "10-K",
                            },
                        ]
                    }
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": [
                            {
                                "end": "2024-09-28",
                                "val": 110_000_000_000,
                                "fy": 2024,
                                "form": "10-K",
                            },
                        ]
                    }
                },
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "units": {
                        "USD": [
                            {
                                "end": "2024-09-28",
                                "val": 10_000_000_000,
                                "fy": 2024,
                                "form": "10-K",
                            },
                        ]
                    }
                },
                "EarningsPerShareBasic": {
                    "units": {
                        "USD/shares": [
                            {"end": "2024-09-28", "val": 6.13, "fy": 2024, "form": "10-K"},
                        ]
                    }
                },
            }
        },
    }


def _build_client(redis, handler) -> EdgarClient:
    """Create an EdgarClient with an httpx MockTransport."""
    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(
        transport=transport,
        headers={"User-Agent": "InvestIQ-Test/1.0"},
        base_url="https://data.sec.gov",
    )
    return EdgarClient(redis=redis, client=async_client)


# ---------------------------------------------------------------------------
# Reducer unit tests — no HTTP involved.
# ---------------------------------------------------------------------------


def test_reducer_extracts_core_metrics():
    facts = _company_facts_payload()
    out = _reduce_company_facts(symbol="AAPL", cik="0000320193", facts=facts)

    assert isinstance(out, EdgarFundamentals)
    assert out.symbol == "AAPL"
    assert out.revenue_ttm == Decimal("383000000000")
    assert out.revenue_prior_ttm == Decimal("383000000000")
    assert out.earnings_ttm == Decimal("93700000000")
    assert out.earnings_prior_ttm == Decimal("96995000000")
    # debt/equity = 100B / 50B = 2.0
    assert out.debt_to_equity == Decimal("2.0000")
    # FCF = 110B - |10B| = 100B
    assert out.free_cash_flow == Decimal("100000000000")
    assert out.eps == Decimal("6.13")


def test_reducer_handles_missing_equity_gracefully():
    facts = _company_facts_payload()
    # Drop equity entirely.
    del facts["facts"]["us-gaap"]["StockholdersEquity"]
    out = _reduce_company_facts(symbol="AAPL", cik="0000320193", facts=facts)
    assert out.debt_to_equity is None


def test_reducer_falls_back_across_tag_chain():
    facts = _company_facts_payload()
    # Replace Revenues with a fallback tag name to exercise the chain.
    facts["facts"]["us-gaap"]["SalesRevenueNet"] = facts["facts"]["us-gaap"].pop("Revenues")
    out = _reduce_company_facts(symbol="AAPL", cik="0000320193", facts=facts)
    assert out.revenue_ttm == Decimal("383000000000")


# ---------------------------------------------------------------------------
# HTTP integration — mocked transport.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_fundamentals_happy_path(redis):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "company_tickers.json" in str(request.url):
            return httpx.Response(200, json=_ticker_payload())
        if "companyfacts/CIK0000320193.json" in str(request.url):
            return httpx.Response(200, json=_company_facts_payload())
        return httpx.Response(404)

    client = _build_client(redis, handler)
    out = await client.get_fundamentals("AAPL")
    assert out.cik == "0000320193"
    assert out.revenue_ttm == Decimal("383000000000")
    # Two HTTP calls on cold path: ticker map + companyfacts.
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_get_fundamentals_uses_redis_cache(redis):
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if "company_tickers.json" in str(request.url):
            return httpx.Response(200, json=_ticker_payload())
        return httpx.Response(200, json=_company_facts_payload())

    client = _build_client(redis, handler)
    await client.get_fundamentals("AAPL")
    calls_first = call_count["n"]
    # Second call hits cache for fundamentals payload — only 0 further HTTP.
    await client.get_fundamentals("AAPL")
    assert call_count["n"] == calls_first  # no extra HTTP


@pytest.mark.asyncio
async def test_unknown_ticker_raises_symbol_not_found(redis):
    def handler(request: httpx.Request) -> httpx.Response:
        if "company_tickers.json" in str(request.url):
            return httpx.Response(200, json=_ticker_payload())
        return httpx.Response(404)

    client = _build_client(redis, handler)
    with pytest.raises(SymbolNotFoundError):
        await client.get_fundamentals("NOPE")


@pytest.mark.asyncio
async def test_403_maps_to_data_provider_error(redis):
    def handler(request: httpx.Request) -> httpx.Response:
        if "company_tickers.json" in str(request.url):
            return httpx.Response(200, json=_ticker_payload())
        return httpx.Response(403, text="forbidden")

    client = _build_client(redis, handler)
    with pytest.raises(DataProviderError):
        await client.get_fundamentals("AAPL")


@pytest.mark.asyncio
async def test_429_maps_to_rate_limit_error(redis):
    def handler(request: httpx.Request) -> httpx.Response:
        if "company_tickers.json" in str(request.url):
            return httpx.Response(200, json=_ticker_payload())
        return httpx.Response(429, headers={"Retry-After": "30"})

    client = _build_client(redis, handler)
    with pytest.raises(RateLimitError) as excinfo:
        await client.get_fundamentals("AAPL")
    assert excinfo.value.retry_after_seconds == 30.0
