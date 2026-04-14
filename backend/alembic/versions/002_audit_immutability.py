"""Enforce audit_log append-only: block UPDATE/DELETE via trigger + role REVOKE.

Revision ID: 002_audit_immutability
Revises: 001_initial
Create Date: 2026-04-13

Two-layer enforcement:

1. ``audit_log_block_mutation`` trigger raises ``audit_log is append-only``
   on any UPDATE or DELETE — applies to *all* roles including superuser,
   preventing accidental writes during dev/test. The trigger is the primary
   integrity gate.

2. Role-level REVOKE on ``investiq_app`` removes UPDATE/DELETE/TRUNCATE
   privileges entirely, so the application role cannot even attempt a
   mutation (permission denied fires before the trigger). ``investiq_app`` is
   created idempotently so this migration works whether or not Docker
   entrypoint pre-provisions the role.

A separate ``investiq_migrator`` role is also created so operators can grant
migration rights without sharing the superuser account.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_audit_immutability"
down_revision: str | Sequence[str] | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Idempotently ensure both roles exist.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'investiq_app') THEN
                CREATE ROLE investiq_app LOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'investiq_migrator') THEN
                CREATE ROLE investiq_migrator LOGIN;
            END IF;
        END $$;
        """
    )

    # 2. Grant the application role normal read/write on all regular tables...
    op.execute(
        """
        GRANT USAGE ON SCHEMA public TO investiq_app, investiq_migrator;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
            TO investiq_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO investiq_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO investiq_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT USAGE, SELECT ON SEQUENCES TO investiq_app;
        """
    )

    # 3. ...but REVOKE everything except INSERT/SELECT on audit_log.
    op.execute(
        """
        REVOKE ALL ON audit_log FROM investiq_app;
        GRANT SELECT, INSERT ON audit_log TO investiq_app;
        """
    )

    # 4. Install the trigger that blocks UPDATE/DELETE regardless of role.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_block_mutation()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only (% attempted)', TG_OP
                USING ERRCODE = 'check_violation';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_block_update
            BEFORE UPDATE ON audit_log
            FOR EACH ROW
            EXECUTE FUNCTION audit_log_block_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_block_delete
            BEFORE DELETE ON audit_log
            FOR EACH ROW
            EXECUTE FUNCTION audit_log_block_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_block_delete ON audit_log;")
    op.execute("DROP TRIGGER IF EXISTS audit_log_block_update ON audit_log;")
    op.execute("DROP FUNCTION IF EXISTS audit_log_block_mutation();")

    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE ON audit_log TO investiq_app;
        """
    )
    # Note: roles are intentionally NOT dropped — other DBs/schemas may rely on them.
