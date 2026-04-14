"""Market data provider layer.

The :mod:`backend.app.data` package exposes an abstract :class:`DataProvider`
interface plus concrete implementations (Yahoo Finance for MVP; Polygon.io as
the planned escape hatch per TechSpec v1.3 §9). All consumers depend only on
the abstract base so the underlying provider can be swapped without touching
the analysis engine.
"""

from backend.app.data.base import (
    DataProvider,
    Fundamentals,
    OHLCVBar,
    Quote,
)
from backend.app.data.errors import (
    DataProviderError,
    RateLimitError,
    SymbolNotFoundError,
    UpstreamUnavailableError,
)

__all__ = [
    "DataProvider",
    "DataProviderError",
    "Fundamentals",
    "OHLCVBar",
    "Quote",
    "RateLimitError",
    "SymbolNotFoundError",
    "UpstreamUnavailableError",
]
