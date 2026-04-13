"""Initial schema — 15 tables + price_history monthly partitions + indexes.

Revision ID: 001_initial
Revises:
Create Date: 2026-04-13

Notes
-----
* Enums are created explicitly so downgrade can drop them cleanly.
* ``price_history`` is created with ``PARTITION BY RANGE (timestamp)`` and three
  forward-looking monthly partitions (current month + 2 ahead). A scheduled job
  in production extends the partition set; dev starts with a small window.
* Audit-log immutability (UPDATE/DELETE trigger + role REVOKE) lives in
  migration ``002_audit_immutability`` so the concern is cleanly separable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Enum definitions (reused below and dropped in downgrade)
_BROKER_ENUM = postgresql.ENUM("alpaca", "zerodha", name="broker_enum", create_type=False)
_BROKER_CONN_STATUS_ENUM = postgresql.ENUM(
    "active", "expired", "revoked", name="broker_conn_status_enum", create_type=False
)
_PLATFORM_ENUM = postgresql.ENUM("ios", "android", name="platform_enum", create_type=False)
_ORDER_SIDE_ENUM = postgresql.ENUM("buy", "sell", name="order_side_enum", create_type=False)
_ORDER_TYPE_ENUM = postgresql.ENUM("market", "limit", name="order_type_enum", create_type=False)
_ORDER_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "submitted",
    "filled",
    "partial",
    "cancelled",
    "rejected",
    name="order_status_enum",
    create_type=False,
)
_CORP_ACTION_TYPE_ENUM = postgresql.ENUM(
    "split", "dividend", "merger", name="corp_action_type_enum", create_type=False
)
_RECOMMENDATION_TYPE_ENUM = postgresql.ENUM(
    "buy", "sell", "hold", name="recommendation_type_enum", create_type=False
)
_RECOMMENDATION_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "accepted",
    "rejected",
    "expired",
    "executed",
    name="recommendation_status_enum",
    create_type=False,
)
_NOTIFICATION_TYPE_ENUM = postgresql.ENUM(
    "recommendation",
    "order_fill",
    "price_alert",
    "system",
    name="notification_type_enum",
    create_type=False,
)
_AI_ANALYSIS_STATUS_ENUM = postgresql.ENUM(
    "success", "error", "timeout", name="ai_analysis_status_enum", create_type=False
)

_ALL_ENUMS = [
    _BROKER_ENUM,
    _BROKER_CONN_STATUS_ENUM,
    _PLATFORM_ENUM,
    _ORDER_SIDE_ENUM,
    _ORDER_TYPE_ENUM,
    _ORDER_STATUS_ENUM,
    _CORP_ACTION_TYPE_ENUM,
    _RECOMMENDATION_TYPE_ENUM,
    _RECOMMENDATION_STATUS_ENUM,
    _NOTIFICATION_TYPE_ENUM,
    _AI_ANALYSIS_STATUS_ENUM,
]


def upgrade() -> None:
    bind = op.get_bind()
    for enum in _ALL_ENUMS:
        enum.create(bind, checkfirst=True)

    # ---- users ----
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en-IN"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ---- instruments ----
    op.create_table(
        "instruments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("asset_class", sa.String(32), nullable=False, server_default="equity"),
        sa.Column("isin", sa.String(12), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("symbol", "exchange", name="uq_instruments_symbol_exchange"),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"])
    op.create_index("ix_instruments_exchange", "instruments", ["exchange"])

    # ---- symbol_mappings ----
    op.create_table(
        "symbol_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "instrument_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("broker", _BROKER_ENUM, nullable=False),
        sa.Column("broker_symbol", sa.String(64), nullable=False),
        sa.Column("broker_exchange", sa.String(16), nullable=True),
        sa.UniqueConstraint(
            "broker", "broker_symbol", "broker_exchange", name="uq_symbol_mappings_broker_triplet"
        ),
    )
    op.create_index("ix_symbol_mappings_instrument_id", "symbol_mappings", ["instrument_id"])

    # ---- broker_connections ----
    op.create_table(
        "broker_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("broker", _BROKER_ENUM, nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("access_token_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("token_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "status",
            _BROKER_CONN_STATUS_ENUM,
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_broker_connections_user_id", "broker_connections", ["user_id"])

    # ---- device_tokens ----
    op.create_table(
        "device_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expo_push_token", sa.String(255), nullable=False, unique=True),
        sa.Column("platform", _PLATFORM_ENUM, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_device_tokens_user_id", "device_tokens", ["user_id"])

    # ---- positions ----
    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "broker_connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("broker_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("avg_cost", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("as_of", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "broker_connection_id", "instrument_id", name="uq_positions_conn_instrument"
        ),
    )
    op.create_index("ix_positions_broker_connection_id", "positions", ["broker_connection_id"])
    op.create_index("ix_positions_instrument_id", "positions", ["instrument_id"])

    # ---- orders ----
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "broker_connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("broker_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("side", _ORDER_SIDE_ENUM, nullable=False),
        sa.Column("order_type", _ORDER_TYPE_ENUM, nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("limit_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("status", _ORDER_STATUS_ENUM, nullable=False, server_default="pending"),
        sa.Column("broker_order_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_orders_broker_connection_id", "orders", ["broker_connection_id"])
    op.create_index("ix_orders_instrument_id", "orders", ["instrument_id"])
    op.create_index("ix_orders_broker_order_id", "orders", ["broker_order_id"])

    # ---- fx_rates ----
    op.create_table(
        "fx_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("quote_currency", sa.String(3), nullable=False),
        sa.Column("rate", sa.Numeric(20, 10), nullable=False),
        sa.Column("as_of", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "base_currency", "quote_currency", "as_of", name="uq_fx_rates_base_quote_asof"
        ),
    )
    op.create_index("ix_fx_rates_as_of", "fx_rates", ["as_of"])

    # ---- corporate_actions ----
    op.create_table(
        "corporate_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "instrument_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_type", _CORP_ACTION_TYPE_ENUM, nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("ratio_or_amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_corporate_actions_instrument_id", "corporate_actions", ["instrument_id"])
    op.create_index("ix_corporate_actions_ex_date", "corporate_actions", ["ex_date"])

    # ---- price_history (PARTITIONED) ----
    op.execute(
        """
        CREATE TABLE price_history (
            instrument_id UUID NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
            timestamp     TIMESTAMPTZ NOT NULL,
            open          NUMERIC(20, 8) NOT NULL,
            high          NUMERIC(20, 8) NOT NULL,
            low           NUMERIC(20, 8) NOT NULL,
            close         NUMERIC(20, 8) NOT NULL,
            volume        BIGINT NOT NULL,
            PRIMARY KEY (instrument_id, timestamp)
        ) PARTITION BY RANGE (timestamp);
        """
    )
    # Create 3 forward-looking monthly partitions (current + 2 ahead)
    now = datetime.now(tz=timezone.utc)
    for i in range(3):
        year = now.year + ((now.month - 1 + i) // 12)
        month = ((now.month - 1 + i) % 12) + 1
        next_year = year + (1 if month == 12 else 0)
        next_month = 1 if month == 12 else month + 1
        part_name = f"price_history_{year:04d}_{month:02d}"
        start = f"{year:04d}-{month:02d}-01"
        end = f"{next_year:04d}-{next_month:02d}-01"
        op.execute(
            f"""
            CREATE TABLE {part_name} PARTITION OF price_history
              FOR VALUES FROM ('{start}') TO ('{end}');
            """
        )

    # ---- recommendations ----
    op.create_table(
        "recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instruments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("recommendation_type", _RECOMMENDATION_TYPE_ENUM, nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "status", _RECOMMENDATION_STATUS_ENUM, nullable=False, server_default="pending"
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_recommendations_user_id", "recommendations", ["user_id"])
    op.create_index("ix_recommendations_instrument_id", "recommendations", ["instrument_id"])

    # ---- notifications ----
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("notification_type", _NOTIFICATION_TYPE_ENUM, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("read_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])

    # ---- calendar_overrides ----
    op.create_table(
        "calendar_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.UniqueConstraint("exchange", "date", name="uq_calendar_overrides_exchange_date"),
    )

    # ---- audit_log (immutability + REVOKE enforced in 002_audit_immutability) ----
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_event_type", "audit_log", ["event_type"])
    op.create_index("ix_audit_log_occurred_at", "audit_log", ["occurred_at"])

    # ---- ai_analysis_log ----
    op.create_table(
        "ai_analysis_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_type", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", _AI_ANALYSIS_STATUS_ENUM, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ai_analysis_log_request_type", "ai_analysis_log", ["request_type"])
    op.create_index("ix_ai_analysis_log_created_at", "ai_analysis_log", ["created_at"])


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("ai_analysis_log")
    op.drop_table("audit_log")
    op.drop_table("calendar_overrides")
    op.drop_table("notifications")
    op.drop_table("recommendations")
    op.execute("DROP TABLE IF EXISTS price_history CASCADE;")
    op.drop_table("corporate_actions")
    op.drop_table("fx_rates")
    op.drop_table("orders")
    op.drop_table("positions")
    op.drop_table("device_tokens")
    op.drop_table("broker_connections")
    op.drop_table("symbol_mappings")
    op.drop_table("instruments")
    op.drop_table("users")

    bind = op.get_bind()
    for enum in reversed(_ALL_ENUMS):
        enum.drop(bind, checkfirst=True)
