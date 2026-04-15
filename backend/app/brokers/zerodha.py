"""Zerodha (Kite Connect v3) adapter — read-only MVP.

Uses the official ``kiteconnect`` Python SDK. Because the SDK is synchronous
(blocking HTTP + thread-unsafe websocket), all broker calls are wrapped in
:func:`asyncio.to_thread` so the adapter honours the project's async-first
convention.

Auth model
----------
Kite Connect v3 uses a daily OAuth dance: the user exchanges a short-lived
``request_token`` for a session-scoped ``access_token`` (valid until 06:00 AM
IST the next day). This adapter consumes an already-minted ``access_token``;
the OAuth redirect / exchange is handled elsewhere (see
``backend.app.routers.broker_oauth``). When the token expires,
:class:`kiteconnect.exceptions.TokenException` is raised and surfaced as
:class:`BrokerAPIError` with :attr:`BrokerErrorCode.AUTH_EXPIRED` so the
caller can trigger a re-auth redirect.

Write-path
----------
``place_order`` intentionally raises :class:`NotImplementedError` — Zerodha
order placement is explicitly post-MVP (see brief ``m4-22-zerodha-adapter.md``
AC #8 and TechSpec v1.3).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from backend.app.brokers.base import BrokerAdapter, BrokerFeatures
from backend.app.brokers.errors import BrokerAPIError, BrokerErrorCode
from backend.app.schemas.broker import (
    NormalizedBalance,
    NormalizedOrder,
    NormalizedPosition,
    OrderSide,
    OrderStatus,
    OrderType,
)
from kiteconnect import KiteConnect
from kiteconnect.exceptions import (
    InputException,
    KiteException,
    NetworkException,
    TokenException,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Broker-reported exchange code → ISO MIC-style canonical code.
# Zerodha holdings/positions include "NSE" or "BSE"; we canonicalise to
# XNSE / XBOM so downstream modules don't need to special-case each broker.
_BROKER_EXCHANGE_TO_MIC: dict[str, str] = {
    "NSE": "XNSE",
    "BSE": "XBOM",
    # Passthrough if caller already supplied a MIC-style code.
    "XNSE": "XNSE",
    "XBOM": "XBOM",
}


def exchange_to_mic(broker_exchange: str | None) -> str:
    """Return the canonical MIC-style exchange code for a Zerodha exchange.

    Defaults to ``"XNSE"`` when the input is missing or unrecognised — NSE is
    the dominant Zerodha venue and the safest fallback for Indian equities.
    """
    if not broker_exchange:
        return "XNSE"
    return _BROKER_EXCHANGE_TO_MIC.get(broker_exchange.strip().upper(), "XNSE")


# Kite Connect access tokens expire daily at 06:00 IST (Asia/Kolkata).
# See: https://kite.trade/docs/connect/v3/user/#login-flow
_IST = ZoneInfo("Asia/Kolkata")
_KITE_DAILY_EXPIRY_HOUR_IST = 6


def _last_kite_expiry_cutoff(now_utc: datetime) -> datetime:
    """Return the most recent 06:00 IST cutoff at-or-before ``now_utc``.

    Any ``access_token_issued_at`` strictly before this cutoff is stale:
    Kite Connect expires tokens daily at 06:00 IST regardless of issue time.
    """
    now_ist = now_utc.astimezone(_IST)
    todays_cutoff_ist = datetime.combine(
        now_ist.date(), time(hour=_KITE_DAILY_EXPIRY_HOUR_IST), tzinfo=_IST
    )
    if now_ist >= todays_cutoff_ist:
        cutoff_ist = todays_cutoff_ist
    else:
        cutoff_ist = todays_cutoff_ist - timedelta(days=1)
    return cutoff_ist.astimezone(UTC)


# Zerodha order status → NormalizedOrder.status.
# Reference: https://kite.trade/docs/connect/v3/orders/#order-statuses
_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "COMPLETE": "filled",
    "OPEN": "new",
    "CANCELLED": "canceled",
    "REJECTED": "rejected",
    "TRIGGER PENDING": "new",
}


class ZerodhaAdapter(BrokerAdapter):
    """Read-only Zerodha Kite Connect v3 adapter."""

    broker_name = "zerodha"

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        access_token: str,
        access_token_issued_at: datetime | None = None,
        kite_client: KiteConnect | None = None,
        symbol_mapper: Callable[[str, str | None], tuple[str, str]] | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_token = access_token
        self._access_token_issued_at = access_token_issued_at
        if kite_client is None:
            kite_client = KiteConnect(api_key=api_key)
            kite_client.set_access_token(access_token)
        self._kite = kite_client
        # Optional resolver: (broker_symbol, broker_exchange) -> (canonical_symbol,
        # canonical_exchange_mic). Callers with DB access wire this to
        # :class:`SymbolMappingService`; tests can inject a pure dict-backed fake.
        # When absent, :meth:`resolve_canonical` falls back to a MIC conversion
        # of ``broker_exchange`` and the broker_symbol itself (uppercased).
        self.symbol_mapper: Callable[[str, str | None], tuple[str, str]] | None = symbol_mapper

    # ------------------------------------------------------------------ token expiry

    def _is_token_expired(self, *, now_utc: datetime | None = None) -> bool:
        """Return True if the stored access token is past its 06:00 IST cutoff.

        Returns False when ``access_token_issued_at`` is unknown (can't
        pre-empt; reactive TokenException → AUTH_EXPIRED still covers it).
        """
        if self._access_token_issued_at is None:
            return False
        now_utc = now_utc or datetime.now(UTC)
        issued_at = self._access_token_issued_at
        if issued_at.tzinfo is None:
            # Defensive: treat naive timestamps as UTC to avoid false positives.
            issued_at = issued_at.replace(tzinfo=UTC)
        cutoff = _last_kite_expiry_cutoff(now_utc)
        return issued_at < cutoff

    # ------------------------------------------------------------------ features

    @property
    def features(self) -> BrokerFeatures:
        return BrokerFeatures(
            supports_positions=True,
            supports_balances=True,
            supports_orders=True,
            supports_place_order=False,  # post-MVP
            supports_oauth=True,
            supports_realtime_streaming=True,
            supports_paper_trading=False,
            requires_daily_reauth=True,
        )

    # ------------------------------------------------------------------ helpers

    async def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Invoke a blocking kiteconnect call in a worker thread, translating errors.

        Performs a pre-flight check against the known daily 06:00 IST expiry
        cutoff when ``access_token_issued_at`` is plumbed through — this
        avoids a wasted network round-trip and surfaces AUTH_EXPIRED with
        the same code path callers already handle.
        """
        if self._is_token_expired():
            raise BrokerAPIError(
                BrokerErrorCode.AUTH_EXPIRED,
                "Zerodha access token expired (past 06:00 IST daily cutoff)",
                broker=self.broker_name,
            )
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except TokenException as exc:
            raise BrokerAPIError(
                BrokerErrorCode.AUTH_EXPIRED,
                f"Zerodha access token expired or invalid: {exc}",
                broker=self.broker_name,
            ) from exc
        except NetworkException as exc:
            raise BrokerAPIError(
                BrokerErrorCode.NETWORK_TIMEOUT,
                f"Zerodha network error: {exc}",
                broker=self.broker_name,
            ) from exc
        except InputException as exc:
            raise BrokerAPIError(
                BrokerErrorCode.INSTRUMENT_UNKNOWN,
                f"Zerodha rejected request: {exc}",
                broker=self.broker_name,
            ) from exc
        except KiteException as exc:
            raise BrokerAPIError(
                BrokerErrorCode.UPSTREAM_DOWN,
                f"Zerodha upstream error: {exc}",
                broker=self.broker_name,
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected Zerodha SDK error")
            raise BrokerAPIError(
                BrokerErrorCode.UPSTREAM_DOWN,
                f"Unexpected Zerodha error: {exc}",
                broker=self.broker_name,
            ) from exc

    # ------------------------------------------------------------------ reads

    async def get_positions(self) -> list[NormalizedPosition]:
        """Return a deduped union of long-term holdings and intraday net positions.

        Zerodha exposes two position buckets:
        * ``kite.holdings()`` — delivery / settled holdings (CNC).
        * ``kite.positions()['net']`` — intraday MIS + overnight NRML nets.

        We merge both and dedupe on ``(tradingsymbol, exchange)``; holdings win
        on conflict because they carry the authoritative avg-cost basis.
        """
        holdings: list[dict[str, Any]] = await self._call(self._kite.holdings)
        positions_resp: dict[str, Any] = await self._call(self._kite.positions)
        net_positions: list[dict[str, Any]] = list(positions_resp.get("net", []))

        seen: set[tuple[str, str]] = set()
        normalized: list[NormalizedPosition] = []

        for row in holdings:
            key = (str(row.get("tradingsymbol", "")), str(row.get("exchange", "") or ""))
            seen.add(key)
            normalized.append(self._parse_holding(row))

        for row in net_positions:
            key = (str(row.get("tradingsymbol", "")), str(row.get("exchange", "") or ""))
            if key in seen:
                continue
            # Skip zero-qty rows (Zerodha returns flat intraday rows for closed legs).
            if Decimal(str(row.get("quantity", "0"))) == 0:
                continue
            seen.add(key)
            normalized.append(self._parse_net_position(row))

        return normalized

    async def get_balances(self) -> NormalizedBalance:
        """Return equity-segment cash snapshot (INR)."""
        margins: dict[str, Any] = await self._call(self._kite.margins, "equity")
        available = margins.get("available", {}) or {}
        utilised = margins.get("utilised", {}) or {}
        cash = Decimal(str(available.get("cash", available.get("live_balance", "0"))))
        # Kite exposes `net` = available - utilised; treat as equity proxy.
        net_val = margins.get("net")
        if net_val is None:
            equity = cash - Decimal(str(utilised.get("debits", "0")))
        else:
            equity = Decimal(str(net_val))
        return NormalizedBalance(
            cash=cash,
            equity=equity,
            currency="INR",
            account_id=str(margins.get("account_id") or self._api_key),
        )

    async def get_orders(self, *, open_only: bool = False) -> list[NormalizedOrder]:
        raw: list[dict[str, Any]] = await self._call(self._kite.orders)
        parsed = [self._parse_order(o) for o in raw]
        if open_only:
            return [o for o in parsed if o.status in {"new", "partially_filled", "pending"}]
        return parsed

    # ------------------------------------------------------------------ normalize

    def normalize_symbol(self, broker_symbol: str) -> str:
        """Return the canonical ticker string for a Zerodha tradingsymbol.

        For Zerodha the tradingsymbol ("RELIANCE", "INFY", "M&M") is already
        the canonical equity symbol — we just normalise whitespace and case.
        The *exchange* half of the canonical pair is resolved separately via
        :meth:`resolve_canonical`, which can consult the ``symbol_mappings``
        table through an injected ``symbol_mapper``.

        Mirrors :meth:`AlpacaAdapter.normalize_symbol` — sync, string-in/string-out,
        honouring the base contract.
        """
        return broker_symbol.strip().upper()

    def resolve_canonical(
        self,
        broker_symbol: str,
        broker_exchange: str | None = None,
    ) -> tuple[str, str]:
        """Resolve ``(canonical_symbol, canonical_exchange_mic)`` for a Zerodha symbol.

        Resolution order:

        1. If ``self.symbol_mapper`` is set (typically wired to
           :class:`SymbolMappingService` at the call site), delegate to it.
           The mapper is expected to return ``(canonical_symbol, mic_exchange)``
           where ``mic_exchange`` is one of ``"XNSE"`` / ``"XBOM"``.
        2. Otherwise, fall back to ``(normalize_symbol(broker_symbol),
           exchange_to_mic(broker_exchange))`` — Zerodha tradingsymbols are
           canonical for equities, and the exchange translation covers the
           NSE→XNSE / BSE→XBOM case required by AC #7.

        Example:
            ``("RELIANCE", "NSE")`` → ``("RELIANCE", "XNSE")``
            ``("TCS",      "BSE")`` → ``("TCS",      "XBOM")``
        """
        bs = broker_symbol.strip()
        if self.symbol_mapper is not None:
            canonical_symbol, canonical_exchange = self.symbol_mapper(bs, broker_exchange)
            return canonical_symbol, canonical_exchange
        return self.normalize_symbol(bs), exchange_to_mic(broker_exchange)

    # ------------------------------------------------------------------ writes

    async def place_order(
        self,
        *,
        broker_symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = "market",
        limit_price: float | None = None,
        idempotency_key: str,
    ) -> NormalizedOrder:
        raise NotImplementedError("Zerodha order placement post-MVP")

    # ------------------------------------------------------------------ parse helpers

    @staticmethod
    def _parse_holding(raw: dict[str, Any]) -> NormalizedPosition:
        qty = Decimal(str(raw.get("quantity", "0")))
        avg = Decimal(str(raw.get("average_price", "0")))
        last = Decimal(str(raw.get("last_price", "0")))
        pnl = Decimal(str(raw.get("pnl", "0")))
        market_value = last * qty
        return NormalizedPosition(
            broker_symbol=str(raw.get("tradingsymbol", "")),
            quantity=qty,
            avg_entry_price=avg,
            current_price=last,
            market_value=market_value,
            unrealized_pl=pnl,
            currency="INR",
            exchange=raw.get("exchange"),
        )

    @staticmethod
    def _parse_net_position(raw: dict[str, Any]) -> NormalizedPosition:
        qty = Decimal(str(raw.get("quantity", "0")))
        avg = Decimal(str(raw.get("average_price", "0")))
        last = Decimal(str(raw.get("last_price", "0")))
        pnl = Decimal(str(raw.get("pnl", "0")))
        mv_raw = raw.get("value")
        market_value = Decimal(str(mv_raw)) if mv_raw is not None else last * qty
        return NormalizedPosition(
            broker_symbol=str(raw.get("tradingsymbol", "")),
            quantity=qty,
            avg_entry_price=avg,
            current_price=last,
            market_value=market_value,
            unrealized_pl=pnl,
            currency="INR",
            exchange=raw.get("exchange"),
        )

    @staticmethod
    def _parse_order(raw: dict[str, Any]) -> NormalizedOrder:
        status = _ORDER_STATUS_MAP.get(str(raw.get("status", "")).upper(), "pending")
        transaction = str(raw.get("transaction_type", "BUY")).upper()
        side: OrderSide = "buy" if transaction == "BUY" else "sell"
        order_type_raw = str(raw.get("order_type", "MARKET")).upper()
        order_type: OrderType
        if order_type_raw == "LIMIT":
            order_type = "limit"
        elif order_type_raw in {"SL", "STOPLOSS"}:
            order_type = "stop_limit"
        elif order_type_raw in {"SL-M", "SL_M", "STOPLOSS_MARKET"}:
            order_type = "stop"
        else:
            order_type = "market"

        limit = raw.get("price")
        stop = raw.get("trigger_price")
        return NormalizedOrder(
            broker_order_id=str(raw.get("order_id", "")),
            broker_symbol=str(raw.get("tradingsymbol", "")),
            side=side,
            order_type=order_type,
            quantity=Decimal(str(raw.get("quantity", "0"))),
            filled_quantity=Decimal(str(raw.get("filled_quantity", "0"))),
            limit_price=Decimal(str(limit)) if limit not in (None, 0, 0.0) else None,
            stop_price=Decimal(str(stop)) if stop not in (None, 0, 0.0) else None,
            status=status,
            submitted_at=raw["order_timestamp"],
            filled_at=raw.get("exchange_update_timestamp") if status == "filled" else None,
            currency="INR",
        )
