"""Zerodha conformance tests (M4-22 S6).

Re-runs the same behavioural contract asserted against :class:`AlpacaAdapter`
in :mod:`backend.tests.test_broker_conformance`, but with Zerodha-specific
fixtures (INR currency, XNSE exchange, daily-reauth flag, TokenException /
NetworkException mapping, stale-token preflight).

Deeper unit coverage of Zerodha-specific parsing / merge logic lives in
:mod:`backend.tests.brokers.test_zerodha_unit` — this file is the broker-
agnostic contract suite instantiated for Zerodha.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from backend.app.brokers.errors import BrokerAPIError, BrokerErrorCode
from backend.app.brokers.zerodha import ZerodhaAdapter
from backend.app.schemas.broker import (
    NormalizedBalance,
    NormalizedOrder,
    NormalizedPosition,
)
from kiteconnect.exceptions import NetworkException, TokenException

# --------------------------------------------------------------------- fixtures

_HOLDING: dict[str, Any] = {
    "tradingsymbol": "RELIANCE",
    "exchange": "NSE",
    "quantity": 10,
    "average_price": 2400.50,
    "last_price": 2500.00,
    "pnl": 995.00,
}

_NET_POSITION: dict[str, Any] = {
    "tradingsymbol": "TCS",
    "exchange": "NSE",
    "quantity": 5,
    "average_price": 3500.00,
    "last_price": 3600.00,
    "pnl": 500.00,
    "value": 18000.00,
}

_MARGINS: dict[str, Any] = {
    "available": {"cash": "15000.00"},
    "utilised": {"debits": "500.00"},
    "net": "14500.00",
    "account_id": "ZD1234",
}

_ORDER_FILLED: dict[str, Any] = {
    "order_id": "zo-1",
    "tradingsymbol": "RELIANCE",
    "exchange": "NSE",
    "transaction_type": "BUY",
    "order_type": "MARKET",
    "quantity": 10,
    "filled_quantity": 10,
    "price": 0,
    "trigger_price": 0,
    "status": "COMPLETE",
    "order_timestamp": datetime(2026, 4, 15, 9, 30, tzinfo=UTC),
    "exchange_update_timestamp": datetime(2026, 4, 15, 9, 30, 1, tzinfo=UTC),
}

_ORDER_OPEN: dict[str, Any] = {
    "order_id": "zo-2",
    "tradingsymbol": "TCS",
    "exchange": "NSE",
    "transaction_type": "SELL",
    "order_type": "LIMIT",
    "quantity": 5,
    "filled_quantity": 0,
    "price": 3700.00,
    "trigger_price": 0,
    "status": "OPEN",
    "order_timestamp": datetime(2026, 4, 15, 10, 0, tzinfo=UTC),
}

_ORDER_CANCELLED: dict[str, Any] = {
    "order_id": "zo-3",
    "tradingsymbol": "INFY",
    "exchange": "NSE",
    "transaction_type": "BUY",
    "order_type": "LIMIT",
    "quantity": 3,
    "filled_quantity": 0,
    "price": 1400.00,
    "trigger_price": 0,
    "status": "CANCELLED",
    "order_timestamp": datetime(2026, 4, 15, 10, 5, tzinfo=UTC),
}

_ORDER_REJECTED: dict[str, Any] = {
    "order_id": "zo-4",
    "tradingsymbol": "HDFC",
    "exchange": "NSE",
    "transaction_type": "BUY",
    "order_type": "MARKET",
    "quantity": 1,
    "filled_quantity": 0,
    "price": 0,
    "trigger_price": 0,
    "status": "REJECTED",
    "order_timestamp": datetime(2026, 4, 15, 10, 10, tzinfo=UTC),
}


def _populated_kite() -> MagicMock:
    """A MagicMock KiteConnect seeded with realistic Kite v3 responses."""
    kite = MagicMock()
    kite.holdings.return_value = [_HOLDING]
    kite.positions.return_value = {"net": [_NET_POSITION], "day": []}
    kite.margins.return_value = _MARGINS
    kite.orders.return_value = [
        _ORDER_FILLED,
        _ORDER_OPEN,
        _ORDER_CANCELLED,
        _ORDER_REJECTED,
    ]
    return kite


def _adapter(kite: MagicMock | None = None) -> ZerodhaAdapter:
    return ZerodhaAdapter(
        api_key="k",
        api_secret="s",
        access_token="tok",
        kite_client=kite if kite is not None else _populated_kite(),
    )


# --------------------------------------------------------------------- features


async def test_features_shape_and_zerodha_specific_flags() -> None:
    """All BrokerFeatures fields are present; Zerodha-specific flags assert expected values.

    Zerodha differs from Alpaca:
      - supports_oauth=True (shared with Alpaca but required here)
      - requires_daily_reauth=True (Alpaca=False — daily 06:00 IST token cutoff)
      - supports_realtime_streaming=True (Alpaca=False in our adapter today)
      - supports_paper_trading=False (Alpaca=True)
    """
    f = _adapter().features
    # Full field coverage (no AttributeError).
    for attr in (
        "supports_positions",
        "supports_balances",
        "supports_orders",
        "supports_place_order",
        "supports_oauth",
        "supports_realtime_streaming",
        "supports_paper_trading",
        "requires_daily_reauth",
    ):
        assert isinstance(getattr(f, attr), bool)

    assert f.supports_positions is True
    assert f.supports_balances is True
    assert f.supports_orders is True
    assert f.supports_place_order is False
    assert f.supports_oauth is True
    assert f.requires_daily_reauth is True
    assert f.supports_realtime_streaming is True
    assert f.supports_paper_trading is False


# --------------------------------------------------------------------- get_positions


async def test_get_positions_returns_list_of_normalized_positions() -> None:
    positions = await _adapter().get_positions()
    assert isinstance(positions, list)
    assert len(positions) == 2
    for p in positions:
        assert isinstance(p, NormalizedPosition)
        assert isinstance(p.broker_symbol, str) and p.broker_symbol
        assert isinstance(p.quantity, Decimal)
        assert isinstance(p.avg_entry_price, Decimal)
        assert isinstance(p.market_value, Decimal)
        assert isinstance(p.unrealized_pl, Decimal)
        # INR currency is part of the Zerodha-specific contract.
        assert p.currency == "INR"


# --------------------------------------------------------------------- get_balances


async def test_get_balances_returns_inr_snapshot() -> None:
    bal = await _adapter().get_balances()
    assert isinstance(bal, NormalizedBalance)
    assert bal.currency == "INR"
    assert isinstance(bal.cash, Decimal)
    assert isinstance(bal.equity, Decimal)
    assert bal.account_id == "ZD1234"


# --------------------------------------------------------------------- get_orders


async def test_get_orders_returns_enum_statuses_never_raw_zerodha_strings() -> None:
    allowed = {
        "new",
        "partially_filled",
        "filled",
        "canceled",
        "rejected",
        "expired",
        "pending",
    }
    orders = await _adapter().get_orders()
    assert len(orders) == 4
    for o in orders:
        assert isinstance(o, NormalizedOrder)
        assert o.status in allowed
        # Ensure no raw Zerodha strings leak through.
        assert o.status not in {"COMPLETE", "CANCELLED", "REJECTED", "TRIGGER PENDING", "OPEN"}


async def test_get_orders_open_only_filters_completed_cancelled_rejected() -> None:
    orders = await _adapter().get_orders(open_only=True)
    # Only the OPEN order survives the filter (COMPLETE, CANCELLED, REJECTED drop).
    assert len(orders) == 1
    assert orders[0].broker_order_id == "zo-2"
    assert orders[0].status == "new"


# --------------------------------------------------------------------- place_order


async def test_place_order_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        await _adapter().place_order(
            broker_symbol="RELIANCE",
            side="buy",
            quantity=1.0,
            idempotency_key="k",
        )


# --------------------------------------------------------------------- normalize_symbol


def test_normalize_symbol_is_sync_passthrough_uppercase() -> None:
    # Behavioural contract: sync (not coroutine), string-in / string-out.
    adapter = _adapter()
    result = adapter.normalize_symbol("RELIANCE")
    assert isinstance(result, str)
    assert result == "RELIANCE"
    # Whitespace + lowercase normalised.
    assert adapter.normalize_symbol("  reliance  ") == "RELIANCE"


# --------------------------------------------------------------------- resolve_canonical


def test_resolve_canonical_fallback_without_mapper() -> None:
    """Without injected mapper, NSE → XNSE; tradingsymbol passed through uppercased."""
    adapter = _adapter()
    assert adapter.symbol_mapper is None
    assert adapter.resolve_canonical("RELIANCE", "NSE") == ("RELIANCE", "XNSE")


def test_resolve_canonical_with_injected_mapper() -> None:
    """With injected mapper (e.g. SymbolMappingService), delegate to it."""
    calls: list[tuple[str, str | None]] = []

    def mapper(bs: str, ex: str | None) -> tuple[str, str]:
        calls.append((bs, ex))
        return ("RELIANCE", "XNSE")

    adapter = _adapter()
    adapter.symbol_mapper = mapper
    assert adapter.resolve_canonical("RELIANCE", "NSE") == ("RELIANCE", "XNSE")
    assert calls == [("RELIANCE", "NSE")]


# --------------------------------------------------------------------- error mapping


async def test_token_exception_maps_to_auth_expired() -> None:
    kite = _populated_kite()
    kite.holdings.side_effect = TokenException("token expired")
    with pytest.raises(BrokerAPIError) as excinfo:
        await _adapter(kite).get_positions()
    assert excinfo.value.code == BrokerErrorCode.AUTH_EXPIRED
    assert excinfo.value.broker == "zerodha"


async def test_network_exception_maps_to_network_timeout() -> None:
    kite = _populated_kite()
    kite.margins.side_effect = NetworkException("connection reset")
    with pytest.raises(BrokerAPIError) as excinfo:
        await _adapter(kite).get_balances()
    assert excinfo.value.code == BrokerErrorCode.NETWORK_TIMEOUT
    assert excinfo.value.broker == "zerodha"


# --------------------------------------------------------------------- token preflight


async def test_stale_access_token_issued_at_raises_auth_expired_without_network() -> None:
    """Token issued before most recent 06:00 IST cutoff surfaces AUTH_EXPIRED preemptively."""
    ist = ZoneInfo("Asia/Kolkata")
    # Yesterday 05:00 IST — strictly before today's 06:00 IST cutoff regardless of now.
    stale_ist = datetime.now(ist).replace(hour=5, minute=0, second=0, microsecond=0) - timedelta(
        days=1
    )
    stale_issued_at = stale_ist.astimezone(UTC)

    kite = _populated_kite()
    adapter = ZerodhaAdapter(
        api_key="k",
        api_secret="s",
        access_token="tok",
        access_token_issued_at=stale_issued_at,
        kite_client=kite,
    )
    with pytest.raises(BrokerAPIError) as excinfo:
        await adapter.get_positions()
    assert excinfo.value.code == BrokerErrorCode.AUTH_EXPIRED
    assert excinfo.value.broker == "zerodha"
    # Preflight short-circuits before any Kite call.
    kite.holdings.assert_not_called()
    kite.positions.assert_not_called()


# --------------------------------------------------------------------- Alpaca/Zerodha divergences (documented)


@pytest.mark.xfail(
    reason="Zerodha place_order is intentionally post-MVP (NotImplementedError); "
    "documents divergence from a hypothetical broker that supports write path.",
    strict=True,
    raises=NotImplementedError,
)
async def test_place_order_write_path_divergence() -> None:
    """Contract divergence marker: Zerodha does NOT support place_order at MVP.

    Xfail(strict) here documents the asymmetry rather than silently skipping —
    if Zerodha ever ships a write path, this test will XPASS and the marker
    must be removed, forcing a conscious decision.
    """
    await _adapter().place_order(
        broker_symbol="RELIANCE",
        side="buy",
        quantity=1.0,
        idempotency_key="k",
    )
