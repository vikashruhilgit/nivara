"""Portfolio Intelligence engine (Mode D).

Composes:

* **Sector allocation** per market (US, IN) as a fraction of that market's
  base-currency value.
* **Diversification** — Herfindahl-Hirschman index (HHI) over sectors
  (fractions that sum to 1, squared and summed) and geography split.
* **Per-market alpha** — each market's portfolio return in its native
  currency vs its benchmark's native return. NO FX conversion is applied
  to the alpha figures themselves (AC #3, #4: "in INR" / "in USD").
* **Blended benchmark** — the user-facing aggregate: each market's benchmark
  return converted into the user's ``base_currency`` via the FX % change
  over the lookback window, then weighted by that market's share of total
  base-currency market value.
* **Rebalancing suggestions** — display-only nudges when any sector's share
  of total base-currency value exceeds 40 %. Each entry carries the
  "not investment advice" disclaimer.

Sector data
-----------
The :class:`~backend.app.models.instruments.Instrument` model currently has
**no** ``sector`` column — a follow-up milestone will add one along with a
fundamentals-backed classifier. Until then, every instrument is treated as
``"Unknown"``. The code uses ``getattr(instrument, "sector", None) or
"Unknown"`` so adding the column later is a one-line ORM change and
everything downstream (allocation, HHI, suggestions) just starts populating
with real values automatically.

Empty portfolios
----------------
The engine is tolerant: with zero positions it returns a fully-zeroed
response (no exception, no division by zero). The API layer surfaces that
directly so callers can render an onboarding state.

Portfolio return placeholder
----------------------------
Until the per-position price pipeline lands, ``_portfolio_return_base``
and per-market portfolio returns are hard-coded to ``0.0``. The response
carries two explicit staleness flags so clients can suppress misleading
alpha figures:

* :attr:`PortfolioIntelligenceResponse.portfolio_return_stale` — always
  ``True`` today (placeholder); also ``True`` for empty portfolios.
* :attr:`PerMarketAlpha.portfolio_return_stale` — always ``True`` today.

Callers MUST hide ``portfolio_alpha`` / ``PerMarketAlpha.alpha`` when the
corresponding ``*_stale`` flag is set; otherwise the displayed alpha is
effectively ``-benchmark_return`` and misleading.

Follow-ups (out of scope for this heal iteration)
-------------------------------------------------
* SQLite testcontainer for engine tests (currently in-memory with hand-rolled
  table creation).
* Rename ``avg_cost`` → ``cost_basis`` across the position / engine code path
  to match accounting terminology.

Exchange classification
-----------------------
Only an explicit US allow-list (NASDAQ, NYSE, AMEX, ARCA, BATS) maps to
``"US"``. NSE/BSE map to ``"IN"``. Anything else (e.g. LSE, TSX) is bucketed
as ``"OTHER"`` — it counts toward sector allocation and the geography split
(``other_pct``) but is **excluded** from ``per_market_alpha`` and the
blended benchmark (no trusted benchmark mapping yet). The raw exchange
codes that fell into OTHER are surfaced on the response as
``unclassified_markets`` for observability.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.instruments import Instrument
from backend.app.models.positions import Position
from backend.app.schemas.benchmark import BenchmarkReturn
from backend.app.schemas.portfolio_intelligence import (
    DiversificationOut,
    PerMarketAlpha,
    PortfolioIntelligenceResponse,
    RebalancingSuggestion,
    SectorAllocationEntry,
)
from backend.app.services.benchmark import NIFTY_SYMBOL, SP500_SYMBOL, BenchmarkService
from backend.app.services.fx import FxRateNotFoundError, FxService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Sector share threshold (fraction of total base-currency value) above which
#: the engine emits a rebalancing suggestion.
SECTOR_CONCENTRATION_THRESHOLD: float = 0.40

#: Disclaimer appended to every rebalancing suggestion. Users must never
#: mistake these nudges for personalised investment advice (Risk #4).
DISCLAIMER_TEXT: str = "For informational purposes only. Not investment advice."

#: Exchange → market code. NSE / BSE → India. An explicit US allow-list maps
#: to US. Everything else → OTHER (excluded from per-market alpha + blended
#: benchmark; still counts in sector allocation and geography split).
_IN_EXCHANGES: frozenset[str] = frozenset({"NSE", "BSE"})
_US_EXCHANGES: frozenset[str] = frozenset({"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"})

#: Markets for which we have a trusted benchmark + currency mapping.
_BENCHMARKED_MARKETS: frozenset[str] = frozenset({"IN", "US"})


def _market_for_exchange(exchange: str | None) -> str:
    """Classify a position's exchange into a coarse market bucket.

    Returns one of ``"IN"``, ``"US"``, or ``"OTHER"``. OTHER positions are
    included in sector allocation + geography but excluded from per-market
    alpha and the blended benchmark (no trusted benchmark mapping).
    """
    if not exchange:
        return "OTHER"
    code = exchange.upper()
    if code in _IN_EXCHANGES:
        return "IN"
    if code in _US_EXCHANGES:
        return "US"
    return "OTHER"


def _sector_for_instrument(instrument: Instrument) -> str:
    """Return the sector for an instrument, defaulting to 'Unknown'.

    ``Instrument`` does not currently have a ``sector`` column; this
    ``getattr`` pattern lets us add one later without touching this engine.
    """
    return getattr(instrument, "sector", None) or "Unknown"


class _EnrichedPosition:
    """Internal row used by the engine — position value per market + sector."""

    __slots__ = (
        "instrument_id",
        "symbol",
        "exchange",
        "market",
        "sector",
        "native_currency",
        "market_value_native",
        "market_value_base",
    )

    def __init__(
        self,
        *,
        instrument_id: UUID,
        symbol: str,
        exchange: str | None,
        market: str,
        sector: str,
        native_currency: str,
        market_value_native: Decimal,
        market_value_base: Decimal,
    ) -> None:
        self.instrument_id = instrument_id
        self.symbol = symbol
        self.exchange = exchange
        self.market = market
        self.sector = sector
        self.native_currency = native_currency
        self.market_value_native = market_value_native
        self.market_value_base = market_value_base


class PortfolioIntelligenceService:
    """Compose diversification + alpha + rebalancing suggestions for a user."""

    #: Set once per service instance after the first placeholder-return log,
    #: so we don't spam WARN lines for every call / every market.
    _placeholder_warning_emitted: bool = False

    def __init__(
        self,
        *,
        session: AsyncSession,
        fx: FxService,
        benchmark_service: BenchmarkService,
    ) -> None:
        self._session = session
        self._fx = fx
        self._benchmark = benchmark_service
        self._placeholder_warning_emitted = False

    async def compute(
        self,
        *,
        user_id: UUID,
        base_currency: str = "USD",
        period_days: int = 30,
    ) -> PortfolioIntelligenceResponse:
        """Return the full portfolio intelligence response for ``user_id``."""
        base_ccy = base_currency.upper()
        positions = await self._load_positions(user_id=user_id, base_currency=base_ccy)

        # Empty portfolio: return all-zero response (no division by zero).
        # portfolio_return_stale stays True — conservatively, no return was
        # computed and the UI must not render a 0% delta against the benchmark.
        if not positions:
            return PortfolioIntelligenceResponse(
                base_currency=base_ccy,
                sector_allocation={},
                diversification=DiversificationOut(hhi=0.0, geography={}),
                per_market_alpha=[],
                blended_benchmark_return=0.0,
                portfolio_return=0.0,
                portfolio_alpha=0.0,
                portfolio_return_stale=True,
                unclassified_markets=[],
                rebalancing_suggestions=[],
            )

        # Collect unclassified exchange codes (OTHER bucket) for observability.
        unclassified_markets = sorted(
            {(p.exchange or "").upper() for p in positions if p.market == "OTHER" and p.exchange}
        )

        total_base = sum((p.market_value_base for p in positions), Decimal("0"))

        sector_allocation = self._sector_allocation(positions)
        diversification = self._diversification(positions, total_base=total_base)

        # Fetch both benchmarks up-front. BenchmarkService handles its own
        # fallback → stale on failure; we don't let a single fetch tank the
        # whole endpoint.
        nifty = await self._benchmark.get_return(symbol=NIFTY_SYMBOL, period_days=period_days)
        sp500 = await self._benchmark.get_return(symbol=SP500_SYMBOL, period_days=period_days)

        per_market_alpha = self._per_market_alpha(positions, nifty=nifty, sp500=sp500)
        portfolio_return = self._portfolio_return_base(
            positions, per_market_alpha=per_market_alpha, base_currency=base_ccy
        )

        blended_benchmark = await self._blended_benchmark_return(
            positions,
            total_base=total_base,
            nifty=nifty,
            sp500=sp500,
            base_currency=base_ccy,
        )

        portfolio_alpha = portfolio_return - blended_benchmark

        rebalancing = self._rebalancing_suggestions(positions, total_base=total_base)

        return PortfolioIntelligenceResponse(
            base_currency=base_ccy,
            sector_allocation=sector_allocation,
            diversification=diversification,
            per_market_alpha=per_market_alpha,
            blended_benchmark_return=blended_benchmark,
            portfolio_return=portfolio_return,
            portfolio_alpha=portfolio_alpha,
            portfolio_return_stale=True,
            unclassified_markets=unclassified_markets,
            rebalancing_suggestions=rebalancing,
        )

    # ------------------------------------------------------------------ loading

    async def _load_positions(
        self, *, user_id: UUID, base_currency: str
    ) -> list[_EnrichedPosition]:
        """Mirror of :meth:`PortfolioSummaryService._enriched_positions` but
        keeps the :class:`Instrument` in scope so we can classify by sector
        and exchange without a second query.
        """
        stmt = (
            select(Position, Instrument)
            .join(
                BrokerConnection,
                BrokerConnection.id == Position.broker_connection_id,
            )
            .join(Instrument, Instrument.id == Position.instrument_id)
            .where(BrokerConnection.user_id == user_id)
        )
        rows = list((await self._session.execute(stmt)).all())

        enriched: list[_EnrichedPosition] = []
        for position, instrument in rows:
            if position.quantity == 0:
                continue
            native_ccy = position.currency
            mv_native = position.quantity * position.avg_cost

            try:
                fx_rate = await self._fx.get_rate(base=native_ccy, quote=base_currency)
            except FxRateNotFoundError:
                # Skip positions we can't convert — they can't contribute to
                # the base-currency aggregates anyway. Log for visibility.
                logger.warning(
                    "skipping position %s: no FX rate %s->%s",
                    instrument.symbol,
                    native_ccy,
                    base_currency,
                )
                continue

            enriched.append(
                _EnrichedPosition(
                    instrument_id=instrument.id,
                    symbol=instrument.symbol,
                    exchange=instrument.exchange,
                    market=_market_for_exchange(instrument.exchange),
                    sector=_sector_for_instrument(instrument),
                    native_currency=native_ccy,
                    market_value_native=mv_native,
                    market_value_base=mv_native * fx_rate,
                )
            )
        return enriched

    # ---------------------------------------------------------------- computations

    def _sector_allocation(
        self, positions: list[_EnrichedPosition]
    ) -> dict[str, list[SectorAllocationEntry]]:
        """Per-market sector % of that market's base-currency value."""
        by_market_sector: dict[str, dict[str, Decimal]] = {}
        market_totals: dict[str, Decimal] = {}
        for p in positions:
            market_totals[p.market] = (
                market_totals.get(p.market, Decimal("0")) + p.market_value_base
            )
            by_market_sector.setdefault(p.market, {})
            by_market_sector[p.market][p.sector] = (
                by_market_sector[p.market].get(p.sector, Decimal("0")) + p.market_value_base
            )

        result: dict[str, list[SectorAllocationEntry]] = {}
        for market, sectors in by_market_sector.items():
            total = market_totals.get(market, Decimal("0"))
            if total <= 0:
                continue
            entries = [
                SectorAllocationEntry(sector=sector, pct=float(value / total))
                for sector, value in sorted(sectors.items(), key=lambda kv: -kv[1])
            ]
            result[market] = entries
        return result

    def _diversification(
        self, positions: list[_EnrichedPosition], *, total_base: Decimal
    ) -> DiversificationOut:
        if total_base <= 0:
            return DiversificationOut(hhi=0.0, geography={})

        sector_weights: dict[str, Decimal] = {}
        geo_weights: dict[str, Decimal] = {}
        for p in positions:
            sector_weights[p.sector] = (
                sector_weights.get(p.sector, Decimal("0")) + p.market_value_base
            )
            geo_weights[p.market] = geo_weights.get(p.market, Decimal("0")) + p.market_value_base

        hhi = sum((float(v / total_base) ** 2 for v in sector_weights.values()), 0.0)
        geography = {market: float(v / total_base) for market, v in geo_weights.items()}
        return DiversificationOut(hhi=hhi, geography=geography)

    def _per_market_alpha(
        self,
        positions: list[_EnrichedPosition],
        *,
        nifty: BenchmarkReturn,
        sp500: BenchmarkReturn,
    ) -> list[PerMarketAlpha]:
        """Compare each market's portfolio return to its benchmark — native ccy only."""
        # Bucket by market; compute a value-weighted return in native currency.
        # For the MVP the only "return" available on a position is 0 (no live
        # price / no price history wired into this engine). We emit 0 for the
        # portfolio side, which still makes the response shape-complete and
        # lets the UI render "benchmark = X%, you = 0% (data pending)" until
        # the price pipeline is plumbed in.
        result: list[PerMarketAlpha] = []
        # Only emit per-market alpha for benchmarked markets. OTHER positions
        # have no trusted benchmark mapping yet and must be excluded.
        markets_present = {p.market for p in positions if p.market in _BENCHMARKED_MARKETS}

        bench_by_market = {"IN": nifty, "US": sp500}
        for market in sorted(markets_present):
            bench = bench_by_market.get(market)
            if bench is None:
                continue
            # Portfolio return in native ccy — placeholder 0 until price history
            # per-position is wired (no FX conflation: each market stays native).
            # portfolio_return_stale=True flags this for the UI.
            portfolio_return_native = 0.0
            bench_return_native = float(bench.total_return)
            result.append(
                PerMarketAlpha(
                    market=market,
                    benchmark_symbol=bench.symbol,
                    benchmark_currency=bench.currency,
                    portfolio_return=portfolio_return_native,
                    benchmark_return=bench_return_native,
                    alpha=portfolio_return_native - bench_return_native,
                    stale_benchmark=bench.stale,
                    portfolio_return_stale=True,
                )
            )
        return result

    def _portfolio_return_base(
        self,
        positions: list[_EnrichedPosition],
        *,
        per_market_alpha: list[PerMarketAlpha],
        base_currency: str,
    ) -> float:
        """Portfolio return in base currency.

        Same placeholder story as :meth:`_per_market_alpha`: without per-position
        price history we return ``0.0`` and flag the response with
        ``portfolio_return_stale=True`` so callers suppress the misleading
        ``portfolio_alpha = -blended_benchmark_return`` that would otherwise
        render. Kept as a separate method so swapping in the real computation
        is local.

        Emits a one-shot WARN log per service instance to surface the
        placeholder in operations before the price pipeline lands.
        """
        if not self._placeholder_warning_emitted:
            logger.warning(
                "portfolio_return placeholder used; price pipeline not yet"
                " wired — response flagged stale"
            )
            self._placeholder_warning_emitted = True
        return 0.0

    async def _blended_benchmark_return(
        self,
        positions: list[_EnrichedPosition],
        *,
        total_base: Decimal,
        nifty: BenchmarkReturn,
        sp500: BenchmarkReturn,
        base_currency: str,
    ) -> float:
        """Blended benchmark return in ``base_currency``.

        Formula
        -------
        For each market M in {IN, US}:

            alloc_M        = base-currency MV of M-holdings / total base MV
            bench_native_M = benchmark total return in M's native ccy
            fx_change_M    = (fx(native_M → base, end)   /
                              fx(native_M → base, start)) - 1
            bench_base_M   = (1 + bench_native_M) * (1 + fx_change_M) - 1

        blended = sum(alloc_M * bench_base_M)

        The FX % change term is what translates a native-ccy benchmark
        return into the base ccy the user thinks in. For matched-currency
        markets (e.g. base=USD, market=US) the FX change is 0 and the
        native return passes through unchanged.
        """
        if total_base <= 0:
            return 0.0

        # Geography weights (base ccy).
        geo_weights: dict[str, Decimal] = {}
        for p in positions:
            geo_weights[p.market] = geo_weights.get(p.market, Decimal("0")) + p.market_value_base

        bench_by_market: dict[str, BenchmarkReturn] = {"IN": nifty, "US": sp500}
        native_by_market: dict[str, str] = {"IN": "INR", "US": "USD"}

        blended = 0.0
        for market, weight_base in geo_weights.items():
            bench = bench_by_market.get(market)
            if bench is None or weight_base <= 0:
                continue
            alloc = float(weight_base / total_base)
            native_ccy = native_by_market[market]

            fx_change = await self._fx_change_pct(
                native=native_ccy,
                base=base_currency,
                period_start=bench.period_start,
                period_end=bench.period_end,
            )
            native_return = float(bench.total_return)
            bench_in_base = (1.0 + native_return) * (1.0 + fx_change) - 1.0
            blended += alloc * bench_in_base
        return blended

    async def _fx_change_pct(
        self,
        *,
        native: str,
        base: str,
        period_start: datetime,
        period_end: datetime,
    ) -> float:
        """Percent change in the ``native → base`` rate over the window.

        Returns 0.0 when ``native == base`` or when either end of the window
        has no rate in the DB.
        """
        if native.upper() == base.upper():
            return 0.0
        try:
            start_rate = await self._fx.get_rate(base=native, quote=base, as_of=period_start)
            end_rate = await self._fx.get_rate(base=native, quote=base, as_of=period_end)
        except FxRateNotFoundError:
            return 0.0
        if start_rate <= 0:
            return 0.0
        return float(end_rate / start_rate) - 1.0

    def _rebalancing_suggestions(
        self, positions: list[_EnrichedPosition], *, total_base: Decimal
    ) -> list[RebalancingSuggestion]:
        """Emit a suggestion for every sector whose weight exceeds 40 %."""
        if total_base <= 0:
            return []
        sector_weights: dict[str, Decimal] = {}
        for p in positions:
            sector_weights[p.sector] = (
                sector_weights.get(p.sector, Decimal("0")) + p.market_value_base
            )

        suggestions: list[RebalancingSuggestion] = []
        for sector, value in sorted(sector_weights.items(), key=lambda kv: -kv[1]):
            pct = float(value / total_base)
            if pct > SECTOR_CONCENTRATION_THRESHOLD:
                suggestions.append(
                    RebalancingSuggestion(
                        type="sector_concentration",
                        sector=sector,
                        current_pct=pct,
                        suggestion=f"Consider reducing exposure to {sector}.",
                        disclaimer=DISCLAIMER_TEXT,
                    )
                )
        return suggestions


__all__ = [
    "DISCLAIMER_TEXT",
    "PortfolioIntelligenceService",
    "SECTOR_CONCENTRATION_THRESHOLD",
]
