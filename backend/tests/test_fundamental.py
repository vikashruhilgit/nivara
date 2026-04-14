"""Tests for :func:`backend.app.analysis.fundamental.score_fundamentals`.

Exercises the 0-100 mapping for each component, the weighted composite, and
graceful degradation under partial data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from backend.app.analysis.fundamental import score_fundamentals
from backend.app.data.edgar import EdgarFundamentals


def _edgar(**overrides) -> EdgarFundamentals:
    base = {
        "symbol": "AAPL",
        "cik": "0000320193",
        "filing_date": None,
        "revenue_ttm": None,
        "revenue_prior_ttm": None,
        "earnings_ttm": None,
        "earnings_prior_ttm": None,
        "pe_ratio": None,
        "debt_to_equity": None,
        "free_cash_flow": None,
        "eps": None,
        "fetched_at": datetime.now(UTC),
    }
    base.update(overrides)
    return EdgarFundamentals(**base)


def test_revenue_growth_positive_scores_high():
    f = _edgar(
        revenue_ttm=Decimal("130"),
        revenue_prior_ttm=Decimal("100"),  # +30% YoY hits top of window
    )
    out = score_fundamentals(f)
    assert out.revenue_growth == 100
    # only one component scorable → composite equals it.
    assert out.composite == 100


def test_revenue_growth_decline_scores_zero():
    f = _edgar(revenue_ttm=Decimal("90"), revenue_prior_ttm=Decimal("100"))
    out = score_fundamentals(f)
    # -10% → clamp to 0
    assert out.revenue_growth == 0


def test_pe_valuation_low_is_cheap_scores_high():
    f = _edgar(pe_ratio=Decimal("10"))
    out = score_fundamentals(f)
    assert out.pe_valuation == 100


def test_pe_valuation_high_is_expensive_scores_low():
    f = _edgar(pe_ratio=Decimal("40"))
    out = score_fundamentals(f)
    assert out.pe_valuation == 0


def test_negative_pe_is_not_scored():
    # Loss-making firms should not be rewarded or penalised arbitrarily.
    f = _edgar(pe_ratio=Decimal("-5"))
    out = score_fundamentals(f)
    assert out.pe_valuation is None


def test_pe_derived_from_price_and_eps_when_missing():
    f = _edgar(eps=Decimal("5"))
    out = score_fundamentals(f, price=Decimal("100"))
    # P/E = 20 → midway between 10 and 40 → 66
    assert out.pe_valuation is not None
    assert 60 <= out.pe_valuation <= 70


def test_debt_health_inverted():
    f_clean = _edgar(debt_to_equity=Decimal("0"))
    f_risky = _edgar(debt_to_equity=Decimal("2"))
    assert score_fundamentals(f_clean).debt_health == 100
    assert score_fundamentals(f_risky).debt_health == 0


def test_cash_flow_margin_scored():
    # FCF 20 on revenue 100 → margin 20% → top of window.
    f = _edgar(revenue_ttm=Decimal("100"), free_cash_flow=Decimal("20"))
    out = score_fundamentals(f)
    assert out.cash_flow == 100


def test_composite_re_normalises_under_partial_data():
    # Only revenue_growth available: composite should equal it, not be diluted
    # by missing weights.
    f = _edgar(revenue_ttm=Decimal("100"), revenue_prior_ttm=Decimal("90"))
    out = score_fundamentals(f)
    assert out.revenue_growth is not None
    assert out.composite == out.revenue_growth


def test_composite_none_when_no_data():
    out = score_fundamentals(_edgar())
    assert out.composite is None


def test_earnings_trend_handles_negative_prior():
    # Prior loss → using abs(prior) in denominator yields sensible positive growth.
    f = _edgar(earnings_ttm=Decimal("50"), earnings_prior_ttm=Decimal("-100"))
    out = score_fundamentals(f)
    assert out.earnings_trend == 100


def test_weighted_composite_applies_full_weight_vector():
    # Construct a case where every component scores 100 so composite is 100.
    f = _edgar(
        revenue_ttm=Decimal("130"),
        revenue_prior_ttm=Decimal("100"),
        earnings_ttm=Decimal("130"),
        earnings_prior_ttm=Decimal("100"),
        debt_to_equity=Decimal("0"),
        pe_ratio=Decimal("10"),
        # FCF/revenue ≥ 20% → top of cash_flow window (130 * 0.2 = 26).
        free_cash_flow=Decimal("26"),
    )
    out = score_fundamentals(f)
    assert out.revenue_growth == 100
    assert out.earnings_trend == 100
    assert out.debt_health == 100
    assert out.pe_valuation == 100
    assert out.cash_flow == 100
    assert out.composite == 100
