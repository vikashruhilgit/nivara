"""FRED (St. Louis Fed) FX client + ECB fallback.

Fetches daily USD/INR foreign-exchange rates for the FX pipeline. Two
providers are wrapped in a single :class:`FredEcbClient` so :mod:`services.fx`
can treat them as a primary + fallback pair:

* **FRED** — series ``DEXINUS`` (Indian rupees to one US dollar, business
  days, Board of Governors). Requires ``FRED_API_KEY`` in settings.
* **ECB SDMX** — ``EXR.D.INR.USD.SP00.A`` (Indian rupee per US dollar,
  reference rate). No auth required; returns XML (SDMX-ML).

Weekend / holiday handling
--------------------------
Both feeds only publish on trading days. Callers **forward-fill** by using the
most recent available rate (i.e., :meth:`get_latest_usd_inr` returns the
rate dated ``as_of`` or earlier, never raising on a non-trading day as long
as at least one prior observation exists).

Error handling
--------------
All upstream failures raise :class:`FxFetchError` so the FX service can
decide whether to fall back. Missing API key → ``FredApiKeyMissingError``
(a subclass of :class:`FxFetchError`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# FRED series ID for USD → INR (INR per 1 USD, business days).
FRED_SERIES_USD_INR = "DEXINUS"
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# ECB SDMX reference rate INR/USD (INR per 1 USD).
ECB_BASE_URL = "https://sdw-wsrest.ecb.europa.eu/service/data/EXR/D.INR.USD.SP00.A"

# Reasonable default: HTTP timeout for FX fetches.
DEFAULT_TIMEOUT_SECONDS = 10.0


class FxFetchError(Exception):
    """Base error for any upstream FX fetch failure (network / parse / empty)."""


class FredApiKeyMissingError(FxFetchError):
    """FRED_API_KEY is not configured but FRED was requested."""


@dataclass(frozen=True, slots=True)
class FxObservation:
    """A single daily FX observation: ``1 base == rate quote`` on ``as_of``."""

    base_currency: str
    quote_currency: str
    rate: Decimal
    as_of: datetime
    source: str  # "fred" | "ecb"


class FredClient:
    """Async FRED observations client.

    Light wrapper around the FRED JSON API. One public method per purpose —
    :meth:`get_latest_usd_inr` — so the FX service doesn't need to know about
    series IDs or pagination.
    """

    def __init__(
        self,
        *,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._timeout = timeout

    async def get_latest_usd_inr(self, *, as_of: date | None = None) -> FxObservation:
        """Return the latest USD/INR observation from FRED on or before ``as_of``.

        Raises :class:`FredApiKeyMissingError` if no key is configured, and
        :class:`FxFetchError` on HTTP / parse / empty-response failures.
        """
        if not self._api_key:
            raise FredApiKeyMissingError("FRED_API_KEY is not configured")

        params: dict[str, str] = {
            "series_id": FRED_SERIES_USD_INR,
            "api_key": self._api_key,
            "file_type": "json",
            # Pull the tail of the series; FRED returns observations ascending.
            "sort_order": "desc",
            "limit": "10",
        }
        if as_of is not None:
            params["observation_end"] = as_of.isoformat()

        try:
            payload = await self._request_json(FRED_BASE_URL, params=params)
        except httpx.HTTPError as exc:
            raise FxFetchError(f"FRED HTTP error: {exc}") from exc

        observations = payload.get("observations") or []
        for obs in observations:
            value = obs.get("value")
            obs_date = obs.get("date")
            if value in (None, "", "."):
                # FRED uses "." to mark missing data (non-trading days).
                continue
            try:
                rate = Decimal(str(value))
            except (ValueError, ArithmeticError):
                continue
            try:
                d = date.fromisoformat(obs_date)
            except (TypeError, ValueError):
                continue
            return FxObservation(
                base_currency="USD",
                quote_currency="INR",
                rate=rate,
                as_of=datetime(d.year, d.month, d.day, tzinfo=UTC),
                source="fred",
            )

        raise FxFetchError("FRED returned no usable USD/INR observations")

    async def _request_json(self, url: str, *, params: dict[str, str]) -> dict[str, Any]:
        if self._client is not None:
            resp = await self._client.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return data
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data


class EcbClient:
    """Async ECB SDMX client for USD/INR reference rate (fallback).

    The ECB publishes EUR-based reference rates; to get USD→INR we use the
    cross-rate pre-published by ECB under the ``EXR.D.INR.USD.SP00.A`` key
    (INR per USD, daily).

    The response is SDMX-ML (XML). We parse using stdlib ``xml.etree`` to
    avoid adding a new dependency — the schema is narrow enough.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client
        self._timeout = timeout

    async def get_latest_usd_inr(self, *, as_of: date | None = None) -> FxObservation:
        """Return latest USD/INR from the ECB SDMX feed on or before ``as_of``.

        Raises :class:`FxFetchError` on HTTP / parse failures.
        """
        params: dict[str, str] = {"format": "jsondata"}
        if as_of is not None:
            params["endPeriod"] = as_of.isoformat()

        try:
            payload = await self._request_json(ECB_BASE_URL, params=params)
        except httpx.HTTPError as exc:
            raise FxFetchError(f"ECB HTTP error: {exc}") from exc

        # SDMX-JSON shape: dataSets[0].series["0:0:0:0:0"].observations is a
        # dict of {obs_index: [value, ...]}; structure.dimensions.observation
        # carries the TIME_PERIOD values in the same order as obs_index.
        try:
            data_sets = payload.get("dataSets") or []
            if not data_sets:
                raise FxFetchError("ECB returned no dataSets")
            series_map = data_sets[0].get("series") or {}
            if not series_map:
                raise FxFetchError("ECB returned no series")
            # Single-series request; take the first.
            series = next(iter(series_map.values()))
            observations = series.get("observations") or {}
            if not observations:
                raise FxFetchError("ECB returned no observations")

            structure = payload.get("structure") or {}
            dims = (structure.get("dimensions") or {}).get("observation") or []
            time_dim = next((d for d in dims if d.get("id") == "TIME_PERIOD"), None)
            if time_dim is None:
                raise FxFetchError("ECB response missing TIME_PERIOD dimension")
            time_values = [v.get("id") for v in (time_dim.get("values") or [])]

            # Find the highest-index observation with a valid value (most recent).
            indices = sorted((int(k) for k in observations), reverse=True)
            for idx in indices:
                raw_value = observations[str(idx)]
                if not raw_value:
                    continue
                value = raw_value[0]
                if value is None:
                    continue
                try:
                    rate = Decimal(str(value))
                except (ValueError, ArithmeticError):
                    continue
                if idx >= len(time_values):
                    continue
                d = date.fromisoformat(time_values[idx])
                return FxObservation(
                    base_currency="USD",
                    quote_currency="INR",
                    rate=rate,
                    as_of=datetime(d.year, d.month, d.day, tzinfo=UTC),
                    source="ecb",
                )
        except FxFetchError:
            raise
        except (KeyError, ValueError, TypeError, StopIteration) as exc:
            raise FxFetchError(f"ECB parse error: {exc}") from exc

        raise FxFetchError("ECB returned no usable USD/INR observations")

    async def _request_json(self, url: str, *, params: dict[str, str]) -> dict[str, Any]:
        headers = {"Accept": "application/vnd.sdmx.data+json;version=1.0.0-wd"}
        if self._client is not None:
            resp = await self._client.get(
                url, params=params, headers=headers, timeout=self._timeout
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return data
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data


class FredEcbClient:
    """Composite client: FRED primary, ECB fallback.

    Logs a warning (but does not raise) when falling back. Raises
    :class:`FxFetchError` only if *both* providers fail.
    """

    def __init__(
        self,
        *,
        fred: FredClient,
        ecb: EcbClient,
    ) -> None:
        self._fred = fred
        self._ecb = ecb

    async def get_latest_usd_inr(self, *, as_of: date | None = None) -> FxObservation:
        try:
            return await self._fred.get_latest_usd_inr(as_of=as_of)
        except FxFetchError as exc:
            logger.warning("FRED USD/INR fetch failed, falling back to ECB: %s", exc)
        return await self._ecb.get_latest_usd_inr(as_of=as_of)


__all__ = [
    "EcbClient",
    "FRED_BASE_URL",
    "FRED_SERIES_USD_INR",
    "FxFetchError",
    "FxObservation",
    "FredApiKeyMissingError",
    "FredClient",
    "FredEcbClient",
]
