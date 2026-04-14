"""SQLAlchemy ORM models.

Importing this package registers every model on ``Base.metadata`` so that
Alembic's ``target_metadata = Base.metadata`` sees all 15 tables for
autogenerate.
"""

from __future__ import annotations

from backend.app.models.ai_analysis_log import AiAnalysisLog
from backend.app.models.audit_log import AuditLog
from backend.app.models.base import Base, TimestampMixin
from backend.app.models.broker_connections import BrokerConnection
from backend.app.models.calendar_overrides import CalendarOverride
from backend.app.models.corporate_actions import CorporateAction
from backend.app.models.device_tokens import DeviceToken
from backend.app.models.fx_rates import FxRate
from backend.app.models.instruments import Instrument
from backend.app.models.notifications import Notification
from backend.app.models.orders import Order
from backend.app.models.positions import Position
from backend.app.models.price_history import PriceHistory
from backend.app.models.recommendations import Recommendation
from backend.app.models.symbol_mappings import SymbolMapping
from backend.app.models.users import User

__all__ = [
    "Base",
    "TimestampMixin",
    "AiAnalysisLog",
    "AuditLog",
    "BrokerConnection",
    "CalendarOverride",
    "CorporateAction",
    "DeviceToken",
    "FxRate",
    "Instrument",
    "Notification",
    "Order",
    "Position",
    "PriceHistory",
    "Recommendation",
    "SymbolMapping",
    "User",
]
