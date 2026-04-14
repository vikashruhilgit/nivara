"""Tests for :mod:`backend.app.data.fred` — FRED/ECB clients + composite.

Network is fully mocked via ``httpx.MockTransport`` so tests are deterministic
and offline. Covers:

* FRED happy-path → returns latest non-missing observation (skips "." rows).
* FRED HTTP error → :class:`FxFetchError`.
* FRED missing API key → :class:`FredApiKeyMissingError`.
* ECB happy-path (SDMX-JSON parse, highest-index observation).
* ECB parse error → :class:`FxFetchError`.
* :class:`FredEcbClient` falls back to ECB when FRED raises, logs warning.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from backend.app.data.fred import (
    EcbClient,
    FredApiKeyMissingError,
    FredClient,
    FredEcbClient,
    FxFetchError,
)

pytestmark = pytest.mark.asyncio


def _fred_response(observations: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"observations": observations})


def _ecb_response(*, time_values: list[str], obs_values: list[float | None]) -> httpx.Response:
    # SDMX-JSON skeleton the EcbClient parses.
    payload = {
        "dataSets": [
            {
                "series": {
                    "0:0:0:0:0": {
                        "observations": {
                            str(i): ([v] if v is not None else []) for i, v in enumerate(obs_values)
                        }
                    }
                }
            }
        ],
        "structure": {
            "dimensions": {
                "observation": [{"id": "TIME_PERIOD", "values": [{"id": t} for t in time_values]}]
            }
        },
    }
    return httpx.Response(200, json=payload)


# ----------------------------------------------------------------- FRED tests


async def test_fred_returns_latest_non_missing_observation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _fred_response(
            [
                {"date": "2026-04-10", "value": "."},  # holiday/missing
                {"date": "2026-04-09", "value": "83.25"},
                {"date": "2026-04-08", "value": "83.20"},
            ]
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = FredClient(api_key="test-key", client=http)
        obs = await client.get_latest_usd_inr()

    assert obs.base_currency == "USD"
    assert obs.quote_currency == "INR"
    assert obs.rate == Decimal("83.25")
    assert obs.as_of.date().isoformat() == "2026-04-09"
    assert obs.source == "fred"


async def test_fred_raises_when_api_key_missing() -> None:
    client = FredClient(api_key=None)
    with pytest.raises(FredApiKeyMissingError):
        await client.get_latest_usd_inr()


async def test_fred_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = FredClient(api_key="k", client=http)
        with pytest.raises(FxFetchError):
            await client.get_latest_usd_inr()


async def test_fred_raises_on_empty_observations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _fred_response([{"date": "2026-04-10", "value": "."}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = FredClient(api_key="k", client=http)
        with pytest.raises(FxFetchError):
            await client.get_latest_usd_inr()


# ------------------------------------------------------------------ ECB tests


async def test_ecb_parses_sdmx_latest_observation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ecb_response(
            time_values=["2026-04-08", "2026-04-09", "2026-04-10"],
            obs_values=[83.10, 83.20, None],  # most recent missing
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = EcbClient(client=http)
        obs = await client.get_latest_usd_inr()

    assert obs.rate == Decimal("83.2")
    assert obs.as_of.date().isoformat() == "2026-04-09"
    assert obs.source == "ecb"


async def test_ecb_raises_on_malformed_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"dataSets": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = EcbClient(client=http)
        with pytest.raises(FxFetchError):
            await client.get_latest_usd_inr()


# --------------------------------------------------------- composite fallback


async def test_composite_falls_back_to_ecb_when_fred_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fred_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="fred down")

    def ecb_handler(request: httpx.Request) -> httpx.Response:
        return _ecb_response(
            time_values=["2026-04-10"],
            obs_values=[82.99],
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(fred_handler)) as fred_http,
        httpx.AsyncClient(transport=httpx.MockTransport(ecb_handler)) as ecb_http,
    ):
        composite = FredEcbClient(
            fred=FredClient(api_key="k", client=fred_http),
            ecb=EcbClient(client=ecb_http),
        )
        with caplog.at_level("WARNING", logger="backend.app.data.fred"):
            obs = await composite.get_latest_usd_inr()

    assert obs.source == "ecb"
    assert obs.rate == Decimal("82.99")
    assert any("falling back to ECB" in r.message for r in caplog.records)


async def test_composite_prefers_fred_when_available() -> None:
    def fred_handler(request: httpx.Request) -> httpx.Response:
        return _fred_response([{"date": "2026-04-10", "value": "83.50"}])

    # ECB shouldn't be called; give it a handler that would fail if it were.
    def ecb_handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("ECB should not be called when FRED succeeds")

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(fred_handler)) as fred_http,
        httpx.AsyncClient(transport=httpx.MockTransport(ecb_handler)) as ecb_http,
    ):
        composite = FredEcbClient(
            fred=FredClient(api_key="k", client=fred_http),
            ecb=EcbClient(client=ecb_http),
        )
        obs = await composite.get_latest_usd_inr()

    assert obs.source == "fred"
    assert obs.rate == Decimal("83.50")
