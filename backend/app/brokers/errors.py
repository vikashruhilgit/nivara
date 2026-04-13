"""Broker error hierarchy with enumerated codes.

All broker-level failures (transport, auth, rate-limit, unknown instrument,
upstream outage, timeout) are raised as :class:`BrokerAPIError` with a
well-known :class:`BrokerErrorCode`. This lets upstream code (portfolio sync,
recommendation engine) implement uniform retry / escalation policies.
"""

from __future__ import annotations

from enum import StrEnum


class BrokerErrorCode(StrEnum):
    """Enumerated, transport-independent broker error codes.

    Callers should pattern-match on these codes rather than string-matching on
    ``str(exc)`` — broker SDK error messages drift across versions.
    """

    AUTH_EXPIRED = "AUTH_EXPIRED"
    """Access / refresh token rejected. Requires re-auth (OAuth redirect)."""

    RATE_LIMITED = "RATE_LIMITED"
    """Broker returned 429 or equivalent. Back off and retry."""

    INSTRUMENT_UNKNOWN = "INSTRUMENT_UNKNOWN"
    """Symbol / instrument not recognized by the broker."""

    UPSTREAM_DOWN = "UPSTREAM_DOWN"
    """Broker returned 5xx / service unavailable."""

    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    """Transport-level timeout talking to the broker."""


class BrokerAPIError(Exception):
    """Uniform exception type raised by :class:`BrokerAdapter` implementations."""

    def __init__(
        self,
        code: BrokerErrorCode,
        message: str,
        *,
        broker: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.broker = broker
        self.status_code = status_code
        super().__init__(f"[{code.value}] {message}")

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"BrokerAPIError(code={self.code.value!r}, broker={self.broker!r}, "
            f"status_code={self.status_code!r}, message={self.message!r})"
        )
