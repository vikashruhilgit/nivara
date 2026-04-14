"""Corporate actions detection + OHLCV adjustment pipeline.

Responsibilities
----------------
1. **Detection (Yahoo adjustment factors):**
   :meth:`CorporateActionsService.detect_from_adjustment_factor` accepts a
   ``(instrument_id, ex_date, factor)`` triple — e.g. 0.5 for a 2-for-1 split,
   2.0 for a 1-for-2 reverse split — produced by :mod:`backend.app.data.yahoo`
   on the daily OHLCV refresh. A factor of exactly ``Decimal("1")`` is a
   no-op; anything else is recorded as a ``split`` corporate action.

2. **Detection (broker sync anomaly):**
   :meth:`CorporateActionsService.detect_broker_position_anomaly` compares
   the previously stored position quantity against the broker-reported one.
   If they differ by more than a small tolerance **and** there is no order
   in ``orders`` between the two sync times that explains the delta, the
   discrepancy is flagged as a *potential* corporate action (the row is
   inserted with ``applied=False`` and ``notes='auto-flagged: qty anomaly'``;
   no OHLCV adjustment is run — a human reviews).

3. **Adjustment pipeline:**
   :meth:`CorporateActionsService.apply_split` multiplies pre-ex-date
   ``price_history`` rows by the split factor, invalidates any cached
   indicators under ``tech:{instrument_id}:*``, sets ``applied=true`` on the
   corporate-actions row, and writes an audit-log entry.

Schema alignment
----------------
The current ``corporate_actions`` schema does NOT have an ``applied`` column
(only ``id, instrument_id, action_type, ex_date, ratio_or_amount, currency,
notes, created_at``). We therefore track applied-state in the ``notes`` field
using a small marker protocol (``APPLIED_MARKER``). This keeps the service
self-contained without requiring a new migration; once the schema adds an
``applied`` boolean the service can switch to it and the marker can be
deprecated.

Cache invalidation contract
---------------------------
Indicator caches are assumed to be keyed ``tech:{instrument_id}:*`` (see
m2-13). We use :func:`Redis.scan_iter` (cursor-paged, non-blocking) rather
than ``KEYS`` to avoid stalling the Redis event loop.

Numeric note
------------
Split factors and OHLCV prices are ``Decimal`` throughout; Yahoo emits
``float`` adjustment factors (imprecise for thirds etc.) so callers should
pass them in as ``Decimal(str(factor))`` to preserve the repr.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from backend.app.config import get_settings
from backend.app.models.audit_log import AuditLog
from backend.app.models.corporate_actions import CorporateAction
from backend.app.models.orders import Order
from backend.app.models.price_history import PriceHistory
from redis.asyncio import Redis
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: A factor of exactly 1.0 means "no corporate action" — skip recording.
NO_ACTION_FACTOR = Decimal("1")

#: Tolerance for broker quantity anomaly comparison.
QTY_ANOMALY_TOLERANCE = Decimal("0.00000001")

#: Marker appended to ``notes`` once OHLCV adjustment has been applied.
APPLIED_MARKER = "[applied]"

#: Marker appended to ``notes`` when the action is auto-flagged (awaiting review).
FLAGGED_MARKER = "[flagged:qty-anomaly]"


@dataclass(frozen=True, slots=True)
class SplitDetection:
    """Result of a Yahoo adjustment-factor detection."""

    instrument_id: UUID
    ex_date: date
    factor: Decimal
    corporate_action_id: UUID


@dataclass(frozen=True, slots=True)
class QtyAnomaly:
    """Result of a broker-sync quantity anomaly detection (flagged, not applied)."""

    instrument_id: UUID
    broker_connection_id: UUID
    observed_at: datetime
    previous_qty: Decimal
    new_qty: Decimal
    corporate_action_id: UUID


class CorporateActionsService:
    """Detect and apply corporate actions on stored OHLCV data."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        redis: Redis,
    ) -> None:
        self._session = session
        self._redis = redis

    # ------------------------------------------------------------------ detect

    async def detect_from_adjustment_factor(
        self,
        *,
        instrument_id: UUID,
        ex_date: date,
        factor: Decimal,
        currency: str | None = None,
        notes: str | None = None,
    ) -> SplitDetection | None:
        """Record a split corporate action from a Yahoo adjustment factor.

        Returns ``None`` when ``factor == 1`` (no-op). Otherwise inserts a
        ``split`` row and returns a :class:`SplitDetection` ready to be fed
        into :meth:`apply_split`.
        """
        if factor == NO_ACTION_FACTOR:
            return None

        row = CorporateAction(
            instrument_id=instrument_id,
            action_type="split",
            ex_date=ex_date,
            ratio_or_amount=factor,
            currency=currency,
            notes=notes,
        )
        self._session.add(row)
        await self._session.flush()
        return SplitDetection(
            instrument_id=instrument_id,
            ex_date=ex_date,
            factor=factor,
            corporate_action_id=row.id,
        )

    async def detect_broker_position_anomaly(
        self,
        *,
        broker_connection_id: UUID,
        instrument_id: UUID,
        previous_qty: Decimal,
        new_qty: Decimal,
        previous_synced_at: datetime,
        observed_at: datetime | None = None,
    ) -> QtyAnomaly | None:
        """Flag a quantity change unexplained by order history as a corporate action.

        A row is inserted into ``corporate_actions`` with ``notes`` carrying
        :data:`FLAGGED_MARKER` so downstream review UI can find it. The
        OHLCV adjustment pipeline is NOT run — a human must confirm first
        (and then call :meth:`apply_split` if it's a split).
        """
        if abs(new_qty - previous_qty) <= QTY_ANOMALY_TOLERANCE:
            return None

        observed = observed_at or datetime.now(UTC)

        # Any orders between the last sync and now that cover the delta?
        stmt = select(Order).where(
            and_(
                Order.broker_connection_id == broker_connection_id,
                Order.instrument_id == instrument_id,
                Order.status.in_(("filled", "partial")),
                Order.created_at >= previous_synced_at,
                Order.created_at <= observed,
            )
        )
        orders = list((await self._session.execute(stmt)).scalars().all())
        # Sum signed order quantities (buy positive, sell negative).
        order_delta = Decimal("0")
        for o in orders:
            signed = o.quantity if o.side == "buy" else -o.quantity
            order_delta += signed

        position_delta = new_qty - previous_qty
        if abs(position_delta - order_delta) <= QTY_ANOMALY_TOLERANCE:
            # Orders fully explain the qty change — nothing to flag.
            return None

        note_parts = [FLAGGED_MARKER, f"prev={previous_qty} new={new_qty}"]
        row = CorporateAction(
            instrument_id=instrument_id,
            action_type="split",  # best-guess; reviewer can correct
            ex_date=observed.date(),
            # Ratio unknown; record the qty factor as a starting hypothesis.
            ratio_or_amount=(previous_qty / new_qty) if new_qty != 0 else Decimal("1"),
            notes=" ".join(note_parts),
        )
        self._session.add(row)
        await self._session.flush()

        logger.warning(
            "corporate_actions.flagged instrument_id=%s prev=%s new=%s order_delta=%s",
            instrument_id,
            previous_qty,
            new_qty,
            order_delta,
        )
        return QtyAnomaly(
            instrument_id=instrument_id,
            broker_connection_id=broker_connection_id,
            observed_at=observed,
            previous_qty=previous_qty,
            new_qty=new_qty,
            corporate_action_id=row.id,
        )

    # ------------------------------------------------------------------- apply

    async def apply_split(
        self,
        detection: SplitDetection,
        *,
        user_id: UUID | None = None,
    ) -> int:
        """Adjust pre-ex-date OHLCV, invalidate caches, mark row applied.

        Returns the number of ``price_history`` rows updated. Idempotent —
        re-applying a split that already carries :data:`APPLIED_MARKER`
        in its notes is a no-op (returns ``0``).
        """
        # Idempotency guard — re-read the row (flush above staged it in-session).
        row = await self._session.get(CorporateAction, detection.corporate_action_id)
        if row is None:
            raise ValueError(f"CorporateAction {detection.corporate_action_id} not found")
        if row.notes and APPLIED_MARKER in row.notes:
            logger.info(
                "corporate_actions.apply skipped (already applied) id=%s",
                row.id,
            )
            return 0

        settings = get_settings()
        window_start = datetime.combine(
            detection.ex_date - timedelta(days=settings.corp_action_adjust_history_days),
            datetime.min.time(),
            tzinfo=UTC,
        )
        ex_cutoff = datetime.combine(detection.ex_date, datetime.min.time(), tzinfo=UTC)

        # Bulk UPDATE: multiply OHLC columns by the factor for pre-ex-date rows.
        # Volume is conventionally divided by the split ratio — but since Yahoo's
        # 'factor' is the *price* adjustment (split ratio inverse), volume gets
        # multiplied by 1/factor. Guarded against div-by-zero.
        factor = detection.factor
        vol_factor = (Decimal("1") / factor) if factor != 0 else Decimal("1")

        stmt = (
            update(PriceHistory)
            .where(
                PriceHistory.instrument_id == detection.instrument_id,
                PriceHistory.timestamp >= window_start,
                PriceHistory.timestamp < ex_cutoff,
            )
            .values(
                open=PriceHistory.open * factor,
                high=PriceHistory.high * factor,
                low=PriceHistory.low * factor,
                close=PriceHistory.close * factor,
                # volume column is BigInteger; cast via integer truncation.
                # Use Python-side compute on read path if needed; here we keep
                # the column typed by casting.
                volume=(PriceHistory.volume * vol_factor),
            )
        )
        result = await self._session.execute(stmt)
        rows_updated = int(getattr(result, "rowcount", 0) or 0)

        # Invalidate indicator caches for this instrument.
        invalidated = await self._invalidate_indicator_cache(detection.instrument_id)

        # Mark as applied (via notes marker — no 'applied' column in schema).
        new_notes = (row.notes + " " if row.notes else "") + APPLIED_MARKER
        row.notes = new_notes

        # Audit trail.
        self._session.add(
            AuditLog(
                user_id=user_id,
                event_type="corporate_action.applied",
                event_data={
                    "corporate_action_id": str(row.id),
                    "instrument_id": str(detection.instrument_id),
                    "ex_date": detection.ex_date.isoformat(),
                    "factor": str(factor),
                    "rows_updated": rows_updated,
                    "cache_keys_invalidated": invalidated,
                },
            )
        )
        await self._session.commit()

        logger.info(
            "corporate_actions.applied id=%s instrument_id=%s factor=%s rows=%s cache=%s",
            row.id,
            detection.instrument_id,
            factor,
            rows_updated,
            invalidated,
        )
        return rows_updated

    async def _invalidate_indicator_cache(self, instrument_id: UUID) -> int:
        """Delete all ``tech:{instrument_id}:*`` Redis keys. Returns count deleted."""
        pattern = f"tech:{instrument_id}:*"
        deleted = 0
        try:
            async for key in self._redis.scan_iter(match=pattern, count=200):
                await self._redis.delete(key)
                deleted += 1
        except Exception:  # pragma: no cover — best-effort cache invalidation
            logger.warning(
                "corporate_actions.cache_invalidate failed pattern=%s",
                pattern,
                exc_info=True,
            )
        return deleted


__all__ = [
    "APPLIED_MARKER",
    "CorporateActionsService",
    "FLAGGED_MARKER",
    "NO_ACTION_FACTOR",
    "QTY_ANOMALY_TOLERANCE",
    "QtyAnomaly",
    "SplitDetection",
]
