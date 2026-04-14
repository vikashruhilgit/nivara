"""GNews (gnews.io) async client with daily rate-limit tracking.

GNews serves financial news on a free-tier budget of 100 requests per day. We
track daily usage in Redis (key ``data:gnews:rate:{YYYY-MM-DD}``) and expose a
:class:`GNewsRateLimitError` when the budget is exhausted so the caller (the
sentiment pipeline) can fall back to :mod:`backend.app.data.rss`.

Auth
----
GNews requires a ``GNEWS_API_KEY`` env var (loaded via ``Settings``). Without
it, any call raises :class:`GNewsApiKeyMissingError` — a subclass of
:class:`GNewsUnavailable` that lets the caller trigger the RSS fallback.

Response shape
--------------
The public GNews ``/search`` endpoint returns::

    {"totalArticles": N, "articles": [{"title", "description", "content",
      "url", "image", "publishedAt", "source": {"name", "url"}}, ...]}

We project this onto :class:`NewsArticle`, keeping only fields downstream
scoring needs. ``published_at`` is parsed as timezone-aware UTC.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

GNEWS_BASE_URL = "https://gnews.io/api/v4/search"
GNEWS_DAILY_BUDGET = 100
GNEWS_DEFAULT_TIMEOUT = 10.0


class GNewsUnavailable(Exception):
    """Base class for all GNews upstream failures (network, auth, rate limit)."""


class GNewsApiKeyMissingError(GNewsUnavailable):
    """No ``GNEWS_API_KEY`` configured — caller should fall back to RSS."""


class GNewsRateLimitError(GNewsUnavailable):
    """Daily request budget exhausted. Caller should fall back to RSS."""


class NewsArticle(BaseModel):
    """A single scored-eligible news article.

    ``source`` is the publisher name; ``summary`` is description or content
    depending on what GNews returned. ``published_at`` is always UTC.
    """

    title: str
    source: str
    url: str
    published_at: datetime
    summary: str = Field(default="")


def _rate_limit_key(today: date | None = None) -> str:
    today = today or datetime.now(tz=UTC).date()
    return f"data:gnews:rate:{today.isoformat()}"


async def _current_usage(redis: Redis, today: date | None = None) -> int:
    raw = await redis.get(_rate_limit_key(today))
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


async def _bump_usage(redis: Redis, today: date | None = None) -> int:
    """Increment daily counter; set 25h TTL on the key so it auto-expires."""
    key = _rate_limit_key(today)
    # INCR is atomic; set TTL only when the key was newly created (value==1).
    count_val: Any = await redis.incr(key)
    count = int(count_val)
    if count == 1:
        # 25h TTL gives a 1h overlap around midnight so we never lose the key
        # mid-request due to a tiny clock skew. Harmless: next day's key is
        # a different bucket anyway.
        await redis.expire(key, 60 * 60 * 25)
    return count


class GNewsClient:
    """Async GNews search client with per-day budget tracking."""

    def __init__(
        self,
        *,
        api_key: str | None,
        redis: Redis,
        client: httpx.AsyncClient | None = None,
        timeout: float = GNEWS_DEFAULT_TIMEOUT,
        daily_budget: int = GNEWS_DAILY_BUDGET,
    ) -> None:
        self._api_key = api_key
        self._redis = redis
        self._client = client
        self._timeout = timeout
        self._daily_budget = daily_budget

    async def remaining_budget(self) -> int:
        """Return the number of GNews requests still available today."""
        used = await _current_usage(self._redis)
        return max(self._daily_budget - used, 0)

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        lang: str = "en",
    ) -> list[NewsArticle]:
        """Search GNews for ``query``, returning up to ``max_results`` articles.

        Raises
        ------
        GNewsApiKeyMissingError
            When no API key is configured.
        GNewsRateLimitError
            When the daily 100-request budget is already exhausted (or the
            upstream returns HTTP 429).
        GNewsUnavailable
            Wraps network or parse failures.
        """
        if not self._api_key:
            raise GNewsApiKeyMissingError("GNEWS_API_KEY is not configured")

        # Check budget *before* issuing the request to avoid burning the quota.
        used = await _current_usage(self._redis)
        if used >= self._daily_budget:
            raise GNewsRateLimitError(
                f"GNews daily budget {self._daily_budget} exhausted ({used} used)"
            )

        params: dict[str, str] = {
            "q": query,
            "apikey": self._api_key,
            "lang": lang,
            "max": str(min(max_results, 100)),
            "sortby": "publishedAt",
        }
        try:
            payload = await self._request_json(GNEWS_BASE_URL, params=params)
        except httpx.HTTPStatusError as exc:
            # Upstream 429 → surface as rate-limit for uniform handling.
            if exc.response.status_code == 429:
                raise GNewsRateLimitError("GNews returned HTTP 429") from exc
            raise GNewsUnavailable(f"GNews HTTP error: {exc}") from exc
        except httpx.HTTPError as exc:
            raise GNewsUnavailable(f"GNews HTTP error: {exc}") from exc

        # Only bump usage on a successful response so failed calls don't burn
        # quota (GNews itself doesn't count errors against the free tier).
        await _bump_usage(self._redis)

        return self._parse_articles(payload)

    async def search_for_symbols(
        self,
        symbols: list[str],
        *,
        max_results: int = 10,
    ) -> list[NewsArticle]:
        """Batch search for multiple symbols via a single OR-joined query.

        Batching by sector or symbol group is how we stretch the 100/day
        budget — one request can return articles for 5-10 symbols.
        """
        if not symbols:
            return []
        # Quote each symbol so GNews treats them as literals; join with OR.
        query = " OR ".join(f'"{s.upper()}"' for s in symbols)
        return await self.search(query, max_results=max_results)

    @staticmethod
    def _parse_articles(payload: dict[str, Any]) -> list[NewsArticle]:
        articles: list[NewsArticle] = []
        for raw in payload.get("articles") or []:
            try:
                published_raw = raw.get("publishedAt")
                if not published_raw:
                    continue
                # GNews uses ISO-8601 with "Z" — normalise to aware UTC.
                published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=UTC)
                source_name = (raw.get("source") or {}).get("name") or "unknown"
                summary = raw.get("description") or raw.get("content") or ""
                title = raw.get("title") or ""
                url = raw.get("url") or ""
                if not title or not url:
                    continue
                articles.append(
                    NewsArticle(
                        title=title,
                        source=source_name,
                        url=url,
                        published_at=published_at,
                        summary=summary,
                    )
                )
            except (TypeError, ValueError) as exc:
                logger.debug("skipping malformed GNews article: %s", exc)
                continue
        return articles

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


__all__ = [
    "GNEWS_BASE_URL",
    "GNEWS_DAILY_BUDGET",
    "GNewsApiKeyMissingError",
    "GNewsClient",
    "GNewsRateLimitError",
    "GNewsUnavailable",
    "NewsArticle",
]
