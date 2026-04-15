"""Conformance tests for concrete :class:`BrokerAdapter` implementations.

These tests are generic — any adapter passed to the fixture must satisfy the
interface contract. MVP exercises :class:`AlpacaAdapter` (with mocked HTTP)
and :class:`ZerodhaAdapter` (stub: ``NotImplementedError`` on every method).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from backend.app.brokers import BrokerAdapter, BrokerAPIError, BrokerErrorCode
from backend.app.brokers.alpaca import AlpacaAdapter
from backend.app.brokers.zerodha import ZerodhaAdapter
from backend.app.schemas.broker import (
    NormalizedBalance,
    NormalizedOrder,
    NormalizedPosition,
)

# --------------------------------------------------------------------- helpers


def _mock_transport(routes: dict[tuple[str, str], httpx.Response]) -> httpx.MockTransport:
    """Build a MockTransport that dispatches by (METHOD, path)."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        if key not in routes:
            return httpx.Response(404, json={"error": f"no route for {key}"})
        return routes[key]

    return httpx.MockTransport(handler)


def _alpaca_with_routes(routes: dict[tuple[str, str], httpx.Response]) -> AlpacaAdapter:
    client = httpx.AsyncClient(transport=_mock_transport(routes), base_url="http://alpaca-mock")
    return AlpacaAdapter(
        api_key="k",
        api_secret="s",
        base_url="http://alpaca-mock",
        http_client=client,
    )


_SAMPLE_POSITION = {
    "symbol": "AAPL",
    "qty": "10",
    "avg_entry_price": "150.00",
    "current_price": "175.50",
    "market_value": "1755.00",
    "unrealized_pl": "255.00",
    "exchange": "NASDAQ",
}

_SAMPLE_ACCOUNT = {
    "account_number": "ACC123",
    "cash": "10000.00",
    "equity": "25000.00",
    "currency": "USD",
}

_SAMPLE_ORDER = {
    "id": "order-1",
    "symbol": "AAPL",
    "qty": "5",
    "filled_qty": "5",
    "side": "buy",
    "order_type": "market",
    "status": "filled",
    "limit_price": None,
    "stop_price": None,
    "submitted_at": datetime(2026, 4, 10, 14, 30, tzinfo=UTC).isoformat(),
    "filled_at": datetime(2026, 4, 10, 14, 30, 5, tzinfo=UTC).isoformat(),
}


# --------------------------------------------------------------------- Alpaca happy path


async def test_alpaca_features_flags() -> None:
    adapter = _alpaca_with_routes({})
    assert adapter.features.supports_positions is True
    assert adapter.features.supports_balances is True
    assert adapter.features.supports_orders is True
    assert adapter.features.supports_place_order is False
    await adapter.aclose()


async def test_alpaca_get_positions_returns_normalized() -> None:
    adapter = _alpaca_with_routes(
        {("GET", "/v2/positions"): httpx.Response(200, json=[_SAMPLE_POSITION])}
    )
    positions = await adapter.get_positions()
    assert len(positions) == 1
    p = positions[0]
    assert isinstance(p, NormalizedPosition)
    assert p.broker_symbol == "AAPL"
    assert p.quantity == Decimal("10")
    assert p.avg_entry_price == Decimal("150.00")
    assert p.current_price == Decimal("175.50")
    assert p.currency == "USD"
    await adapter.aclose()


async def test_alpaca_get_balances_returns_normalized() -> None:
    adapter = _alpaca_with_routes(
        {("GET", "/v2/account"): httpx.Response(200, json=_SAMPLE_ACCOUNT)}
    )
    bal = await adapter.get_balances()
    assert isinstance(bal, NormalizedBalance)
    assert bal.cash == Decimal("10000.00")
    assert bal.equity == Decimal("25000.00")
    assert bal.account_id == "ACC123"
    await adapter.aclose()


async def test_alpaca_get_orders_returns_normalized() -> None:
    adapter = _alpaca_with_routes(
        {("GET", "/v2/orders"): httpx.Response(200, json=[_SAMPLE_ORDER])}
    )
    orders = await adapter.get_orders()
    assert len(orders) == 1
    o = orders[0]
    assert isinstance(o, NormalizedOrder)
    assert o.broker_order_id == "order-1"
    assert o.side == "buy"
    assert o.status == "filled"
    assert o.quantity == Decimal("5")
    await adapter.aclose()


async def test_alpaca_normalize_symbol_uppercases_and_strips() -> None:
    adapter = _alpaca_with_routes({})
    assert adapter.normalize_symbol("  aapl  ") == "AAPL"
    assert adapter.normalize_symbol("tsla") == "TSLA"
    await adapter.aclose()


async def test_alpaca_place_order_raises_not_implemented() -> None:
    adapter = _alpaca_with_routes({})
    with pytest.raises(NotImplementedError):
        await adapter.place_order(
            broker_symbol="AAPL",
            side="buy",
            quantity=1.0,
            idempotency_key="test-key",
        )
    await adapter.aclose()


# --------------------------------------------------------------------- Alpaca error mapping


@pytest.mark.parametrize(
    "http_status,expected_code",
    [
        (401, BrokerErrorCode.AUTH_EXPIRED),
        (403, BrokerErrorCode.AUTH_EXPIRED),
        (429, BrokerErrorCode.RATE_LIMITED),
        (500, BrokerErrorCode.UPSTREAM_DOWN),
        (503, BrokerErrorCode.UPSTREAM_DOWN),
    ],
)
async def test_alpaca_http_errors_map_to_broker_codes(
    http_status: int, expected_code: BrokerErrorCode
) -> None:
    adapter = _alpaca_with_routes(
        {("GET", "/v2/positions"): httpx.Response(http_status, json={"error": "nope"})}
    )
    with pytest.raises(BrokerAPIError) as excinfo:
        await adapter.get_positions()
    assert excinfo.value.code == expected_code
    assert excinfo.value.broker == "alpaca"
    await adapter.aclose()


async def test_alpaca_timeout_maps_to_network_timeout() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://alpaca-mock"
    )
    adapter = AlpacaAdapter(
        api_key="k", api_secret="s", base_url="http://alpaca-mock", http_client=client
    )
    with pytest.raises(BrokerAPIError) as excinfo:
        await adapter.get_positions()
    assert excinfo.value.code == BrokerErrorCode.NETWORK_TIMEOUT
    await adapter.aclose()


# --------------------------------------------------------------------- Broker error codes


def test_broker_error_codes_cover_required_set() -> None:
    required = {
        "AUTH_EXPIRED",
        "RATE_LIMITED",
        "INSTRUMENT_UNKNOWN",
        "UPSTREAM_DOWN",
        "NETWORK_TIMEOUT",
    }
    assert required <= {c.value for c in BrokerErrorCode}


# --------------------------------------------------------------------- Zerodha adapter


def _zerodha_with_mock_kite() -> ZerodhaAdapter:
    """Build a ZerodhaAdapter with a stub KiteConnect client (no network)."""
    from unittest.mock import MagicMock

    fake_kite = MagicMock()
    fake_kite.holdings.return_value = []
    fake_kite.positions.return_value = {"net": [], "day": []}
    fake_kite.orders.return_value = []
    fake_kite.margins.return_value = {
        "available": {"cash": "0"},
        "utilised": {"debits": "0"},
        "net": "0",
    }
    return ZerodhaAdapter(
        api_key="k",
        api_secret="s",
        access_token="tok",
        kite_client=fake_kite,
    )


async def test_zerodha_features_reflect_read_only_oauth() -> None:
    adapter = _zerodha_with_mock_kite()
    f = adapter.features
    assert f.supports_positions is True
    assert f.supports_balances is True
    assert f.supports_orders is True
    assert f.supports_place_order is False
    assert f.supports_oauth is True
    assert f.supports_realtime_streaming is True
    assert f.supports_paper_trading is False
    assert f.requires_daily_reauth is True


async def test_zerodha_place_order_raises_not_implemented() -> None:
    adapter = _zerodha_with_mock_kite()
    with pytest.raises(NotImplementedError):
        await adapter.place_order(
            broker_symbol="RELIANCE", side="buy", quantity=1.0, idempotency_key="k"
        )


async def test_zerodha_normalize_symbol_is_passthrough() -> None:
    adapter = _zerodha_with_mock_kite()
    assert adapter.normalize_symbol("RELIANCE") == "RELIANCE"


# --------------------------------------------------------------------- Zerodha error mapping


async def test_zerodha_token_exception_maps_to_auth_expired() -> None:
    from kiteconnect.exceptions import TokenException

    fake_kite = _zerodha_with_mock_kite()._kite
    fake_kite.holdings.side_effect = TokenException("expired")
    adapter = ZerodhaAdapter(api_key="k", api_secret="s", access_token="t", kite_client=fake_kite)
    with pytest.raises(BrokerAPIError) as excinfo:
        await adapter.get_positions()
    assert excinfo.value.code == BrokerErrorCode.AUTH_EXPIRED
    assert excinfo.value.broker == "zerodha"


async def test_zerodha_network_exception_maps_to_network_timeout() -> None:
    from kiteconnect.exceptions import NetworkException

    fake_kite = _zerodha_with_mock_kite()._kite
    fake_kite.margins.side_effect = NetworkException("connection reset")
    adapter = ZerodhaAdapter(api_key="k", api_secret="s", access_token="t", kite_client=fake_kite)
    with pytest.raises(BrokerAPIError) as excinfo:
        await adapter.get_balances()
    assert excinfo.value.code == BrokerErrorCode.NETWORK_TIMEOUT
    assert excinfo.value.broker == "zerodha"


# --------------------------------------------------------------------- Parametrized behavioural contract
#
# Any adapter fixture passed to these tests must satisfy the same behavioural
# contract — documented in :class:`BrokerAdapter`. Broker-specific values
# (currency, exchange) are asserted separately; the contract only checks
# *shapes* (types, enum membership, required fields).


def _alpaca_contract_adapter() -> BrokerAdapter:
    return _alpaca_with_routes(
        {
            ("GET", "/v2/positions"): httpx.Response(200, json=[_SAMPLE_POSITION]),
            ("GET", "/v2/account"): httpx.Response(200, json=_SAMPLE_ACCOUNT),
            ("GET", "/v2/orders"): httpx.Response(200, json=[_SAMPLE_ORDER]),
        }
    )


def _zerodha_contract_adapter() -> BrokerAdapter:
    from unittest.mock import MagicMock

    fake_kite = MagicMock()
    fake_kite.holdings.return_value = [
        {
            "tradingsymbol": "RELIANCE",
            "exchange": "NSE",
            "quantity": 10,
            "average_price": 2400.50,
            "last_price": 2500.00,
            "pnl": 995.00,
        }
    ]
    fake_kite.positions.return_value = {"net": [], "day": []}
    fake_kite.margins.return_value = {
        "available": {"cash": "15000.00"},
        "utilised": {"debits": "500.00"},
        "net": "14500.00",
        "account_id": "ZD1234",
    }
    fake_kite.orders.return_value = [
        {
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
    ]
    return ZerodhaAdapter(api_key="k", api_secret="s", access_token="t", kite_client=fake_kite)


ADAPTER_FACTORIES = [
    pytest.param(_alpaca_contract_adapter, id="alpaca"),
    pytest.param(_zerodha_contract_adapter, id="zerodha"),
]


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
async def test_contract_features_shape(factory: Callable[[], BrokerAdapter]) -> None:
    """Every adapter exposes the full :class:`BrokerFeatures` dataclass."""
    adapter = factory()
    try:
        f = adapter.features
        # All BrokerFeatures fields are booleans.
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
            assert isinstance(getattr(f, attr), bool), f"{attr} must be bool"
        # MVP contract: both adapters are read-only.
        assert f.supports_place_order is False
        assert f.supports_positions is True
        assert f.supports_balances is True
        assert f.supports_orders is True
    finally:
        close = getattr(adapter, "aclose", None)
        if close is not None:
            await close()


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
async def test_contract_get_positions_returns_normalized(
    factory: Callable[[], BrokerAdapter],
) -> None:
    adapter = factory()
    try:
        positions = await adapter.get_positions()
        assert isinstance(positions, list)
        assert len(positions) >= 1
        for p in positions:
            assert isinstance(p, NormalizedPosition)
            # Required normalized fields (market_value, unrealized_pl per schema).
            assert isinstance(p.broker_symbol, str) and p.broker_symbol
            assert isinstance(p.quantity, Decimal)
            assert isinstance(p.avg_entry_price, Decimal)
            assert isinstance(p.current_price, Decimal)
            assert isinstance(p.market_value, Decimal)
            assert isinstance(p.unrealized_pl, Decimal)
    finally:
        close = getattr(adapter, "aclose", None)
        if close is not None:
            await close()


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
async def test_contract_get_balances_returns_normalized(
    factory: Callable[[], BrokerAdapter],
) -> None:
    adapter = factory()
    try:
        bal = await adapter.get_balances()
        assert isinstance(bal, NormalizedBalance)
        assert isinstance(bal.cash, Decimal)
        assert isinstance(bal.equity, Decimal)
        assert bal.currency in {"USD", "INR", "EUR", "GBP"}
        assert isinstance(bal.account_id, str)
    finally:
        close = getattr(adapter, "aclose", None)
        if close is not None:
            await close()


_ALLOWED_ORDER_STATUSES = {
    "new",
    "partially_filled",
    "filled",
    "canceled",
    "rejected",
    "expired",
    "pending",
}


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
async def test_contract_get_orders_returns_normalized_enum_status(
    factory: Callable[[], BrokerAdapter],
) -> None:
    adapter = factory()
    try:
        orders = await adapter.get_orders()
        assert isinstance(orders, list)
        assert len(orders) >= 1
        for o in orders:
            assert isinstance(o, NormalizedOrder)
            # status MUST be the normalized enum, never a raw broker string
            # like "COMPLETE" or "TRIGGER PENDING".
            assert o.status in _ALLOWED_ORDER_STATUSES
            assert o.side in {"buy", "sell"}
            assert o.order_type in {"market", "limit", "stop", "stop_limit"}
    finally:
        close = getattr(adapter, "aclose", None)
        if close is not None:
            await close()


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
async def test_contract_place_order_raises_not_implemented(
    factory: Callable[[], BrokerAdapter],
) -> None:
    adapter = factory()
    try:
        with pytest.raises(NotImplementedError):
            await adapter.place_order(
                broker_symbol="SYM",
                side="buy",
                quantity=1.0,
                idempotency_key="test-key",
            )
    finally:
        close = getattr(adapter, "aclose", None)
        if close is not None:
            await close()


@pytest.mark.parametrize("factory", ADAPTER_FACTORIES)
async def test_contract_normalize_symbol_is_sync_and_uppercases(
    factory: Callable[[], BrokerAdapter],
) -> None:
    adapter = factory()
    try:
        # Sync (not coroutine), string-in / string-out per base contract.
        result = adapter.normalize_symbol("  abc  ")
        assert isinstance(result, str)
        assert result == "ABC"
    finally:
        close = getattr(adapter, "aclose", None)
        if close is not None:
            await close()


# --------------------------------------------------------------------- ABC contract


def test_cannot_instantiate_abstract_adapter() -> None:
    with pytest.raises(TypeError):
        BrokerAdapter()  # type: ignore[abstract]
