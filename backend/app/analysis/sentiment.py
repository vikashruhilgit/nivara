"""Composite sentiment scoring engine.

Combines three signals into a single score in ``[-1, +1]``:

* **News** — FinBERT-scored articles from GNews (with RSS fallback). Each
  article's score is weighted by an exponential time-decay with a 24h
  half-life so stale headlines don't dominate the present score.
* **Social** — FinBERT-scored Reddit submissions. 1h half-life (much
  shorter) because social sentiment moves faster. Reddit is intentionally
  *degradable* — if :class:`backend.app.data.reddit.RedditUnavailable` is
  raised, social weight is redistributed across news + macro per AC #3.
* **Macro** — Derived from FRED economic indicators. Maps unemployment
  delta, Fed-funds-rate direction, and GDP growth trend to a scalar in
  ``[-1, +1]`` per AC #5. If FRED is unavailable, macro defaults to
  neutral (0.0) and its 30% weight is redistributed to news + social per
  AC #6.

Weight redistribution
---------------------
The base weights are::

    news  = 0.50
    social = 0.20
    macro = 0.30

When a leg degrades, the remaining legs are re-normalised so they still
sum to 1.0. Two specific degradation modes are codified in the briefs:

* Reddit unavailable → ``news=0.60, macro=0.40, social=0.0``
* FRED unavailable   → ``news=0.70, social=0.30, macro=0.0``

Both unavailable → ``news=1.0`` (only signal left).

Decay model
-----------
For any timestamped item::

    decayed_weight = 0.5 ** (age_hours / half_life_hours)

We apply decay *per item* and then compute the leg score as the
sample-weighted mean of item scores. Items with age > 10× the half-life
contribute negligibly but are not truncated — the math handles them.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from backend.app.analysis.finbert import FinBertUnavailable, score_batch
from backend.app.data.gnews import (
    GNewsUnavailable,
    NewsArticle,
)
from backend.app.data.reddit import RedditPost, RedditUnavailable
from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover
    from backend.app.data.gnews import GNewsClient
    from backend.app.data.reddit import RedditClient
    from backend.app.data.rss import RssFallbackClient
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# ---- Weights ---------------------------------------------------------------

NEWS_WEIGHT = 0.50
SOCIAL_WEIGHT = 0.20
MACRO_WEIGHT = 0.30

NEWS_HALF_LIFE_HOURS = 24.0
SOCIAL_HALF_LIFE_HOURS = 1.0

# FRED indicator series IDs (see backend/app/data/fred.py for pattern).
FRED_UNRATE = "UNRATE"  # Civilian unemployment rate (%)
FRED_FEDFUNDS = "FEDFUNDS"  # Effective federal funds rate (%)
FRED_GDP = "GDPC1"  # Real GDP (chained 2017 dollars, quarterly)


# ---- Output schema ---------------------------------------------------------


class SentimentBreakdown(BaseModel):
    """Per-leg detail so callers can see *why* composite is what it is."""

    news_weight: float = Field(..., ge=0.0, le=1.0)
    social_weight: float = Field(..., ge=0.0, le=1.0)
    macro_weight: float = Field(..., ge=0.0, le=1.0)
    news_available: bool
    social_available: bool
    macro_available: bool


class SentimentResult(BaseModel):
    """Final composite sentiment for a symbol.

    ``composite``, ``news_score``, ``social_score``, and ``macro_score`` are
    all in ``[-1, +1]``. Unavailable legs report ``0.0`` and are flagged in
    :attr:`breakdown`.
    """

    symbol: str
    composite: float = Field(..., ge=-1.0, le=1.0)
    news_score: float = Field(..., ge=-1.0, le=1.0)
    social_score: float = Field(..., ge=-1.0, le=1.0)
    macro_score: float = Field(..., ge=-1.0, le=1.0)
    article_count: int
    reddit_count: int
    breakdown: SentimentBreakdown
    computed_at: datetime


# ---- Decay & aggregation ---------------------------------------------------


def _decay_weight(age_hours: float, half_life_hours: float) -> float:
    """Exponential decay — returns the relative weight of an aged item.

    ``age_hours == 0`` → weight 1.0. ``age_hours == half_life`` → 0.5.
    Negative ages (future-dated items, clock skew) clamp to 1.0.
    """
    if age_hours <= 0:
        return 1.0
    return float(0.5 ** (age_hours / half_life_hours))


def _age_hours(item_ts: datetime, now: datetime) -> float:
    delta = now - item_ts
    return max(delta.total_seconds() / 3600.0, 0.0)


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    """Sample-weighted mean with graceful zero-weight handling."""
    if not values:
        return 0.0
    total_weight = sum(weights)
    if total_weight <= 0:
        return 0.0
    weighted_sum = sum(v * w for v, w in zip(values, weights, strict=True))
    return weighted_sum / total_weight


def _resolve_weights(
    *,
    news_available: bool,
    social_available: bool,
    macro_available: bool,
) -> tuple[float, float, float]:
    """Return the re-normalised ``(news, social, macro)`` weights.

    Implements the redistribution rules from ACs #3 and #6 explicitly so
    the behaviour is readable in tests without re-normalisation math.
    """
    # Everything degraded → no signal at all.
    if not news_available and not social_available and not macro_available:
        return 0.0, 0.0, 0.0
    # Specific cases from the brief come first — exact values, no surprises.
    if news_available and not social_available and macro_available:
        # AC #3: Reddit unavailable → news 60%, macro 40%.
        return 0.60, 0.0, 0.40
    if news_available and social_available and not macro_available:
        # AC #6: FRED unavailable → news 70%, social 30%.
        return 0.70, 0.30, 0.0
    if news_available and not social_available and not macro_available:
        # Only news left.
        return 1.0, 0.0, 0.0
    if not news_available and social_available and macro_available:
        # News unavailable: renormalise social+macro. Keep their ratio
        # (0.20 : 0.30 = 2:3).
        return 0.0, 0.40, 0.60
    if not news_available and social_available and not macro_available:
        return 0.0, 1.0, 0.0
    if not news_available and not social_available and macro_available:
        return 0.0, 0.0, 1.0
    # Normal case: all three available.
    return NEWS_WEIGHT, SOCIAL_WEIGHT, MACRO_WEIGHT


# ---- Leg computation -------------------------------------------------------


async def _score_news_leg(
    articles: list[NewsArticle],
    *,
    now: datetime,
    redis: Redis | None,
) -> float:
    """Score a list of news articles with 24h half-life decay."""
    if not articles:
        return 0.0
    # FinBERT on title + short summary. Keeping inputs short keeps inference
    # under the 512-token BERT limit and avoids needing manual truncation.
    texts = [f"{a.title}. {a.summary[:400]}" for a in articles]
    try:
        scores = await score_batch(texts, redis=redis)
    except FinBertUnavailable as exc:
        logger.warning("FinBERT unavailable for news leg: %s", exc)
        return 0.0
    weights = [
        _decay_weight(_age_hours(a.published_at, now), NEWS_HALF_LIFE_HOURS) for a in articles
    ]
    return _weighted_mean(scores, weights)


async def _score_social_leg(
    posts: list[RedditPost],
    *,
    now: datetime,
    redis: Redis | None,
) -> float:
    """Score Reddit posts with 1h half-life decay."""
    if not posts:
        return 0.0
    texts = [f"{p.title}. {p.body[:400]}" for p in posts]
    try:
        scores = await score_batch(texts, redis=redis)
    except FinBertUnavailable as exc:
        logger.warning("FinBERT unavailable for social leg: %s", exc)
        return 0.0
    weights = [_decay_weight(_age_hours(p.created_at, now), SOCIAL_HALF_LIFE_HOURS) for p in posts]
    return _weighted_mean(scores, weights)


async def compute_macro_score(
    *,
    fred_observations: dict[str, list[tuple[datetime, float]]] | None,
) -> float:
    """Compute the macro leg scalar from a dict of FRED observation series.

    ``fred_observations`` maps series IDs to lists of ``(timestamp, value)``
    tuples sorted ascending by timestamp. When ``None`` (FRED unavailable),
    returns ``0.0`` — the caller then excludes macro and redistributes.

    Mapping rules (all contribute equally, 1/3 each):

    * **Unemployment delta** — compare latest to 12 months prior; rising
      unemployment is a negative signal. Scale: a +1pp rise → -1.0; a -1pp
      fall → +1.0, linear between.
    * **Fed funds direction** — compare latest to 3 months prior. Rising
      rates are a negative signal for equities (tightening). Scale: a
      +50bps move → -1.0; -50bps → +1.0.
    * **GDP growth trend** — YoY real GDP growth. +5% → +1.0; -5% → -1.0.
    """
    if not fred_observations:
        return 0.0

    def _latest(series_id: str) -> tuple[datetime, float] | None:
        obs = fred_observations.get(series_id) or []
        return obs[-1] if obs else None

    def _value_at_or_before(series_id: str, target: datetime) -> tuple[datetime, float] | None:
        obs = fred_observations.get(series_id) or []
        best: tuple[datetime, float] | None = None
        for ts, val in obs:
            if ts <= target:
                best = (ts, val)
            else:
                break
        return best

    components: list[float] = []

    # Unemployment YoY delta.
    unrate_latest = _latest(FRED_UNRATE)
    if unrate_latest is not None:
        prior = _value_at_or_before(
            FRED_UNRATE, unrate_latest[0].replace(year=unrate_latest[0].year - 1)
        )
        if prior is not None:
            delta_pp = unrate_latest[1] - prior[1]
            # Rising unemployment → negative. Clamp at ±1pp.
            components.append(max(-1.0, min(1.0, -delta_pp)))

    # Fed funds 3-month change.
    ff_latest = _latest(FRED_FEDFUNDS)
    if ff_latest is not None:
        # Approximate "3 months prior" by subtracting 90 days.
        target = ff_latest[0] - timedelta(days=90)
        prior = _value_at_or_before(FRED_FEDFUNDS, target)
        if prior is not None:
            delta_bps = (ff_latest[1] - prior[1]) * 100.0  # pp → bps
            # +50bps tightening → -1.0; -50bps easing → +1.0.
            components.append(max(-1.0, min(1.0, -delta_bps / 50.0)))

    # GDP YoY growth.
    gdp_latest = _latest(FRED_GDP)
    if gdp_latest is not None:
        prior = _value_at_or_before(FRED_GDP, gdp_latest[0].replace(year=gdp_latest[0].year - 1))
        if prior is not None and prior[1] > 0:
            yoy_pct = (gdp_latest[1] - prior[1]) / prior[1] * 100.0
            # ±5% YoY maps to ±1.0.
            components.append(max(-1.0, min(1.0, yoy_pct / 5.0)))

    if not components:
        return 0.0
    return sum(components) / len(components)


# ---- Public API ------------------------------------------------------------


async def compute_sentiment(
    symbol: str,
    *,
    gnews: GNewsClient | None,
    rss: RssFallbackClient | None,
    reddit: RedditClient | None,
    redis: Redis | None,
    fred_observations: dict[str, list[tuple[datetime, float]]] | None = None,
    now: datetime | None = None,
    news_limit: int = 15,
    reddit_limit: int = 30,
) -> SentimentResult:
    """Compute the composite sentiment for ``symbol``.

    Each data source is independently optional; see module docstring for
    the exact weight redistribution rules.
    """
    symbol_u = symbol.upper().strip()
    now = now or datetime.now(tz=UTC)

    # ---- News leg --------------------------------------------------------
    articles: list[NewsArticle] = []
    news_available = False
    if gnews is not None:
        try:
            articles = await gnews.search_for_symbols([symbol_u], max_results=news_limit)
            news_available = True
        except GNewsUnavailable as exc:
            logger.info("GNews unavailable for %s (%s); trying RSS", symbol_u, exc)
    if not articles and rss is not None:
        try:
            articles = await rss.fetch_for_symbol(symbol_u, max_results=news_limit)
            news_available = news_available or bool(articles)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RSS fallback failed for %s: %s", symbol_u, exc)
    # News is "available" if we got any articles from either source.
    news_available = bool(articles)

    news_score = await _score_news_leg(articles, now=now, redis=redis) if articles else 0.0

    # ---- Social leg ------------------------------------------------------
    posts: list[RedditPost] = []
    social_available = True
    if reddit is None:
        social_available = False
    else:
        try:
            posts = await reddit.fetch_posts(symbol_u, limit=reddit_limit)
        except RedditUnavailable as exc:
            logger.info("Reddit unavailable for %s: %s", symbol_u, exc)
            social_available = False

    social_score = (
        await _score_social_leg(posts, now=now, redis=redis)
        if (social_available and posts)
        else 0.0
    )

    # ---- Macro leg -------------------------------------------------------
    macro_available = bool(fred_observations)
    macro_score = (
        await compute_macro_score(fred_observations=fred_observations) if macro_available else 0.0
    )

    # ---- Composite -------------------------------------------------------
    w_news, w_social, w_macro = _resolve_weights(
        news_available=news_available,
        social_available=social_available,
        macro_available=macro_available,
    )
    composite_raw = w_news * news_score + w_social * social_score + w_macro * macro_score
    composite = max(-1.0, min(1.0, composite_raw))

    return SentimentResult(
        symbol=symbol_u,
        composite=composite,
        news_score=news_score,
        social_score=social_score,
        macro_score=macro_score,
        article_count=len(articles),
        reddit_count=len(posts),
        breakdown=SentimentBreakdown(
            news_weight=w_news,
            social_weight=w_social,
            macro_weight=w_macro,
            news_available=news_available,
            social_available=social_available,
            macro_available=macro_available,
        ),
        computed_at=now,
    )


__all__ = [
    "FRED_FEDFUNDS",
    "FRED_GDP",
    "FRED_UNRATE",
    "MACRO_WEIGHT",
    "NEWS_HALF_LIFE_HOURS",
    "NEWS_WEIGHT",
    "SOCIAL_HALF_LIFE_HOURS",
    "SOCIAL_WEIGHT",
    "SentimentBreakdown",
    "SentimentResult",
    "_decay_weight",
    "_resolve_weights",
    "compute_macro_score",
    "compute_sentiment",
]


# Note: ``_decay_weight`` and ``_resolve_weights`` are exported because the
# sentiment test suite asserts their math directly (AC #4 decay window,
# AC #3/#6 redistribution rules). They remain underscored to flag "not for
# external callers" — public entry is :func:`compute_sentiment`.
