"""Reddit social-sentiment client (PRAW wrapper) with graceful degradation.

Social sentiment is the smallest leg of the composite (20% weight), and the
brief is explicit that Reddit must be *degradable*: if credentials are
missing, the SDK isn't installed, or the API returns errors, the sentiment
engine must redistribute weight to news + macro rather than fail the request.

This module isolates that contract in two ways:

1. ``praw`` is imported lazily inside :meth:`RedditClient.fetch_posts`. That
   keeps the module import-time dependency surface empty — you can run the
   whole test suite without installing ``praw``.
2. Any failure (missing creds, missing SDK, auth error, network error) is
   wrapped in :class:`RedditUnavailable` so the scoring engine has a single
   exception type to catch.

Subreddits searched by default track the MVP's target markets:

* ``r/stocks`` — general US equities discussion
* ``r/wallstreetbets`` — high-volume US retail sentiment
* ``r/IndianStreetBets`` — Indian equities retail sentiment

PRAW is synchronous; we run calls via :func:`asyncio.to_thread` to preserve
our async contract across the data layer.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_SUBREDDITS: tuple[str, ...] = ("stocks", "wallstreetbets", "IndianStreetBets")
DEFAULT_USER_AGENT = "investiq-sentiment/0.1 (by /u/investiq_bot)"


class RedditUnavailable(Exception):
    """Reddit cannot be queried (missing creds, SDK, network, auth error).

    The sentiment engine catches this and redistributes the 20% social
    weight across news and macro per AC #3.
    """


class RedditPost(BaseModel):
    """A single Reddit submission or comment projected onto a stable schema."""

    title: str
    body: str
    score: int
    created_at: datetime
    subreddit: str
    url: str


class RedditClient:
    """Thin async wrapper over PRAW's synchronous API.

    Construction never touches the network. All credential / SDK checks
    happen lazily on the first :meth:`fetch_posts` call so tests that mock
    the client never pay the import cost.
    """

    def __init__(
        self,
        *,
        client_id: str | None,
        client_secret: str | None,
        user_agent: str = DEFAULT_USER_AGENT,
        subreddits: tuple[str, ...] = DEFAULT_SUBREDDITS,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._subreddits = subreddits
        self._reddit: Any | None = None  # Lazy-instantiated praw.Reddit.

    def _build_reddit(self) -> Any:
        """Instantiate ``praw.Reddit`` on demand. Raises :class:`RedditUnavailable`."""
        if not self._client_id or not self._client_secret:
            raise RedditUnavailable("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not configured")
        try:
            import praw
        except ImportError as exc:
            raise RedditUnavailable(
                "praw is not installed; run `pip install praw` to enable Reddit sentiment"
            ) from exc
        try:
            return praw.Reddit(
                client_id=self._client_id,
                client_secret=self._client_secret,
                user_agent=self._user_agent,
                check_for_async=False,
            )
        except Exception as exc:  # praw wraps auth errors broadly
            raise RedditUnavailable(f"praw auth failed: {exc}") from exc

    async def fetch_posts(
        self,
        symbol: str,
        *,
        limit: int = 50,
    ) -> list[RedditPost]:
        """Search configured subreddits for ``symbol``, returning up to ``limit`` posts.

        Raises
        ------
        RedditUnavailable
            When creds are missing, PRAW is uninstalled, or auth fails.
        """
        if self._reddit is None:
            self._reddit = await asyncio.to_thread(self._build_reddit)

        reddit_obj = self._reddit
        assert reddit_obj is not None  # mypy narrow; set above

        def _search_all() -> list[RedditPost]:
            # PRAW's search methods are sync generators; materialise inside the
            # thread so we never leak a non-awaitable back to the event loop.
            out: list[RedditPost] = []
            per_sub_limit = max(limit // max(len(self._subreddits), 1), 1)
            for sub_name in self._subreddits:
                try:
                    subreddit = reddit_obj.subreddit(sub_name)
                    for submission in subreddit.search(symbol, limit=per_sub_limit, sort="new"):
                        post = _submission_to_post(submission, sub_name)
                        if post is not None:
                            out.append(post)
                except Exception as exc:  # noqa: BLE001
                    # Per-subreddit failure shouldn't nuke the whole fetch;
                    # log and continue. If *all* subs fail, caller sees [].
                    logger.warning("reddit search failed in r/%s: %s", sub_name, exc)
                    continue
            return out[:limit]

        try:
            return await asyncio.to_thread(_search_all)
        except RedditUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RedditUnavailable(f"reddit fetch failed: {exc}") from exc


def _submission_to_post(submission: Any, subreddit_name: str) -> RedditPost | None:
    """Project a PRAW Submission onto the stable :class:`RedditPost` schema.

    Anything missing or malformed returns ``None`` so the caller can skip it.
    """
    try:
        title = str(getattr(submission, "title", "") or "")
        body = str(getattr(submission, "selftext", "") or "")
        score = int(getattr(submission, "score", 0) or 0)
        created_utc = getattr(submission, "created_utc", None)
        if created_utc is None:
            return None
        created_at = datetime.fromtimestamp(float(created_utc), tz=UTC)
        url = str(getattr(submission, "url", "") or "")
        if not title:
            return None
        return RedditPost(
            title=title,
            body=body,
            score=score,
            created_at=created_at,
            subreddit=subreddit_name,
            url=url,
        )
    except (TypeError, ValueError, AttributeError) as exc:
        logger.debug("skipping malformed reddit submission: %s", exc)
        return None


__all__ = [
    "DEFAULT_SUBREDDITS",
    "RedditClient",
    "RedditPost",
    "RedditUnavailable",
]
