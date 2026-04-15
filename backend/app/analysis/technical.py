"""Technical analysis engine — 6 weighted indicators + composite signal.

Computes RSI, MACD, MA alignment, Bollinger Bands, volume, and ATR on an
OHLCV time series and combines them into a composite score in the range
``[-1, +1]`` which maps to a Strong Sell / Sell / Hold / Buy / Strong Buy
action. Results are cached per-indicator in Redis with a 5-minute TTL
(``tech:{instrument_id}:{name}``) so the recommendation engine can fan out
to many instruments without paying the pandas-ta cost on every call.

Indicator weights (TechSpec v1.3 §Scoring — technical 40% of composite)::

    RSI:               20%
    MACD:              20%
    MA alignment:      25%
    Bollinger Bands:   15%
    Volume:            10%
    ATR:               10%

Why individual normalisation to [-1, +1]
----------------------------------------
Each indicator is independently mapped onto a bounded, direction-consistent
signal: +1 is maximally bullish, -1 is maximally bearish, 0 is neutral.
This lets us mix them with simple weighted averaging and preserves
interpretability ("RSI contributed -0.6 because it's overbought").

Insufficient-data policy
------------------------
Most indicators need a minimum history (e.g. RSI-14 needs 14 bars, SMA-200
needs 200). When a required window is unavailable we return ``None`` for
that indicator and flag it as insufficient data. The composite re-normalises
the remaining weights so partial analyses still yield a comparable signal
(mirroring the fundamental scoring engine's behaviour). If fewer than
``_MIN_BARS_FOR_ANY_ANALYSIS`` (30) bars are provided, we refuse the whole
analysis and return ``composite=None`` with every indicator flagged.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pandas as pd

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# ---- Constants -------------------------------------------------------------

_MIN_BARS_FOR_ANY_ANALYSIS = 30
_CACHE_TTL_SECONDS = 300  # 5 minutes per TechSpec 9.1

# Minimum bars required for each indicator. Derived from the standard pandas-ta
# lookback windows: RSI(14), MACD(26+9=35), BB(20), ATR(14), SMA200(200),
# volume (20-day avg).
_MIN_BARS: dict[str, int] = {
    "rsi": 14,
    "macd": 35,
    "ma_alignment": 200,  # needs SMA200
    "bollinger": 20,
    "volume": 20,
    "atr": 14,
}

_WEIGHTS: dict[str, float] = {
    "rsi": 0.20,
    "macd": 0.20,
    "ma_alignment": 0.25,
    "bollinger": 0.15,
    "volume": 0.10,
    "atr": 0.10,
}

# Composite action thresholds per brief AC #2.
_ACTION_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (-0.6, "strong_sell"),
    (-0.2, "sell"),
    (0.2, "hold"),
    (0.6, "buy"),
    (float("inf"), "strong_buy"),
)


# ---- Dataclasses -----------------------------------------------------------


@dataclass(frozen=True)
class IndicatorResult:
    """Normalised indicator signal in ``[-1, +1]`` plus a raw reading.

    ``value`` is the normalised signal used by the composite.
    ``raw`` carries the raw indicator reading (e.g. RSI=72.1) for UI/debug.
    ``insufficient_data`` is ``True`` when the input had fewer bars than the
    indicator's minimum window (per :data:`_MIN_BARS`). In that case
    ``value`` and ``raw`` are ``None``.
    """

    value: float | None
    raw: float | None
    insufficient_data: bool


@dataclass(frozen=True)
class TechnicalAnalysis:
    """Result of :func:`analyze_technical` — signals + composite."""

    rsi: IndicatorResult
    macd: IndicatorResult
    ma_alignment: IndicatorResult
    bollinger: IndicatorResult
    volume: IndicatorResult
    atr: IndicatorResult
    composite_score: float | None
    action: str | None
    bars_analyzed: int
    insufficient_data_flags: list[str] = field(default_factory=list)


# ---- Helpers ---------------------------------------------------------------


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _action_for(score: float) -> str:
    for threshold, label in _ACTION_THRESHOLDS:
        if score < threshold:
            return label
    return "strong_buy"  # pragma: no cover — unreachable; inf sentinel above


def _ensure_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalise an OHLCV frame.

    Accepts any DataFrame that has columns ``open, high, low, close, volume``
    (case-insensitive). Returns a float-typed copy sorted ascending by index.
    """
    required = {"open", "high", "low", "close", "volume"}
    cols = {c.lower(): c for c in df.columns}
    missing = required - set(cols)
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {sorted(missing)}")
    out = df.rename(columns={cols[c]: c for c in required}).copy()
    for c in ("open", "high", "low", "close", "volume"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.sort_index()
    out = out.dropna(subset=["open", "high", "low", "close", "volume"])
    return out


# ---- Indicator calculators -------------------------------------------------

# We hand-roll the indicators instead of importing ``pandas_ta.Strategy`` so
# the module has no hard import dependency on pandas-ta at analysis time.
# This matters for two reasons:
# 1. pandas-ta pins numpy<2 in some releases, which collides with the rest of
#    our stack. If that pin becomes a problem we can swap to an alternative
#    (ta-lib, vectorbt) without touching callers.
# 2. Tests run without installing pandas-ta (it's listed in pyproject but
#    CI may skip it); these calculations are standard math.


def _rsi_signal(close: pd.Series, period: int = 14) -> tuple[float, float]:
    """Return ``(normalised_signal, raw_rsi)`` for the latest bar.

    Normalisation: RSI>70 is overbought (bearish, negative signal); RSI<30 is
    oversold (bullish, positive signal); 50 is neutral. We linearly map:
    RSI=30 → +1, RSI=50 → 0, RSI=70 → -1; values outside clamp.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    latest_gain = float(avg_gain.iloc[-1])
    latest_loss = float(avg_loss.iloc[-1])
    # Classic RSI edge cases: no losses in window → RSI=100; no gains → RSI=0.
    if latest_loss == 0 and latest_gain == 0:
        latest = 50.0
    elif latest_loss == 0:
        latest = 100.0
    elif latest_gain == 0:
        latest = 0.0
    else:
        rs = latest_gain / latest_loss
        latest = 100.0 - (100.0 / (1.0 + rs))
    # Map RSI to signal: midpoint 50 → 0, deviations invert sign.
    # signal = (50 - rsi) / 20, clamped to [-1, +1].
    signal = _clamp((50.0 - latest) / 20.0)
    return signal, latest


def _macd_signal(close: pd.Series) -> tuple[float, float]:
    """Return ``(normalised_signal, raw_histogram)`` using 12/26/9 MACD.

    Normalisation: the MACD histogram can swing wildly depending on price
    scale, so we scale it by the current close and clip. A positive histogram
    with MACD above signal is bullish; negative is bearish.
    """
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=9, adjust=False).mean()
    histogram = macd - signal_line
    latest_hist = float(histogram.iloc[-1])
    latest_close = float(close.iloc[-1])
    if latest_close == 0:
        return 0.0, latest_hist
    # Scale histogram by 1% of price; above that we saturate the signal.
    scaled = latest_hist / (latest_close * 0.01)
    signal = _clamp(scaled / 3.0)  # histogram ≥ 3% of price → full signal
    return signal, latest_hist


def _ma_alignment_signal(close: pd.Series) -> tuple[float, float]:
    """Moving-average alignment across SMA20 / SMA50 / SMA200.

    Scoring:
    * 20 > 50 > 200: fully bullish (+1)
    * 200 > 50 > 20: fully bearish (-1)
    * Mixed orderings interpolate: we score each of the 3 pairwise comparisons
      (20 vs 50, 50 vs 200, 20 vs 200) with +1/3 if the shorter MA is higher,
      -1/3 otherwise.
    The "raw" reading is the SMA20 value for UI display.
    """
    sma20 = close.rolling(20).mean().iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]
    comparisons = [
        1 if sma20 > sma50 else -1,
        1 if sma50 > sma200 else -1,
        1 if sma20 > sma200 else -1,
    ]
    signal = sum(comparisons) / 3.0
    return _clamp(signal), float(sma20)


def _bollinger_signal(close: pd.Series, period: int = 20, std: float = 2.0) -> tuple[float, float]:
    """Bollinger Bands: position within the band maps to signal.

    Normalisation: ``%B = (close - lower) / (upper - lower)``.
    %B=0 (at lower band) → +1 (oversold, bullish).
    %B=0.5 (middle) → 0.
    %B=1 (at upper band) → -1 (overbought, bearish).
    Values outside the bands clamp.
    """
    ma = close.rolling(period).mean()
    sd = close.rolling(period).std(ddof=0)
    upper = ma + std * sd
    lower = ma - std * sd
    latest_close = float(close.iloc[-1])
    latest_upper = float(upper.iloc[-1])
    latest_lower = float(lower.iloc[-1])
    if latest_upper == latest_lower:
        return 0.0, 0.5
    pct_b = (latest_close - latest_lower) / (latest_upper - latest_lower)
    signal = _clamp(1.0 - 2.0 * pct_b)
    return signal, float(pct_b)


def _volume_signal(volume: pd.Series, close: pd.Series) -> tuple[float, float]:
    """Relative volume vs 20-day average, weighted by price direction.

    A volume spike on an up day is bullish; on a down day it's bearish. The
    signal magnitude scales with how much above average the volume is,
    saturating at 3x average.
    """
    avg_vol = float(volume.rolling(20).mean().iloc[-1])
    latest_vol = float(volume.iloc[-1])
    if avg_vol <= 0:
        return 0.0, 1.0
    rel_vol = latest_vol / avg_vol
    # Direction: sign of today's return.
    ret = float(close.iloc[-1]) - float(close.iloc[-2])
    direction = 1.0 if ret > 0 else (-1.0 if ret < 0 else 0.0)
    # Magnitude: (rel_vol - 1) / 2, clamped so rel_vol=3 → full strength.
    magnitude = _clamp((rel_vol - 1.0) / 2.0, low=0.0, high=1.0)
    return _clamp(direction * magnitude), rel_vol


def _atr_signal(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> tuple[float, float]:
    """Average True Range as volatility signal.

    ATR is a magnitude, not a direction, so we map it to a bearish bias when
    volatility is elevated (high ATR typically accompanies uncertain /
    distribution markets). Normalisation: ATR / close ratio; 0.5% → 0,
    3%+ → -1 (very volatile, cautious). Low volatility gives a mild bullish
    tilt, capped at +0.3.
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    latest_atr = float(atr.iloc[-1])
    latest_close = float(close.iloc[-1])
    if latest_close == 0:
        return 0.0, latest_atr
    atr_pct = latest_atr / latest_close
    # Map 0.5% → +0.3, 1.5% → 0, 3% → -1.
    if atr_pct <= 0.015:
        signal = _clamp(0.3 - (atr_pct / 0.015) * 0.3)
    else:
        signal = _clamp(-((atr_pct - 0.015) / 0.015))
    return signal, atr_pct


# ---- Analysis orchestration ------------------------------------------------


def _insufficient(name: str) -> IndicatorResult:
    return IndicatorResult(value=None, raw=None, insufficient_data=True)


def analyze_technical(ohlcv: pd.DataFrame) -> TechnicalAnalysis:
    """Compute the 6-indicator technical analysis on an OHLCV frame.

    ``ohlcv`` must have columns ``open, high, low, close, volume`` and should
    be sorted ascending by date (index). Extra columns are ignored. At least
    :data:`_MIN_BARS_FOR_ANY_ANALYSIS` rows are required; fewer will return a
    ``TechnicalAnalysis`` with every indicator flagged insufficient and
    ``composite_score=None``.
    """
    frame = _ensure_ohlcv(ohlcv)
    n = len(frame)

    # Not enough data for any indicator → short-circuit.
    if n < _MIN_BARS_FOR_ANY_ANALYSIS:
        return TechnicalAnalysis(
            rsi=_insufficient("rsi"),
            macd=_insufficient("macd"),
            ma_alignment=_insufficient("ma_alignment"),
            bollinger=_insufficient("bollinger"),
            volume=_insufficient("volume"),
            atr=_insufficient("atr"),
            composite_score=None,
            action=None,
            bars_analyzed=n,
            insufficient_data_flags=list(_MIN_BARS.keys()),
        )

    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    vol = frame["volume"].astype(float)

    results: dict[str, IndicatorResult] = {}
    flags: list[str] = []

    def _calc(name: str, fn: Any) -> None:
        if n < _MIN_BARS[name]:
            results[name] = _insufficient(name)
            flags.append(name)
            return
        try:
            signal, raw = fn()
        except Exception:  # pragma: no cover — defensive; pandas math rarely raises here
            logger.exception("technical.%s failed", name)
            results[name] = _insufficient(name)
            flags.append(name)
            return
        # pandas rolling/EWM may produce NaN at the head of the series even
        # when length is sufficient. Treat NaN as insufficient rather than
        # emitting a bogus 0 signal.
        if signal != signal or raw != raw:  # NaN check (NaN != NaN)
            results[name] = _insufficient(name)
            flags.append(name)
            return
        results[name] = IndicatorResult(
            value=float(signal), raw=float(raw), insufficient_data=False
        )

    _calc("rsi", lambda: _rsi_signal(close))
    _calc("macd", lambda: _macd_signal(close))
    _calc("ma_alignment", lambda: _ma_alignment_signal(close))
    _calc("bollinger", lambda: _bollinger_signal(close))
    _calc("volume", lambda: _volume_signal(vol, close))
    _calc("atr", lambda: _atr_signal(high, low, close))

    # Composite with re-normalised weights.
    scored = {k: r for k, r in results.items() if not r.insufficient_data and r.value is not None}
    if not scored:
        composite: float | None = None
        action: str | None = None
    else:
        total_w = sum(_WEIGHTS[k] for k in scored)
        weighted = sum((scored[k].value * _WEIGHTS[k] for k in scored), 0.0)  # type: ignore[operator]
        composite = _clamp(weighted / total_w) if total_w > 0 else None
        action = _action_for(composite) if composite is not None else None

    return TechnicalAnalysis(
        rsi=results["rsi"],
        macd=results["macd"],
        ma_alignment=results["ma_alignment"],
        bollinger=results["bollinger"],
        volume=results["volume"],
        atr=results["atr"],
        composite_score=composite,
        action=action,
        bars_analyzed=n,
        insufficient_data_flags=flags,
    )


# ---- Redis caching ---------------------------------------------------------


def _cache_key(instrument_id: UUID | str, indicator: str) -> str:
    return f"tech:{instrument_id}:{indicator}"


def _serialize_indicator(r: IndicatorResult) -> str:
    return json.dumps(
        {
            "value": r.value,
            "raw": r.raw,
            "insufficient_data": r.insufficient_data,
        }
    )


def _deserialize_indicator(payload: str) -> IndicatorResult:
    data = json.loads(payload)
    return IndicatorResult(
        value=data["value"],
        raw=data["raw"],
        insufficient_data=bool(data["insufficient_data"]),
    )


async def cache_indicators(
    redis: Redis,
    instrument_id: UUID | str,
    analysis: TechnicalAnalysis,
    ttl_seconds: int = _CACHE_TTL_SECONDS,
) -> None:
    """Write each indicator to Redis under ``tech:{instrument_id}:{name}``.

    Only writes indicators with sufficient data. Insufficient-data results
    are intentionally NOT cached — we'd rather re-attempt on the next call
    (new data may have arrived) than serve a stale "insufficient" verdict.
    """
    for name in _WEIGHTS:
        result: IndicatorResult = getattr(analysis, name)
        if result.insufficient_data:
            continue
        await redis.set(
            _cache_key(instrument_id, name),
            _serialize_indicator(result),
            ex=ttl_seconds,
        )


async def load_cached_indicators(
    redis: Redis,
    instrument_id: UUID | str,
) -> dict[str, IndicatorResult]:
    """Return a ``{name: IndicatorResult}`` dict of whatever is cached.

    Missing keys are simply absent from the returned dict. Callers merge
    cache hits with freshly-computed indicators as needed.
    """
    out: dict[str, IndicatorResult] = {}
    for name in _WEIGHTS:
        payload = await redis.get(_cache_key(instrument_id, name))
        if payload is None:
            continue
        try:
            out[name] = _deserialize_indicator(payload)
        except (ValueError, KeyError):
            # Corrupt cache entry — ignore and let a fresh compute overwrite it.
            logger.warning("corrupt tech cache entry for %s:%s", instrument_id, name)
    return out


async def analyze_with_cache(
    redis: Redis,
    instrument_id: UUID | str,
    ohlcv: pd.DataFrame,
    ttl_seconds: int = _CACHE_TTL_SECONDS,
) -> TechnicalAnalysis:
    """Cache-aware wrapper around :func:`analyze_technical`.

    Strategy: if ALL 6 indicators are cache-hits, rebuild a
    :class:`TechnicalAnalysis` from the cached values and recompute only the
    composite (cheap). Otherwise compute everything from scratch and write
    the fresh indicators back to the cache.

    This keeps the cache semantics simple — we never mix stale and fresh
    indicators in a single composite. A partial cache hit falls through to
    a full recompute, which is the correct behaviour when TTL expiries
    interleave.
    """
    cached = await load_cached_indicators(redis, instrument_id)
    if len(cached) == len(_WEIGHTS):
        return _assemble_from_cache(cached, ohlcv)

    analysis = analyze_technical(ohlcv)
    await cache_indicators(redis, instrument_id, analysis, ttl_seconds=ttl_seconds)
    return analysis


def _assemble_from_cache(
    cached: dict[str, IndicatorResult], ohlcv: pd.DataFrame
) -> TechnicalAnalysis:
    """Rebuild a :class:`TechnicalAnalysis` from a full cache hit.

    Bars-analyzed and insufficient flags come from the input frame because
    the cache doesn't store those — they describe the current call, not the
    cached indicators.
    """
    frame = _ensure_ohlcv(ohlcv)
    flags = [name for name, r in cached.items() if r.insufficient_data]

    scored = {k: r for k, r in cached.items() if not r.insufficient_data and r.value is not None}
    if not scored:
        composite: float | None = None
        action: str | None = None
    else:
        total_w = sum(_WEIGHTS[k] for k in scored)
        weighted = sum((scored[k].value * _WEIGHTS[k] for k in scored), 0.0)  # type: ignore[operator]
        composite = _clamp(weighted / total_w) if total_w > 0 else None
        action = _action_for(composite) if composite is not None else None

    return TechnicalAnalysis(
        rsi=cached["rsi"],
        macd=cached["macd"],
        ma_alignment=cached["ma_alignment"],
        bollinger=cached["bollinger"],
        volume=cached["volume"],
        atr=cached["atr"],
        composite_score=composite,
        action=action,
        bars_analyzed=len(frame),
        insufficient_data_flags=flags,
    )


# ---- Data loading ----------------------------------------------------------


async def load_ohlcv_from_db(
    session: Any,
    instrument_id: UUID,
    bars: int = 252,
) -> pd.DataFrame:
    """Load the last ``bars`` OHLCV rows for ``instrument_id`` from Postgres.

    Returned frame is indexed by ``timestamp`` and sorted ascending.
    ``session`` is an async SQLAlchemy session. Imported lazily to keep this
    module usable from pure-python test paths that don't touch the DB.
    """
    from backend.app.models.price_history import PriceHistory
    from sqlalchemy import select

    stmt = (
        select(
            PriceHistory.timestamp,
            PriceHistory.open,
            PriceHistory.high,
            PriceHistory.low,
            PriceHistory.close,
            PriceHistory.volume,
        )
        .where(PriceHistory.instrument_id == instrument_id)
        .order_by(PriceHistory.timestamp.desc())
        .limit(bars)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    # Rows come back newest-first; flip to ascending for TA.
    rows = list(reversed(rows))
    df = pd.DataFrame(
        rows, columns=["timestamp", "open", "high", "low", "close", "volume"]
    ).set_index("timestamp")
    # Convert Decimal → float for pandas-ta consumption.
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].apply(lambda v: float(v) if isinstance(v, Decimal) else v)
    df["volume"] = df["volume"].astype(float)
    return df


async def load_close_series_bulk(
    session: Any,
    instrument_ids: list[UUID],
    bars: int = 252,
) -> dict[UUID, pd.Series]:
    """Load close-price Series for many instruments in one round-trip.

    Returns a dict keyed by instrument_id; instruments with no price history
    are simply absent from the dict. Per-instrument limit is applied with a
    window function so a portfolio of 20 holdings doesn't pull 20 * 252 rows
    from a single large IN-query. Used by the portfolio-level Risk Meter and
    Health Score endpoints to avoid N+1 queries across holdings.
    """
    if not instrument_ids:
        return {}
    from backend.app.models.price_history import PriceHistory
    from sqlalchemy import func, select

    # Row-numbered subquery: pick the latest ``bars`` rows per instrument.
    row_num = (
        func.row_number()
        .over(
            partition_by=PriceHistory.instrument_id,
            order_by=PriceHistory.timestamp.desc(),
        )
        .label("rn")
    )
    subq = (
        select(
            PriceHistory.instrument_id,
            PriceHistory.timestamp,
            PriceHistory.close,
            row_num,
        )
        .where(PriceHistory.instrument_id.in_(instrument_ids))
        .subquery()
    )
    stmt = select(subq.c.instrument_id, subq.c.timestamp, subq.c.close).where(subq.c.rn <= bars)
    rows = (await session.execute(stmt)).all()
    if not rows:
        return {}
    df = pd.DataFrame(rows, columns=["instrument_id", "timestamp", "close"])
    df["close"] = df["close"].apply(lambda v: float(v) if isinstance(v, Decimal) else v)
    out: dict[UUID, pd.Series] = {}
    for instrument_id, group in df.groupby("instrument_id"):
        series = group.set_index("timestamp")["close"].sort_index().astype(float)
        out[instrument_id] = series
    return out


__all__ = [
    "IndicatorResult",
    "TechnicalAnalysis",
    "analyze_technical",
    "analyze_with_cache",
    "cache_indicators",
    "load_cached_indicators",
    "load_close_series_bulk",
    "load_ohlcv_from_db",
]
