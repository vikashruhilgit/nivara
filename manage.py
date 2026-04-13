#!/usr/bin/env python3
"""InvestIQ management CLI.

Usage
-----
    python manage.py db upgrade        # alembic upgrade head
    python manage.py db downgrade N    # alembic downgrade N
    python manage.py db current        # show current revision
    python manage.py seed              # populate instruments + symbol_mappings
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.config import get_settings

app = typer.Typer(help="InvestIQ backend management CLI.", no_args_is_help=True)
db_app = typer.Typer(help="Database / Alembic operations.", no_args_is_help=True)
app.add_typer(db_app, name="db")

_ROOT = Path(__file__).resolve().parent
_ALEMBIC_INI = _ROOT / "alembic.ini"


def _alembic_config() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    # Override sqlalchemy.url at runtime from Settings (overrides empty value in alembic.ini)
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


@db_app.command("upgrade")
def db_upgrade(revision: str = "head") -> None:
    """Apply migrations up to REVISION (default: head)."""
    command.upgrade(_alembic_config(), revision)
    typer.echo(f"DB upgraded to {revision}.")


@db_app.command("downgrade")
def db_downgrade(revision: str) -> None:
    """Downgrade to REVISION (e.g. '-1', 'base', '001_initial')."""
    command.downgrade(_alembic_config(), revision)
    typer.echo(f"DB downgraded to {revision}.")


@db_app.command("current")
def db_current() -> None:
    """Print current DB revision."""
    command.current(_alembic_config())


@db_app.command("revision")
def db_revision(message: str, autogenerate: bool = True) -> None:
    """Create a new revision. Use --no-autogenerate for empty templates."""
    command.revision(_alembic_config(), message=message, autogenerate=autogenerate)


@app.command("seed")
def seed() -> None:
    """Populate instruments + symbol_mappings with top 50 NSE + S&P 500 fixtures.

    Idempotent: safe to re-run. Relies on UNIQUE constraints for conflict-skip.
    """

    async def _run() -> None:
        # Local import: avoids importing seed module (and its heavy deps) at CLI startup
        from backend.app.seeds.instruments import seed_instruments

        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                counts = await seed_instruments(session)
        finally:
            await engine.dispose()
        typer.echo(
            f"Seed complete: {counts['instruments_inserted']} instruments, "
            f"{counts['mappings_inserted']} symbol mappings inserted."
        )

    asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(app() or 0)
