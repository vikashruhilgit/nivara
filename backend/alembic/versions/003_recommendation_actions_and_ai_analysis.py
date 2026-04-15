"""Extend recommendation_type_enum + ai_analysis_log for MODE 4 shadow mode.

Revision ID: 003_recommendation_actions_and_ai_analysis
Revises: 002_audit_immutability
Create Date: 2026-04-15

Two things change:

1. ``recommendation_type_enum`` gains ``strong_buy`` and ``strong_sell`` so
   the five-action recommendation scheme (AC #2) can be persisted.
2. ``ai_analysis_log`` grows four columns for MODE 4 shadow logging:
   ``shadow_mode``, ``instrument_id``, ``result_json`` (JSONB), and
   ``ai_score`` (Numeric(5,4)).

Postgres quirk: ``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction
block, so we mark this migration non-transactional.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_recommendation_actions_and_ai_analysis"
down_revision: str | Sequence[str] | None = "002_audit_immutability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Required for ALTER TYPE ... ADD VALUE (must run outside a transaction).
transactional_ddl = False


def upgrade() -> None:
    # 1. Extend the enum. ``IF NOT EXISTS`` (Postgres 12+) keeps the
    # migration idempotent even if a prior partial run added one value.
    op.execute("ALTER TYPE recommendation_type_enum ADD VALUE IF NOT EXISTS 'strong_buy'")
    op.execute("ALTER TYPE recommendation_type_enum ADD VALUE IF NOT EXISTS 'strong_sell'")

    # 2. Extend ai_analysis_log. All new columns are nullable / defaulted so
    # the change is online-safe (no rewrite).
    op.add_column(
        "ai_analysis_log",
        sa.Column(
            "shadow_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "ai_analysis_log",
        sa.Column(
            "instrument_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("instruments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "ai_analysis_log",
        sa.Column("result_json", JSONB(), nullable=True),
    )
    op.add_column(
        "ai_analysis_log",
        sa.Column("ai_score", sa.Numeric(5, 4), nullable=True),
    )
    op.create_index(
        "ix_ai_analysis_log_instrument_id",
        "ai_analysis_log",
        ["instrument_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_analysis_log_instrument_id", table_name="ai_analysis_log")
    op.drop_column("ai_analysis_log", "ai_score")
    op.drop_column("ai_analysis_log", "result_json")
    op.drop_column("ai_analysis_log", "instrument_id")
    op.drop_column("ai_analysis_log", "shadow_mode")
    # NOTE: Postgres has no native "DROP VALUE" for enums; the values remain.
    # A full downgrade would require recreating the enum, which we consider
    # out of scope for forward-only dev migrations.
