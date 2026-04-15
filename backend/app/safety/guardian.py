"""Safety guardian (M3-19).

Centralises the four pre-trade safety checks required by the Safety Layer:

1. **Position size** — proposed notional must stay below a % of portfolio.
2. **Daily loss** — current value vs start-of-day must not breach the daily
   loss limit.
3. **Max drawdown** — current value vs peak must not breach the drawdown
   limit.
4. **Duplicate order** — the same (symbol, side, qty) triple cannot be
   submitted twice inside a short rolling window (default 60 s). Backed by
   a Redis sorted set so lookups and GC are O(log N).

Every rejection writes an ``audit_log`` row via :class:`AuditService` so
downstream operators can reconstruct a full safety timeline.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any
from uuid import UUID

from backend.app.schemas.safety import SafetyDecision
from backend.app.services.audit import AuditService
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

EVENT_SAFETY_VIOLATION = "safety.violation"

RECENT_ORDERS_KEY_PREFIX = "safety:recent_orders:"

# Machine-readable violation codes.
CODE_POSITION_SIZE = "position_size_exceeded"
CODE_DAILY_LOSS = "daily_loss_exceeded"
CODE_MAX_DRAWDOWN = "max_drawdown_exceeded"
CODE_DUPLICATE_ORDER = "duplicate_order"


def _to_float(value: Decimal) -> float:
    """Best-effort Decimal → float for JSON-serialisable audit details."""

    return float(value)


class SafetyGuardian:
    """Pre-trade validation orchestrator.

    The guardian holds a reference to an :class:`AsyncSession` so it can
    record audit rows, but it does not commit — the caller owns the
    transaction boundary (consistent with the portfolio sync pattern).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditService(session)

    # ------------------------------------------------------------------ internals

    async def _record_violation(
        self,
        *,
        user_id: UUID,
        code: str,
        reason: str,
        details: dict[str, Any],
    ) -> None:
        await self._audit.record(
            event_type=EVENT_SAFETY_VIOLATION,
            user_id=user_id,
            event_data={"code": code, "reason": reason, **details},
        )

    # ---------------------------------------------------------------- size check

    async def validate_position_size(
        self,
        *,
        user_id: UUID,
        instrument_id: UUID,
        proposed_value: Decimal,
        portfolio_value: Decimal,
        max_pct: Decimal = Decimal("0.10"),
    ) -> SafetyDecision:
        """Reject orders whose post-fill notional exceeds ``max_pct`` of portfolio."""

        if portfolio_value <= Decimal("0"):
            details: dict[str, Any] = {
                "instrument_id": str(instrument_id),
                "proposed_value": _to_float(proposed_value),
                "portfolio_value": _to_float(portfolio_value),
                "max_pct": _to_float(max_pct),
            }
            reason = "Portfolio value is zero; cannot evaluate position size."
            await self._record_violation(
                user_id=user_id,
                code=CODE_POSITION_SIZE,
                reason=reason,
                details=details,
            )
            return SafetyDecision(
                allowed=False, reason=reason, code=CODE_POSITION_SIZE, details=details
            )

        limit_value = portfolio_value * max_pct
        if proposed_value > limit_value:
            pct_of_portfolio = proposed_value / portfolio_value
            details = {
                "instrument_id": str(instrument_id),
                "proposed_value": _to_float(proposed_value),
                "portfolio_value": _to_float(portfolio_value),
                "max_pct": _to_float(max_pct),
                "pct_of_portfolio": _to_float(pct_of_portfolio),
            }
            reason = (
                f"Proposed position ({pct_of_portfolio:.2%}) exceeds max allowed ({max_pct:.2%})."
            )
            await self._record_violation(
                user_id=user_id,
                code=CODE_POSITION_SIZE,
                reason=reason,
                details=details,
            )
            return SafetyDecision(
                allowed=False, reason=reason, code=CODE_POSITION_SIZE, details=details
            )

        return SafetyDecision(allowed=True)

    # -------------------------------------------------------------- daily loss

    async def check_daily_loss(
        self,
        *,
        user_id: UUID,
        current_value: Decimal,
        start_of_day_value: Decimal,
        limit_pct: Decimal = Decimal("0.02"),
    ) -> SafetyDecision:
        """Reject when today's drawdown exceeds ``limit_pct``."""

        if start_of_day_value <= Decimal("0"):
            return SafetyDecision(allowed=True)

        loss = start_of_day_value - current_value
        if loss <= Decimal("0"):
            return SafetyDecision(allowed=True)

        loss_pct = loss / start_of_day_value
        if loss_pct >= limit_pct:
            details: dict[str, Any] = {
                "current_value": _to_float(current_value),
                "start_of_day_value": _to_float(start_of_day_value),
                "loss_pct": _to_float(loss_pct),
                "limit_pct": _to_float(limit_pct),
            }
            reason = f"Daily loss ({loss_pct:.2%}) has breached limit ({limit_pct:.2%})."
            await self._record_violation(
                user_id=user_id,
                code=CODE_DAILY_LOSS,
                reason=reason,
                details=details,
            )
            return SafetyDecision(
                allowed=False, reason=reason, code=CODE_DAILY_LOSS, details=details
            )

        return SafetyDecision(allowed=True)

    # ------------------------------------------------------------ max drawdown

    async def check_max_drawdown(
        self,
        *,
        user_id: UUID,
        current_value: Decimal,
        peak_value: Decimal,
        limit_pct: Decimal = Decimal("0.10"),
    ) -> SafetyDecision:
        """Reject when current drawdown from peak exceeds ``limit_pct``."""

        if peak_value <= Decimal("0"):
            return SafetyDecision(allowed=True)

        drawdown = peak_value - current_value
        if drawdown <= Decimal("0"):
            return SafetyDecision(allowed=True)

        drawdown_pct = drawdown / peak_value
        if drawdown_pct >= limit_pct:
            details: dict[str, Any] = {
                "current_value": _to_float(current_value),
                "peak_value": _to_float(peak_value),
                "drawdown_pct": _to_float(drawdown_pct),
                "limit_pct": _to_float(limit_pct),
            }
            reason = f"Drawdown ({drawdown_pct:.2%}) has breached limit ({limit_pct:.2%})."
            await self._record_violation(
                user_id=user_id,
                code=CODE_MAX_DRAWDOWN,
                reason=reason,
                details=details,
            )
            return SafetyDecision(
                allowed=False, reason=reason, code=CODE_MAX_DRAWDOWN, details=details
            )

        return SafetyDecision(allowed=True)

    # -------------------------------------------------------- duplicate order

    @staticmethod
    def _orders_key(user_id: UUID) -> str:
        return f"{RECENT_ORDERS_KEY_PREFIX}{user_id}"

    @staticmethod
    def _order_member(symbol: str, side: str, qty: Decimal) -> str:
        return f"{symbol}|{side}|{qty}"

    async def check_duplicate_order(
        self,
        redis: Redis,
        *,
        user_id: UUID,
        symbol: str,
        side: str,
        qty: Decimal,
        window_seconds: int = 60,
    ) -> SafetyDecision:
        """Reject a duplicate ``(symbol, side, qty)`` within ``window_seconds``.

        Implementation: a Redis sorted set keyed per user with current
        monotonic timestamp as the score. Entries older than the window are
        purged before the lookup to keep the set bounded. Uses ``ZSCORE`` to
        avoid a false positive on the member we would insert ourselves.
        """

        key = self._orders_key(user_id)
        member = self._order_member(symbol, side, qty)
        now = time.time()
        cutoff = now - window_seconds

        # Trim entries older than the rolling window.
        await redis.zremrangebyscore(key, "-inf", cutoff)
        # Bound membership TTL so abandoned users don't leak keys.
        await redis.expire(key, window_seconds * 2)

        existing_score = await redis.zscore(key, member)
        if existing_score is not None and float(existing_score) >= cutoff:
            details: dict[str, Any] = {
                "symbol": symbol,
                "side": side,
                "qty": _to_float(qty),
                "window_seconds": window_seconds,
                "last_seen_ts": float(existing_score),
            }
            reason = f"Duplicate order for {symbol} {side} {qty} within {window_seconds}s window."
            await self._record_violation(
                user_id=user_id,
                code=CODE_DUPLICATE_ORDER,
                reason=reason,
                details=details,
            )
            return SafetyDecision(
                allowed=False, reason=reason, code=CODE_DUPLICATE_ORDER, details=details
            )

        return SafetyDecision(allowed=True)

    async def record_order(
        self,
        redis: Redis,
        *,
        user_id: UUID,
        symbol: str,
        side: str,
        qty: Decimal,
        window_seconds: int = 60,
    ) -> None:
        """Record an accepted order so future duplicate checks see it."""

        key = self._orders_key(user_id)
        member = self._order_member(symbol, side, qty)
        await redis.zadd(key, {member: time.time()})
        await redis.expire(key, window_seconds * 2)

    # ------------------------------------------------------------ aggregate

    async def validate_action(
        self,
        redis: Redis,
        *,
        user_id: UUID,
        instrument_id: UUID,
        symbol: str,
        side: str,
        qty: Decimal,
        proposed_value: Decimal,
        portfolio_value: Decimal,
        start_of_day_value: Decimal,
        peak_value: Decimal,
        max_position_pct: Decimal = Decimal("0.10"),
        daily_loss_pct: Decimal = Decimal("0.02"),
        max_drawdown_pct: Decimal = Decimal("0.10"),
        window_seconds: int = 60,
    ) -> SafetyDecision:
        """Run every check in turn and return the first failure (or allow)."""

        checks = [
            await self.validate_position_size(
                user_id=user_id,
                instrument_id=instrument_id,
                proposed_value=proposed_value,
                portfolio_value=portfolio_value,
                max_pct=max_position_pct,
            ),
            await self.check_daily_loss(
                user_id=user_id,
                current_value=portfolio_value,
                start_of_day_value=start_of_day_value,
                limit_pct=daily_loss_pct,
            ),
            await self.check_max_drawdown(
                user_id=user_id,
                current_value=portfolio_value,
                peak_value=peak_value,
                limit_pct=max_drawdown_pct,
            ),
            await self.check_duplicate_order(
                redis,
                user_id=user_id,
                symbol=symbol,
                side=side,
                qty=qty,
                window_seconds=window_seconds,
            ),
        ]
        for decision in checks:
            if not decision.allowed:
                return decision
        return SafetyDecision(allowed=True)


__all__ = [
    "CODE_DAILY_LOSS",
    "CODE_DUPLICATE_ORDER",
    "CODE_MAX_DRAWDOWN",
    "CODE_POSITION_SIZE",
    "EVENT_SAFETY_VIOLATION",
    "RECENT_ORDERS_KEY_PREFIX",
    "SafetyGuardian",
]
