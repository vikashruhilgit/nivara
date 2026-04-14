"""SEC EDGAR fundamentals client.

Fetches XBRL-tagged financial data from the SEC EDGAR XBRL "companyfacts" API
for US-listed issuers and reduces it to the
:class:`backend.app.data.edgar.EdgarFundamentals` schema consumed by the
fundamental scoring engine (:mod:`backend.app.analysis.fundamental`).

Why EDGAR and not Yahoo for US fundamentals
-------------------------------------------
The Yahoo ``info`` dict is convenient but:

* it exposes only a small subset of US-GAAP concepts (no free cash flow,
  limited debt/equity history),
* it is undocumented and regularly breaks,
* it does not surface the filing date, so staleness is opaque.

EDGAR is authoritative, free, and stable. It only covers SEC-registered
issuers though, so Indian stocks (XNSE/XBOM) fall back to Yahoo via
:class:`backend.app.data.yahoo.YahooProvider.get_fundamentals`.

SEC access requirements
-----------------------
Per SEC Fair Access policy (https://www.sec.gov/os/accessing-edgar-data) every
request MUST include a descriptive ``User-Agent`` header containing contact
information. Requests without one receive a 403 with an explanatory HTML
body. We set ``InvestIQ/1.0 (contact@investiq.app)`` — callers may override
via :class:`EdgarClient` construction if the contact address changes.

SEC also asks clients to stay below 10 requests/second. The recommendation
pipeline fetches fundamentals at most once per instrument per 24h (Redis
cache TTL — see :mod:`backend.app.data.cache`), so we sit far below that
bar. A process-wide :class:`asyncio.Semaphore` caps concurrency at 8 to
keep bursts inside the limit.

XBRL taxonomy quirks
--------------------
The same concept often appears under multiple US-GAAP tags across filings
(e.g. Revenue has been tagged as ``Revenues``, ``SalesRevenueNet``,
``RevenueFromContractWithCustomerExcludingAssessedTax``). We try each tag in
a fallback list and take the first that yields usable data. Any missing
field is returned as ``None`` — the scoring engine degrades gracefully.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx
from backend.app.data.cache import FUNDAMENTALS_TTL_SECONDS, get_model, set_model
from backend.app.data.errors import (
    DataProviderError,
    RateLimitError,
    SymbolNotFoundError,
    UpstreamUnavailableError,
)
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_PROVIDER_NAME = "edgar"
_SEC_BASE = "https://data.sec.gov"
_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_DEFAULT_USER_AGENT = "InvestIQ/1.0 (contact@investiq.app)"
_HTTP_TIMEOUT = 15.0
_MAX_CONCURRENT_REQUESTS = 8

# US-GAAP XBRL tag fallback chains. First tag wins.
# See https://www.sec.gov/cgi-bin/viewer?action=view&cik=... for taxonomies.
_REVENUE_TAGS = (
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
)
_NET_INCOME_TAGS = (
    "NetIncomeLoss",
    "ProfitLoss",
)
_TOTAL_DEBT_TAGS = (
    "LongTermDebt",
    "LongTermDebtNoncurrent",
    "DebtLongtermAndShorttermCombinedAmount",
)
_EQUITY_TAGS = (
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
)
_OPERATING_CASH_FLOW_TAGS = (
    "NetCashProvidedByUsedInOperatingActivities",
    "CashFlowsFromOperatingActivities",
)
_CAPEX_TAGS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
)
_EPS_TAGS = (
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
)


class EdgarFundamentals(BaseModel):
    """Fundamentals payload returned by :class:`EdgarClient`.

    All money values are already in the filing currency (USD for EDGAR). The
    scoring engine treats ``None`` as "unavailable" — never as zero.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    cik: str
    filing_date: date | None = None
    # Current and prior annual revenues — used to compute YoY growth.
    revenue_ttm: Decimal | None = None
    revenue_prior_ttm: Decimal | None = None
    # Current and prior annual earnings — used for earnings trend.
    earnings_ttm: Decimal | None = None
    earnings_prior_ttm: Decimal | None = None
    # Derived scoring inputs.
    pe_ratio: Decimal | None = None
    debt_to_equity: Decimal | None = None
    free_cash_flow: Decimal | None = None
    eps: Decimal | None = None
    fetched_at: datetime


@dataclass(frozen=True)
class _Observation:
    end: date
    value: Decimal
    fy: int
    form: str  # "10-K" / "10-Q" / "20-F" etc.


class EdgarClient:
    """Async SEC EDGAR fundamentals client with Redis-backed 24h caching.

    Responsibilities
    ----------------
    * Resolve ticker → CIK via the SEC company-tickers endpoint (cached in
      Redis under ``edgar:cik:{ticker}`` so we only hit SEC once per process
      lifetime per ticker).
    * Fetch ``/api/xbrl/companyfacts/CIK{10-digit}.json`` and reduce it to
      :class:`EdgarFundamentals`.
    * Cache the reduced payload under the shared ``data:edgar:fundamentals:*``
      key used by :mod:`backend.app.data.cache` so the key scheme stays
      uniform across providers.

    Error handling
    --------------
    SEC-specific status codes map to the shared DataProvider exception tree:

    * 403 → :class:`DataProviderError` ("User-Agent rejected or IP blocked").
    * 404 → :class:`SymbolNotFoundError`.
    * 429 → :class:`RateLimitError` with ``retry_after_seconds`` from header.
    * 5xx / network → :class:`UpstreamUnavailableError`.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        user_agent: str = _DEFAULT_USER_AGENT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._redis = redis
        self._user_agent = user_agent
        # A single shared AsyncClient reuses the TCP connection. Callers that
        # want to inject a mock supply ``client`` directly.
        self._client = client or httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)
        self._ticker_map: dict[str, str] | None = None  # ticker (upper) -> CIK (10-digit str)
        self._ticker_map_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- Public API ----------------------------------------------------

    async def get_fundamentals(self, symbol: str) -> EdgarFundamentals:
        """Fetch fundamentals for a US ticker (e.g. ``"AAPL"``).

        Uses the shared ``data:edgar:fundamentals:{symbol}`` cache key so the
        :mod:`backend.app.data.cache` invalidation helpers cover us too.
        """
        from backend.app.data.cache import fundamentals_key

        symbol = symbol.upper().strip()
        if not symbol:
            raise DataProviderError("empty symbol", provider=_PROVIDER_NAME)

        cache_key = fundamentals_key(_PROVIDER_NAME, symbol)
        cached = await get_model(self._redis, cache_key, EdgarFundamentals)
        if cached is not None:
            logger.debug("edgar cache hit: %s", cache_key)
            return cached

        cik = await self._resolve_cik(symbol)
        facts = await self._fetch_company_facts(cik)
        fundamentals = _reduce_company_facts(symbol=symbol, cik=cik, facts=facts)
        await set_model(self._redis, cache_key, fundamentals, ttl=FUNDAMENTALS_TTL_SECONDS)
        return fundamentals

    # ---- CIK resolution ------------------------------------------------

    async def _resolve_cik(self, symbol: str) -> str:
        """Return the zero-padded 10-digit CIK for ``symbol``.

        Two-level cache: (1) process-wide in-memory map populated lazily from
        the ``company_tickers.json`` endpoint, (2) Redis-backed per-ticker
        lookup for cold starts.
        """
        redis_key = f"edgar:cik:{symbol}"
        cached_cik = await self._redis.get(redis_key)
        if cached_cik is not None:
            # redis-py returns bytes or str depending on decode_responses.
            if isinstance(cached_cik, bytes):
                cached_cik = cached_cik.decode()
            return str(cached_cik)

        async with self._ticker_map_lock:
            if self._ticker_map is None:
                self._ticker_map = await self._load_ticker_map()

        cik = self._ticker_map.get(symbol)
        if cik is None:
            raise SymbolNotFoundError(
                f"EDGAR has no CIK for ticker {symbol!r}",
                provider=_PROVIDER_NAME,
            )
        # Cache for 7 days — CIK assignments are essentially permanent.
        await self._redis.set(redis_key, cik, ex=7 * 24 * 60 * 60)
        return cik

    async def _load_ticker_map(self) -> dict[str, str]:
        """Download and parse SEC's master ticker→CIK mapping."""
        try:
            async with self._semaphore:
                resp = await self._client.get(_SEC_TICKERS_URL)
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError(
                f"could not fetch SEC ticker map: {exc}", provider=_PROVIDER_NAME
            ) from exc

        if resp.status_code != 200:
            raise UpstreamUnavailableError(
                f"SEC ticker map returned HTTP {resp.status_code}",
                provider=_PROVIDER_NAME,
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise UpstreamUnavailableError(
                f"SEC ticker map returned non-JSON payload: {exc}",
                provider=_PROVIDER_NAME,
            ) from exc

        # Payload shape: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}
        mapping: dict[str, str] = {}
        for row in payload.values():
            ticker = str(row.get("ticker", "")).upper().strip()
            cik_raw = row.get("cik_str")
            if not ticker or cik_raw is None:
                continue
            mapping[ticker] = f"{int(cik_raw):010d}"
        logger.info("loaded %d EDGAR ticker mappings", len(mapping))
        return mapping

    # ---- Company facts -------------------------------------------------

    async def _fetch_company_facts(self, cik: str) -> dict[str, Any]:
        """Fetch the full XBRL company-facts payload for ``cik``."""
        url = f"{_SEC_BASE}/api/xbrl/companyfacts/CIK{cik}.json"
        try:
            async with self._semaphore:
                resp = await self._client.get(url)
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError(
                f"EDGAR request failed for CIK {cik}: {exc}",
                provider=_PROVIDER_NAME,
            ) from exc

        if resp.status_code == 404:
            raise SymbolNotFoundError(
                f"EDGAR has no companyfacts for CIK {cik}",
                provider=_PROVIDER_NAME,
            )
        if resp.status_code == 403:
            raise DataProviderError(
                "EDGAR rejected request — check User-Agent header",
                provider=_PROVIDER_NAME,
            )
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            raise RateLimitError(
                "EDGAR rate-limited the request",
                provider=_PROVIDER_NAME,
                retry_after_seconds=float(retry_after) if retry_after else None,
            )
        if resp.status_code >= 500:
            raise UpstreamUnavailableError(
                f"EDGAR returned HTTP {resp.status_code}",
                provider=_PROVIDER_NAME,
            )
        if resp.status_code != 200:
            raise UpstreamUnavailableError(
                f"EDGAR unexpected HTTP {resp.status_code}",
                provider=_PROVIDER_NAME,
            )
        try:
            payload: dict[str, Any] = resp.json()
        except ValueError as exc:
            raise UpstreamUnavailableError(
                f"EDGAR returned non-JSON payload: {exc}",
                provider=_PROVIDER_NAME,
            ) from exc
        return payload


# ---- XBRL reducers ---------------------------------------------------------


def _extract_concept(
    facts: dict[str, Any],
    tag_chain: tuple[str, ...],
    *,
    unit_preference: tuple[str, ...] = ("USD",),
) -> list[_Observation]:
    """Extract observations for the first matching tag in ``tag_chain``.

    ``facts`` is the full SEC company-facts JSON. Only US-GAAP observations
    are considered. Observations are sorted ascending by period end date so
    callers can index ``-1`` for "latest" and ``-2`` for "prior".
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tag_chain:
        node = us_gaap.get(tag)
        if not node:
            continue
        units = node.get("units", {})
        for unit in unit_preference:
            raw = units.get(unit)
            if not raw:
                continue
            observations: list[_Observation] = []
            for row in raw:
                try:
                    end_str = row["end"]
                    value_raw = row["val"]
                    fy = int(row.get("fy") or 0)
                    form = str(row.get("form") or "")
                    end = date.fromisoformat(end_str)
                    value = Decimal(str(value_raw))
                except (KeyError, ValueError, TypeError):
                    continue
                observations.append(_Observation(end=end, value=value, fy=fy, form=form))
            if observations:
                observations.sort(key=lambda o: o.end)
                return observations
    return []


def _latest_annual(obs: list[_Observation]) -> _Observation | None:
    """Return the most recent 10-K (annual) observation, else latest of any form."""
    annual = [o for o in obs if o.form == "10-K"]
    if annual:
        return annual[-1]
    return obs[-1] if obs else None


def _prior_annual(obs: list[_Observation]) -> _Observation | None:
    """Return the prior-year 10-K observation for YoY comparison."""
    annual = [o for o in obs if o.form == "10-K"]
    if len(annual) >= 2:
        return annual[-2]
    return None


def _reduce_company_facts(
    *,
    symbol: str,
    cik: str,
    facts: dict[str, Any],
) -> EdgarFundamentals:
    """Reduce raw XBRL company-facts JSON to :class:`EdgarFundamentals`."""
    revenue_obs = _extract_concept(facts, _REVENUE_TAGS)
    net_income_obs = _extract_concept(facts, _NET_INCOME_TAGS)
    debt_obs = _extract_concept(facts, _TOTAL_DEBT_TAGS)
    equity_obs = _extract_concept(facts, _EQUITY_TAGS)
    ocf_obs = _extract_concept(facts, _OPERATING_CASH_FLOW_TAGS)
    capex_obs = _extract_concept(facts, _CAPEX_TAGS)
    eps_obs = _extract_concept(facts, _EPS_TAGS, unit_preference=("USD/shares",))

    latest_revenue = _latest_annual(revenue_obs)
    prior_revenue = _prior_annual(revenue_obs)
    latest_earnings = _latest_annual(net_income_obs)
    prior_earnings = _prior_annual(net_income_obs)
    latest_debt = _latest_annual(debt_obs)
    latest_equity = _latest_annual(equity_obs)
    latest_ocf = _latest_annual(ocf_obs)
    latest_capex = _latest_annual(capex_obs)
    latest_eps = _latest_annual(eps_obs)

    # Debt/equity — skip when equity is zero or missing to avoid DivideByZero
    # (and avoid returning spuriously large ratios for distressed issuers).
    debt_to_equity: Decimal | None = None
    if latest_debt and latest_equity and latest_equity.value != 0:
        debt_to_equity = (latest_debt.value / latest_equity.value).quantize(Decimal("0.0001"))

    # Free cash flow = OCF - |CapEx|. CapEx is reported as a positive outflow
    # in SEC filings, so we subtract its absolute value.
    free_cash_flow: Decimal | None = None
    if latest_ocf is not None:
        fcf = latest_ocf.value - (abs(latest_capex.value) if latest_capex else Decimal(0))
        free_cash_flow = fcf

    filing_date = max(
        (o.end for o in (latest_revenue, latest_earnings) if o is not None),
        default=None,
    )

    return EdgarFundamentals(
        symbol=symbol,
        cik=cik,
        filing_date=filing_date,
        revenue_ttm=latest_revenue.value if latest_revenue else None,
        revenue_prior_ttm=prior_revenue.value if prior_revenue else None,
        earnings_ttm=latest_earnings.value if latest_earnings else None,
        earnings_prior_ttm=prior_earnings.value if prior_earnings else None,
        pe_ratio=None,  # Requires price; provided by the API layer at request time.
        debt_to_equity=debt_to_equity,
        free_cash_flow=free_cash_flow,
        eps=latest_eps.value if latest_eps else None,
        fetched_at=datetime.now(UTC),
    )


__all__ = [
    "EdgarClient",
    "EdgarFundamentals",
]
