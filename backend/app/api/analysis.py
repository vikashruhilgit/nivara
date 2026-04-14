"""Analysis API routes.

Currently exposes a single endpoint:

* ``GET /api/analysis/{symbol}/fundamental`` — returns raw fundamentals plus
  scored components (0-100) for a given instrument symbol. US-listed
  instruments pull from SEC EDGAR; anything else falls back to Yahoo Finance
  fundamentals via :class:`backend.app.data.yahoo.YahooProvider`.

Authentication
--------------
All routes require a bearer token via
:func:`backend.app.auth.dependencies.get_current_user`. The recommendation
pipeline (Month 3) calls these endpoints server-side with the user's token.

Caching
-------
Both providers write through the shared ``data:{provider}:fundamentals:*``
Redis cache with a 24h TTL. The API does not add a second cache layer —
caching at the provider boundary is simpler and survives endpoint changes.

Symbol resolution
-----------------
Callers pass the canonical symbol (e.g. ``AAPL`` or ``RELIANCE``) plus an
``exchange`` query parameter. When ``exchange`` is a US market
(NYSE/NASDAQ/ARCA/AMEX/BATS) we use EDGAR; otherwise we build the Yahoo
ticker via :func:`backend.app.data.yahoo.resolve_yahoo_symbol`-equivalent
logic and fall back to Yahoo fundamentals. We intentionally do NOT try EDGAR
for non-US exchanges — SEC coverage for foreign private issuers via 20-F is
spotty and introduces failure modes we'd rather avoid in the MVP.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from backend.app.analysis.fundamental import FundamentalScore, score_fundamentals
from backend.app.analysis.sentiment import SentimentResult, compute_sentiment
from backend.app.analysis.technical import (
    TechnicalAnalysis,
    analyze_with_cache,
    load_ohlcv_from_db,
)
from backend.app.auth.dependencies import get_current_user
from backend.app.config import get_settings
from backend.app.data.edgar import EdgarClient, EdgarFundamentals
from backend.app.data.errors import DataProviderError, SymbolNotFoundError
from backend.app.data.gnews import GNewsClient
from backend.app.data.reddit import RedditClient
from backend.app.data.rss import RssFallbackClient
from backend.app.data.yahoo import YahooProvider
from backend.app.db import get_session
from backend.app.models.instruments import Instrument
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

_US_EXCHANGES = frozenset({"NYSE", "NASDAQ", "ARCA", "AMEX", "BATS", "NYSEARCA"})
_NSE_EXCHANGES = frozenset({"NSE", "XNSE"})
_BSE_EXCHANGES = frozenset({"BSE", "XBOM"})


# ---- Response schema -------------------------------------------------------


class FundamentalComponents(BaseModel):
    """Per-metric 0-100 scores (``None`` when a component is not scorable)."""

    revenue_growth: int | None = Field(None, ge=0, le=100)
    earnings_trend: int | None = Field(None, ge=0, le=100)
    debt_health: int | None = Field(None, ge=0, le=100)
    pe_valuation: int | None = Field(None, ge=0, le=100)
    cash_flow: int | None = Field(None, ge=0, le=100)


class FundamentalRawData(BaseModel):
    """Subset of the raw fundamentals actually used by scoring.

    Callers can still hit the provider layer directly if they need the full
    payload. Exposed here so the mobile client can render the "why" behind a
    score without a second round-trip.
    """

    revenue_ttm: Decimal | None = None
    earnings_ttm: Decimal | None = None
    pe_ratio: Decimal | None = None
    debt_to_equity: Decimal | None = None
    free_cash_flow: Decimal | None = None
    eps: Decimal | None = None


class FundamentalAnalysisResponse(BaseModel):
    """GET /api/analysis/{symbol}/fundamental response body."""

    symbol: str
    exchange: str
    provider: str = Field(..., description="Which DataProvider served this response.")
    filing_date: date | None = None
    fetched_at: datetime
    composite_score: int | None = Field(
        None,
        ge=0,
        le=100,
        description="Weighted composite over available components (0-100).",
    )
    components: FundamentalComponents
    raw: FundamentalRawData


# ---- Dependencies ----------------------------------------------------------


def _get_edgar_client() -> EdgarClient:
    # A fresh client per request is wasteful (TCP reuse lost) but keeps the
    # dependency trivially testable. The HTTP layer's keep-alive benefits are
    # recovered once we move to a lifespan-scoped singleton in a later job.
    return EdgarClient(redis=get_redis())


def _get_yahoo_provider() -> YahooProvider:
    return YahooProvider(redis=get_redis())


def _get_gnews_client() -> GNewsClient:
    settings = get_settings()
    return GNewsClient(api_key=settings.gnews_api_key, redis=get_redis())


def _get_rss_client() -> RssFallbackClient:
    return RssFallbackClient()


def _get_reddit_client() -> RedditClient:
    settings = get_settings()
    return RedditClient(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
    )


# ---- Route -----------------------------------------------------------------


@router.get(
    "/{symbol}/fundamental",
    response_model=FundamentalAnalysisResponse,
)
async def get_fundamental_analysis(
    symbol: str,
    exchange: str = Query(
        ...,
        description="Listing exchange (e.g. NASDAQ, NSE, BSE). Determines provider selection.",
        min_length=2,
        max_length=16,
    ),
    price: Decimal | None = Query(
        None,
        description=(
            "Optional current market price; combined with EDGAR EPS to derive P/E "
            "when the provider has not pre-computed it."
        ),
        gt=0,
    ),
    edgar: EdgarClient = Depends(_get_edgar_client),
    yahoo: YahooProvider = Depends(_get_yahoo_provider),
    _user: User = Depends(get_current_user),
) -> FundamentalAnalysisResponse:
    symbol_u = symbol.upper().strip()
    exchange_u = exchange.upper().strip()

    if exchange_u in _US_EXCHANGES:
        return await _fundamentals_via_edgar(
            edgar=edgar, symbol=symbol_u, exchange=exchange_u, price=price
        )
    if exchange_u in _NSE_EXCHANGES or exchange_u in _BSE_EXCHANGES:
        return await _fundamentals_via_yahoo(
            yahoo=yahoo, symbol=symbol_u, exchange=exchange_u, price=price
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"unsupported exchange {exchange_u!r}",
    )


# ---- Provider dispatch -----------------------------------------------------


async def _fundamentals_via_edgar(
    *,
    edgar: EdgarClient,
    symbol: str,
    exchange: str,
    price: Decimal | None,
) -> FundamentalAnalysisResponse:
    try:
        fundamentals = await edgar.get_fundamentals(symbol)
    except SymbolNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except DataProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"EDGAR upstream error: {exc}",
        ) from exc

    score = score_fundamentals(fundamentals, price=price)
    return _to_response(
        symbol=symbol,
        exchange=exchange,
        provider="edgar",
        filing_date=fundamentals.filing_date,
        fetched_at=fundamentals.fetched_at,
        raw=FundamentalRawData(
            revenue_ttm=fundamentals.revenue_ttm,
            earnings_ttm=fundamentals.earnings_ttm,
            pe_ratio=_derived_pe(fundamentals, price),
            debt_to_equity=fundamentals.debt_to_equity,
            free_cash_flow=fundamentals.free_cash_flow,
            eps=fundamentals.eps,
        ),
        score=score,
    )


async def _fundamentals_via_yahoo(
    *,
    yahoo: YahooProvider,
    symbol: str,
    exchange: str,
    price: Decimal | None,
) -> FundamentalAnalysisResponse:
    # Yahoo symbol convention mirrors resolve_yahoo_symbol but we don't have
    # an Instrument row here — rebuild by hand.
    if exchange in _NSE_EXCHANGES:
        yahoo_symbol = f"{symbol}.NS"
    elif exchange in _BSE_EXCHANGES:
        yahoo_symbol = f"{symbol}.BO"
    else:  # pragma: no cover — dispatcher guarantees this branch is unreachable
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported exchange {exchange!r}",
        )

    try:
        fundamentals = await yahoo.get_fundamentals(yahoo_symbol)
    except SymbolNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except DataProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Yahoo upstream error: {exc}",
        ) from exc

    # Yahoo Fundamentals schema carries fewer fields than EDGAR; project it
    # onto EdgarFundamentals so we can reuse the scoring engine. Missing
    # fields stay None and the scorer degrades gracefully.
    projected = EdgarFundamentals(
        symbol=fundamentals.symbol,
        cik="",  # Yahoo has no CIK; empty string preserves type.
        filing_date=None,
        revenue_ttm=fundamentals.revenue_ttm,
        revenue_prior_ttm=None,  # Yahoo info dict does not expose prior-year.
        earnings_ttm=None,
        earnings_prior_ttm=None,
        pe_ratio=fundamentals.pe_ratio,
        debt_to_equity=None,
        free_cash_flow=None,
        eps=fundamentals.eps,
        fetched_at=fundamentals.fetched_at,
    )
    score = score_fundamentals(projected, price=price)

    return _to_response(
        symbol=symbol,
        exchange=exchange,
        provider="yahoo",
        filing_date=None,
        fetched_at=fundamentals.fetched_at,
        raw=FundamentalRawData(
            revenue_ttm=fundamentals.revenue_ttm,
            earnings_ttm=None,
            pe_ratio=fundamentals.pe_ratio,
            debt_to_equity=None,
            free_cash_flow=None,
            eps=fundamentals.eps,
        ),
        score=score,
    )


# ---- Helpers ---------------------------------------------------------------


def _derived_pe(fundamentals: EdgarFundamentals, price: Decimal | None) -> Decimal | None:
    """EDGAR itself doesn't publish P/E; derive it from price + EPS if possible."""
    if fundamentals.pe_ratio is not None:
        return fundamentals.pe_ratio
    if price is not None and fundamentals.eps is not None and fundamentals.eps != 0:
        return (price / fundamentals.eps).quantize(Decimal("0.0001"))
    return None


def _to_response(
    *,
    symbol: str,
    exchange: str,
    provider: str,
    filing_date: date | None,
    fetched_at: datetime,
    raw: FundamentalRawData,
    score: FundamentalScore,
) -> FundamentalAnalysisResponse:
    return FundamentalAnalysisResponse(
        symbol=symbol,
        exchange=exchange,
        provider=provider,
        filing_date=filing_date,
        fetched_at=fetched_at,
        composite_score=score.composite,
        components=FundamentalComponents(
            revenue_growth=score.revenue_growth,
            earnings_trend=score.earnings_trend,
            debt_health=score.debt_health,
            pe_valuation=score.pe_valuation,
            cash_flow=score.cash_flow,
        ),
        raw=raw,
    )


@router.get(
    "/{symbol}/sentiment",
    response_model=SentimentResult,
)
async def get_sentiment_analysis(
    symbol: str,
    gnews: GNewsClient = Depends(_get_gnews_client),
    rss: RssFallbackClient = Depends(_get_rss_client),
    reddit: RedditClient = Depends(_get_reddit_client),
    _user: User = Depends(get_current_user),
) -> SentimentResult:
    """Return composite sentiment (-1 to +1) with news/social/macro breakdown.

    Each source degrades independently (per AC #3 and #6): GNews rate-limit
    falls back to RSS, Reddit auth failures redistribute social weight to
    news + macro, and missing FRED data redistributes macro weight to
    news + social.
    """
    symbol_u = symbol.upper().strip()
    if not symbol_u:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="symbol is required")
    # FRED observations are threaded through only when a prior job has
    # cached them; the sentiment engine already defaults macro to neutral
    # when this is None (AC #6).
    return await compute_sentiment(
        symbol_u,
        gnews=gnews,
        rss=rss,
        reddit=reddit,
        redis=get_redis(),
        fred_observations=None,
    )


# ---- Technical analysis ----------------------------------------------------


class TechnicalIndicator(BaseModel):
    """Single indicator in the technical response.

    ``value`` is the normalised signal in ``[-1, +1]``. ``raw`` is the
    underlying indicator reading (RSI, histogram, %B, etc.) for UI display.
    ``insufficient_data`` is ``True`` when the OHLCV history was too short
    for this indicator's lookback window.
    """

    value: float | None = Field(None, ge=-1, le=1)
    raw: float | None = None
    insufficient_data: bool = False


class TechnicalAnalysisResponse(BaseModel):
    """GET /api/analysis/{symbol}/technical response body."""

    symbol: str
    exchange: str
    bars_analyzed: int
    composite_score: float | None = Field(None, ge=-1, le=1)
    action: str | None = Field(
        None,
        description="strong_sell | sell | hold | buy | strong_buy (None when no indicators scored).",
    )
    insufficient_data_flags: list[str] = Field(default_factory=list)
    rsi: TechnicalIndicator
    macd: TechnicalIndicator
    ma_alignment: TechnicalIndicator
    bollinger: TechnicalIndicator
    volume: TechnicalIndicator
    atr: TechnicalIndicator


def _technical_to_response(
    *, symbol: str, exchange: str, analysis: TechnicalAnalysis
) -> TechnicalAnalysisResponse:
    def _ind(r: Any) -> TechnicalIndicator:
        return TechnicalIndicator(
            value=r.value,
            raw=r.raw,
            insufficient_data=r.insufficient_data,
        )

    return TechnicalAnalysisResponse(
        symbol=symbol,
        exchange=exchange,
        bars_analyzed=analysis.bars_analyzed,
        composite_score=analysis.composite_score,
        action=analysis.action,
        insufficient_data_flags=analysis.insufficient_data_flags,
        rsi=_ind(analysis.rsi),
        macd=_ind(analysis.macd),
        ma_alignment=_ind(analysis.ma_alignment),
        bollinger=_ind(analysis.bollinger),
        volume=_ind(analysis.volume),
        atr=_ind(analysis.atr),
    )


@router.get(
    "/{symbol}/technical",
    response_model=TechnicalAnalysisResponse,
)
async def get_technical_analysis(
    symbol: str,
    exchange: str = Query(
        ...,
        description="Listing exchange (e.g. NASDAQ, NSE). Resolves the Instrument row.",
        min_length=2,
        max_length=16,
    ),
    bars: int = Query(
        252,
        description="Number of OHLCV bars to read from price_history (default: 1 trading year).",
        ge=30,
        le=1000,
    ),
    session: AsyncSession = Depends(get_session),
    redis: Any = Depends(get_redis),
    _user: User = Depends(get_current_user),
) -> TechnicalAnalysisResponse:
    """Compute composite technical signal from cached OHLCV history.

    Reads up to ``bars`` rows from :class:`PriceHistory` (populated by the
    data-provider job) and runs the 6-indicator pipeline. Indicators are
    cached in Redis for 5 minutes keyed by ``tech:{instrument_id}:{name}``;
    on a full cache hit the indicator math is skipped and only the composite
    is recomputed.
    """
    symbol_u = symbol.upper().strip()
    exchange_u = exchange.upper().strip()

    stmt = select(Instrument).where(
        Instrument.symbol == symbol_u,
        Instrument.exchange == exchange_u,
    )
    instrument = (await session.execute(stmt)).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"instrument not found: {symbol_u} on {exchange_u}",
        )

    ohlcv = await load_ohlcv_from_db(session, instrument.id, bars=bars)
    if ohlcv.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no price history for {symbol_u} on {exchange_u}",
        )

    analysis = await analyze_with_cache(redis, instrument.id, ohlcv)
    return _technical_to_response(symbol=symbol_u, exchange=exchange_u, analysis=analysis)


__all__ = [
    "FundamentalAnalysisResponse",
    "FundamentalComponents",
    "FundamentalRawData",
    "TechnicalAnalysisResponse",
    "TechnicalIndicator",
    "router",
]
