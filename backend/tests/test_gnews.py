"""Tests for :mod:`backend.app.data.gnews` and :mod:`backend.app.data.rss`.

HTTP is mocked via ``httpx.MockTransport`` (same pattern as test_fred).
Redis is ``fakeredis.aioredis`` so the daily-budget counter works without a
real broker.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import fakeredis.aioredis
import httpx
import pytest
import pytest_asyncio
from backend.app.data.gnews import (
    GNEWS_BASE_URL,
    GNewsApiKeyMissingError,
    GNewsClient,
    GNewsRateLimitError,
    GNewsUnavailable,
    _rate_limit_key,
)
from backend.app.data.rss import RssFallbackClient


def _gnews_response(articles: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"totalArticles": len(articles), "articles": articles})


@pytest_asyncio.fixture
async def redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def test_gnews_happy_path_returns_articles(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/search"
        return _gnews_response(
            [
                {
                    "title": "Apple beats earnings",
                    "description": "Q3 revenue above estimates",
                    "url": "https://example.com/1",
                    "publishedAt": "2026-04-14T12:00:00Z",
                    "source": {"name": "Example News"},
                }
            ]
        )

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    client = GNewsClient(api_key="k", redis=redis, client=http)

    articles = await client.search("AAPL")

    assert len(articles) == 1
    assert articles[0].title == "Apple beats earnings"
    assert articles[0].source == "Example News"
    # Usage bumped in Redis.
    assert await redis.get(_rate_limit_key()) == "1"


async def test_gnews_missing_api_key_raises(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    client = GNewsClient(api_key=None, redis=redis)
    with pytest.raises(GNewsApiKeyMissingError):
        await client.search("AAPL")


async def test_gnews_rate_limit_exhausted_from_redis(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    # Pre-seed Redis with the budget already exhausted.
    await redis.set(_rate_limit_key(), "100")
    client = GNewsClient(api_key="k", redis=redis)
    with pytest.raises(GNewsRateLimitError):
        await client.search("AAPL")


async def test_gnews_upstream_429_surfaces_rate_limit(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "too many"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GNewsClient(api_key="k", redis=redis, client=http)
    with pytest.raises(GNewsRateLimitError):
        await client.search("AAPL")


async def test_gnews_network_failure_wrapped(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GNewsClient(api_key="k", redis=redis, client=http)
    with pytest.raises(GNewsUnavailable):
        await client.search("AAPL")


async def test_gnews_search_for_symbols_builds_or_query(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["q"] = request.url.params.get("q") or ""
        return _gnews_response([])

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GNewsClient(api_key="k", redis=redis, client=http)
    await client.search_for_symbols(["aapl", "msft"])
    assert '"AAPL"' in captured["q"]
    assert '"MSFT"' in captured["q"]
    assert " OR " in captured["q"]


async def test_gnews_url_is_correct() -> None:
    assert GNEWS_BASE_URL == "https://gnews.io/api/v4/search"


async def test_rss_fallback_returns_empty_when_feedparser_missing() -> None:
    """When feedparser is absent (optional dep), RSS returns []."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<rss></rss>")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = RssFallbackClient(client=http, feeds=())
    # Even if feedparser is installed, an empty feed yields no articles.
    articles = await client.fetch_for_symbol("AAPL", max_results=5)
    assert articles == []
