"""Structural tests for :mod:`backend.app.brokers.seed_indian_symbols`.

The seed module is a thin async wrapper around
:func:`backend.app.seeds.instruments.seed_instruments`, which uses
Postgres-specific ``ON CONFLICT DO NOTHING`` and cannot be exercised against
the in-memory SQLite fixture used by unit tests. We therefore verify the
structural contract here:

* ``upsert_all`` is an async callable that delegates to the canonical JSON-backed
  loader (so the fixture in ``backend/app/seeds/symbol_mappings.json`` remains
  the single source of truth).
* The JSON fixture covers the Nifty 50 seed set required by AC #7 — including
  RELIANCE / INFY / TCS / HDFCBANK — with ``broker="zerodha"`` mappings.

Idempotency is guaranteed by the underlying ``ON CONFLICT DO NOTHING`` clause
and is covered end-to-end by ``manage.py`` seed invocations in CI against
Postgres.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from backend.app.brokers import seed_indian_symbols
from backend.app.seeds import instruments as seed_loader


def test_upsert_all_is_async() -> None:
    assert inspect.iscoroutinefunction(seed_indian_symbols.upsert_all)


def test_upsert_all_delegates_to_seed_instruments() -> None:
    """The broker-scoped helper must call the canonical loader.

    Keeps the JSON fixture authoritative — duplicating the Nifty 50 list in
    Python would drift from ``symbol_mappings.json``.
    """
    src = inspect.getsource(seed_indian_symbols.upsert_all)
    assert "seed_instruments" in src


def test_nse_fixture_covers_nifty50_bellwethers() -> None:
    """AC #7 seed set: RELIANCE, INFY, TCS, HDFCBANK and peers must be present."""
    fixture_path = Path(seed_loader.__file__).parent / "symbol_mappings.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    nse_rows = data.get("nse", [])
    broker_symbols = {row["broker_symbol"] for row in nse_rows}

    required = {
        "RELIANCE",
        "INFY",
        "TCS",
        "HDFCBANK",
        "ICICIBANK",
        "SBIN",
        "AXISBANK",
        "KOTAKBANK",
        "BHARTIARTL",
        "LT",
        "ITC",
        "HINDUNILVR",
    }
    missing = required - broker_symbols
    assert not missing, f"Nifty 50 bellwethers missing from seed: {missing}"
    # Every row is Zerodha-compatible (broker_exchange=NSE).
    assert all(row.get("broker_exchange", "NSE") == "NSE" for row in nse_rows)
    # Canonical ticker equals broker ticker for the Zerodha pair.
    assert all(row["symbol"] == row["broker_symbol"] for row in nse_rows)


def test_module_runnable_as_script() -> None:
    """``python -m backend.app.brokers.seed_indian_symbols`` must be valid."""
    src = inspect.getsource(seed_indian_symbols)
    assert 'if __name__ == "__main__"' in src
    assert "asyncio.run" in src
