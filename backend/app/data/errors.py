"""Exception hierarchy for the DataProvider layer.

All provider-facing errors inherit from :class:`DataProviderError`. Consumers
should catch the base class to remain provider-agnostic; subclasses exist for
retry/backoff decisions.
"""

from __future__ import annotations


class DataProviderError(Exception):
    """Base error raised by any :class:`backend.app.data.DataProvider`.

    The ``provider`` attribute names the concrete implementation (e.g.
    ``"yahoo"``) so callers can log / alert without introspecting ``type()``.
    """

    def __init__(self, message: str, *, provider: str = "unknown") -> None:
        super().__init__(message)
        self.provider = provider
        self.message = message


class SymbolNotFoundError(DataProviderError):
    """The requested symbol is not known to the upstream provider.

    Non-retryable; caller should surface a 404-equivalent to its own users.
    """


class RateLimitError(DataProviderError):
    """The provider rejected the request due to rate limiting.

    Retryable with backoff. ``retry_after_seconds`` is a best-effort hint
    (Yahoo does not send ``Retry-After``; yfinance surfaces no structured info,
    so this defaults to ``None`` and callers should use exponential backoff).
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str = "unknown",
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.retry_after_seconds = retry_after_seconds


class UpstreamUnavailableError(DataProviderError):
    """The upstream provider is unreachable or returned an empty/invalid payload.

    Retryable. Distinct from :class:`RateLimitError` to allow different backoff
    policies (e.g., circuit-breaker on sustained unavailability).
    """
