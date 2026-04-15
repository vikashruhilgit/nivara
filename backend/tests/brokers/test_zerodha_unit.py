"""Unit tests for :class:`backend.app.brokers.zerodha.ZerodhaAdapter`.

The real ``kiteconnect.KiteConnect`` client is swapped for a :class:`MagicMock`
that returns fixture dicts shaped like actual Kite Connect v3 responses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from backend.app.brokers.errors import BrokerAPIError, BrokerErrorCode
from backend.app.brokers.zerodha import ZerodhaAdapter
from kiteconnect.exceptions import InputException, NetworkException, TokenException

# --------------------------------------------------------------------- fixtures


def _make_adapter(kite: MagicMock) -> ZerodhaAdapter:
    return ZerodhaAdapter(
        api_key="test_key",
        api_secret="test_secret",
        access_token="test_token",
        kite_client=kite,
    )


_HOLDING_RELIANCE = {
    "tradingsymbol": "RELIANCE",
    "exchange": "NSE",
    "quantity": 10,
    "average_price": 2400.50,
    "last_price": 2500.00,
    "pnl": 995.00,
}

_NET_POSITION_TCS = {
    "tradingsymbol": "TCS",
    "exchange": "NSE",
    "quantity": 5,
    "average_price": 3500.00,
    "last_price": 3600.00,
    "pnl": 500.00,
    "value": 18000.00,
}

_NET_POSITION_RELIANCE_DUPE = {
    "tradingsymbol": "RELIANCE",
    "exchange": "NSE",
    "quantity": 2,
    "average_price": 2550.00,
    "last_price": 2500.00,
    "pnl": -100.00,
}

_NET_POSITION_FLAT = {
    "tradingsymbol": "INFY",
    "exchange": "NSE",
    "quantity": 0,
    "average_price": 0,
    "last_price": 1500.00,
    "pnl": 0,
}

_MARGINS_EQUITY = {
    "available": {"cash": "15000.00", "live_balance": "15000.00"},
    "utilised": {"debits": "500.00"},
    "net": "14500.00",
    "account_id": "ZD1234",
}

_ORDER_COMPLETE = {
    "order_id": "220901000123456",
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

_ORDER_OPEN = {
    "order_id": "220901000123457",
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

_ORDER_CANCELLED = {
    "order_id": "220901000123458",
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

_ORDER_REJECTED = {
    "order_id": "220901000123459",
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

_ORDER_TRIGGER_PENDING = {
    "order_id": "220901000123460",
    "tradingsymbol": "WIPRO",
    "exchange": "NSE",
    "transaction_type": "SELL",
    "order_type": "SL",
    "quantity": 2,
    "filled_quantity": 0,
    "price": 450.00,
    "trigger_price": 455.00,
    "status": "TRIGGER PENDING",
    "order_timestamp": datetime(2026, 4, 15, 10, 15, tzinfo=UTC),
}


# --------------------------------------------------------------------- get_positions


async def test_get_positions_merges_holdings_and_net_dedupes_by_symbol_exchange() -> None:
    kite = MagicMock()
    kite.holdings.return_value = [_HOLDING_RELIANCE]
    kite.positions.return_value = {
        "net": [_NET_POSITION_TCS, _NET_POSITION_RELIANCE_DUPE, _NET_POSITION_FLAT],
        "day": [],
    }
    adapter = _make_adapter(kite)

    positions = await adapter.get_positions()

    # Holdings (RELIANCE) + one new net (TCS); dupe RELIANCE dropped; flat INFY skipped.
    assert len(positions) == 2
    by_symbol = {p.broker_symbol: p for p in positions}
    assert "RELIANCE" in by_symbol
    assert "TCS" in by_symbol
    assert "INFY" not in by_symbol

    rel = by_symbol["RELIANCE"]
    # Holdings row wins: avg 2400.50, not 2550.00 from the net position.
    assert rel.avg_entry_price == Decimal("2400.5")
    assert rel.quantity == Decimal("10")
    assert rel.currency == "INR"
    assert rel.exchange == "NSE"

    tcs = by_symbol["TCS"]
    assert tcs.quantity == Decimal("5")
    assert tcs.market_value == Decimal("18000.0")
    assert tcs.currency == "INR"


async def test_get_positions_empty() -> None:
    kite = MagicMock()
    kite.holdings.return_value = []
    kite.positions.return_value = {"net": [], "day": []}
    adapter = _make_adapter(kite)

    assert await adapter.get_positions() == []


# --------------------------------------------------------------------- get_balances


async def test_get_balances_returns_inr_snapshot() -> None:
    kite = MagicMock()
    kite.margins.return_value = _MARGINS_EQUITY
    adapter = _make_adapter(kite)

    bal = await adapter.get_balances()

    kite.margins.assert_called_once_with("equity")
    assert bal.currency == "INR"
    assert bal.cash == Decimal("15000.00")
    assert bal.equity == Decimal("14500.00")
    assert bal.account_id == "ZD1234"


async def test_get_balances_falls_back_without_net_field() -> None:
    kite = MagicMock()
    kite.margins.return_value = {
        "available": {"cash": "1000.00"},
        "utilised": {"debits": "200.00"},
    }
    adapter = _make_adapter(kite)

    bal = await adapter.get_balances()
    assert bal.cash == Decimal("1000.00")
    assert bal.equity == Decimal("800.00")
    assert bal.currency == "INR"


# --------------------------------------------------------------------- get_orders


async def test_get_orders_maps_all_statuses() -> None:
    kite = MagicMock()
    kite.orders.return_value = [
        _ORDER_COMPLETE,
        _ORDER_OPEN,
        _ORDER_CANCELLED,
        _ORDER_REJECTED,
        _ORDER_TRIGGER_PENDING,
    ]
    adapter = _make_adapter(kite)

    orders = await adapter.get_orders()

    assert len(orders) == 5
    by_id = {o.broker_order_id: o for o in orders}
    assert by_id["220901000123456"].status == "filled"
    assert by_id["220901000123457"].status == "new"
    assert by_id["220901000123458"].status == "canceled"
    assert by_id["220901000123459"].status == "rejected"
    assert by_id["220901000123460"].status == "new"

    # Side + type mapping sanity.
    assert by_id["220901000123456"].side == "buy"
    assert by_id["220901000123456"].order_type == "market"
    assert by_id["220901000123457"].side == "sell"
    assert by_id["220901000123457"].order_type == "limit"
    assert by_id["220901000123457"].limit_price == Decimal("3700.0")
    assert by_id["220901000123460"].order_type == "stop_limit"
    assert by_id["220901000123460"].stop_price == Decimal("455.0")

    # Currency is INR across the board.
    assert all(o.currency == "INR" for o in orders)


async def test_get_orders_open_only_filters_non_open() -> None:
    kite = MagicMock()
    kite.orders.return_value = [_ORDER_COMPLETE, _ORDER_OPEN, _ORDER_TRIGGER_PENDING]
    adapter = _make_adapter(kite)

    open_orders = await adapter.get_orders(open_only=True)
    assert len(open_orders) == 2
    assert all(o.status in {"new", "partially_filled", "pending"} for o in open_orders)


# --------------------------------------------------------------------- error mapping


async def test_token_exception_maps_to_auth_expired() -> None:
    kite = MagicMock()
    kite.holdings.side_effect = TokenException("Token is invalid or has expired")
    adapter = _make_adapter(kite)

    with pytest.raises(BrokerAPIError) as excinfo:
        await adapter.get_positions()
    assert excinfo.value.code == BrokerErrorCode.AUTH_EXPIRED
    assert excinfo.value.broker == "zerodha"


async def test_network_exception_maps_to_network_timeout() -> None:
    kite = MagicMock()
    kite.margins.side_effect = NetworkException("connection reset")
    adapter = _make_adapter(kite)

    with pytest.raises(BrokerAPIError) as excinfo:
        await adapter.get_balances()
    assert excinfo.value.code == BrokerErrorCode.NETWORK_TIMEOUT


async def test_input_exception_maps_to_instrument_unknown() -> None:
    kite = MagicMock()
    kite.orders.side_effect = InputException("invalid input")
    adapter = _make_adapter(kite)

    with pytest.raises(BrokerAPIError) as excinfo:
        await adapter.get_orders()
    assert excinfo.value.code == BrokerErrorCode.INSTRUMENT_UNKNOWN


async def test_generic_exception_maps_to_upstream_down() -> None:
    kite = MagicMock()
    kite.holdings.side_effect = RuntimeError("boom")
    adapter = _make_adapter(kite)

    with pytest.raises(BrokerAPIError) as excinfo:
        await adapter.get_positions()
    assert excinfo.value.code == BrokerErrorCode.UPSTREAM_DOWN


# --------------------------------------------------------------------- misc


async def test_place_order_raises_not_implemented() -> None:
    adapter = _make_adapter(MagicMock())
    with pytest.raises(NotImplementedError):
        await adapter.place_order(
            broker_symbol="RELIANCE",
            side="buy",
            quantity=1.0,
            idempotency_key="k",
        )


def test_normalize_symbol_is_passthrough() -> None:
    adapter = _make_adapter(MagicMock())
    assert adapter.normalize_symbol("RELIANCE") == "RELIANCE"


def test_features_flags() -> None:
    adapter = _make_adapter(MagicMock())
    f = adapter.features
    assert f.supports_positions is True
    assert f.supports_balances is True
    assert f.supports_orders is True
    assert f.supports_place_order is False
    assert f.supports_oauth is True
    assert f.supports_realtime_streaming is True
    assert f.supports_paper_trading is False
    assert f.requires_daily_reauth is True
