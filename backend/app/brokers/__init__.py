"""Broker abstraction layer.

Provides a unified interface (:class:`BrokerAdapter`) over heterogeneous broker
APIs. Concrete adapters translate broker responses into normalized Pydantic
schemas and surface transport/auth failures as :class:`BrokerAPIError`.
"""

from backend.app.brokers.base import BrokerAdapter, BrokerFeatures
from backend.app.brokers.errors import BrokerAPIError, BrokerErrorCode

__all__ = [
    "BrokerAdapter",
    "BrokerFeatures",
    "BrokerAPIError",
    "BrokerErrorCode",
]
