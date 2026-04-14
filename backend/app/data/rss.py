"""RSS fallback for news fetching when GNews is unavailable.

Used by the sentiment pipeline only when
:class:`backend.app.data.gnews.GNewsClient` raises
:class:`backend.app.data.gnews.GNewsRateLimitError` or
:class:`backend.app.data.gnews.GNewsApiKeyMissingError`.

We fetch well-known free RSS feeds (Yahoo Finance, CNBC world business) and
project them onto the same :class:`~backend.app.data.gnews.NewsArticle`
schema so downstream scoring code is source-agnostic.

``feedparser`` parses are CPU-bound; we wrap them in ``asyncio.to_thread`` to
keep the async contract.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
from backend.app.data.gnews import NewsArticle

if TYPE_CHECKING:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0

# Generic feeds that cover markets / equities news. Symbol-specific feeds
# (Yahoo's per-ticker RSS) are requested on demand.
DEFAULT_FEEDS: tuple[str, ...] = ("https://finance.yahoo.com/news/rssindex",)


def _yahoo_symbol_feed(symbol: str) -> str:
    # Yahoo per-ticker RSS (public, unauthenticated).
    return f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"


def _parse_feed(text: str) -> list[dict[str, Any]]:
    """Parse an RSS/Atom feed string into a list of plain dict entries.

    ``feedparser`` is an optional dependency — when it is missing we return
    an empty list and log a warning so the caller degrades to the
    (already-handled) no-news path rather than exploding.
    """
    try:
        import feedparser
    except ImportError:
        logger.warning(
            "feedparser not installed; RSS fallback returns empty. "
            "Install with: pip install feedparser"
        )
        return []

    parsed = feedparser.parse(text)
    entries: list[dict[str, Any]] = []
    for entry in parsed.entries or []:
        entries.append(
            {
                "title": getattr(entry, "title", "") or "",
                "link": getattr(entry, "link", "") or "",
                "summary": getattr(entry, "summary", "") or "",
                "published_parsed": getattr(entry, "published_parsed", None),
                "source": getattr(getattr(parsed, "feed", None), "title", None) or "rss",
            }
        )
    return entries


def _entry_to_article(entry: dict[str, Any]) -> NewsArticle | None:
    title = entry.get("title") or ""
    link = entry.get("link") or ""
    if not title or not link:
        return None
    published_parsed = entry.get("published_parsed")
    if published_parsed is not None:
        try:
            published_at = datetime(
                *published_parsed[:6],  # type: ignore[misc]
                tzinfo=UTC,
            )
        except (TypeError, ValueError):
            published_at = datetime.now(tz=UTC)
    else:
        published_at = datetime.now(tz=UTC)
    return NewsArticle(
        title=str(title),
        source=str(entry.get("source") or "rss"),
        url=str(link),
        published_at=published_at,
        summary=str(entry.get("summary") or ""),
    )


class RssFallbackClient:
    """Fetches generic or symbol-specific RSS feeds as a news fallback."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        feeds: tuple[str, ...] = DEFAULT_FEEDS,
    ) -> None:
        self._client = client
        self._timeout = timeout
        self._feeds = feeds

    async def fetch_for_symbol(self, symbol: str, *, max_results: int = 10) -> list[NewsArticle]:
        """Fetch per-symbol Yahoo RSS + the generic feeds, merged + deduped."""
        urls = [_yahoo_symbol_feed(symbol.upper()), *self._feeds]
        articles: list[NewsArticle] = []
        for url in urls:
            try:
                text = await self._fetch_text(url)
            except httpx.HTTPError as exc:
                logger.warning("RSS fetch failed for %s: %s", url, exc)
                continue
            entries = await asyncio.to_thread(_parse_feed, text)
            for entry in entries:
                article = _entry_to_article(entry)
                if article is not None:
                    articles.append(article)
        # Dedup by URL, preserve order, cap at max_results.
        seen: set[str] = set()
        deduped: list[NewsArticle] = []
        for article in articles:
            if article.url in seen:
                continue
            seen.add(article.url)
            deduped.append(article)
            if len(deduped) >= max_results:
                break
        return deduped

    async def _fetch_text(self, url: str) -> str:
        if self._client is not None:
            resp = await self._client.get(url, timeout=self._timeout)
            resp.raise_for_status()
            return resp.text
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text


__all__ = [
    "DEFAULT_FEEDS",
    "RssFallbackClient",
]
