# Supervisor Job: Portfolio Intelligence (Mode D) — Diversification, Benchmarks, Alpha

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected initialized (by Job 1)
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Month 2 complete (portfolio sync, price_history, data pipelines, FX pipeline)

## Task
**Goal:** Implement Portfolio Intelligence (Mode D): diversification quality (sector concentration, geography split), sector allocation vs benchmark, per-market alpha (Indian holdings vs Nifty ^NSEI in INR, US holdings vs S&P ^GSPC in USD — no FX conflation), portfolio-level blended benchmark (IN allocation% x Nifty return in base currency + US allocation% x S&P return in base currency), performance attribution, and rebalancing suggestions (display only — no execution). Expose via GET /api/portfolio/intelligence.

**Problem Statement:**
Users with cross-market portfolios (India + US) need to understand their portfolio quality, diversification, and performance relative to appropriate benchmarks. Without portfolio intelligence, users cannot see sector concentration, compare to benchmarks, or get rebalancing suggestions. Currently, only raw positions and balances are available. Success looks like a comprehensive portfolio analysis with per-market alpha computed in native currencies to avoid FX conflation.

## Acceptance Criteria
- [ ] Given portfolio with AAPL + RELIANCE, when intelligence computed, then shows sector allocation for both US and Indian markets
- [ ] Given portfolio, when diversification computed, then shows sector concentration (HHI) and geography split (% IN, % US)
- [ ] Given Indian holdings, when alpha computed, then compared to Nifty 50 (^NSEI) in INR (no FX conversion)
- [ ] Given US holdings, when alpha computed, then compared to S&P 500 (^GSPC) in USD (no FX conversion)
- [ ] Given mixed portfolio (IN + US), when blended benchmark computed, then = (IN allocation% x Nifty return in base currency) + (US allocation% x S&P return in base currency)
- [ ] Given portfolio alpha computed, then = portfolio return minus blended benchmark return
- [ ] Given concentrated portfolio (>40% in one sector), then rebalancing suggestion generated (display only)
- [ ] Given GET /api/portfolio/intelligence, then returns diversification, sector allocation, per-market alpha, blended benchmark, and rebalancing suggestions
- [ ] Given rebalancing suggestions, then no execution actions — display only with disclaimer

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | Benchmark service (Nifty + S&P returns) | AC #3, #4, #5 | 0 modify, 2 create (backend/app/services/benchmark.py, backend/app/schemas/benchmark.py) | yfinance, pandas | LAUNCHABLE |
| 2 | Portfolio intelligence engine | AC #1, #2, #3, #4, #5, #6, #7, #9 | 0 modify, 2 create (backend/app/intelligence/portfolio.py, backend/app/schemas/portfolio_intelligence.py) | pandas, numpy, HHI | BLOCKED (by #1) |
| 3 | Portfolio intelligence API endpoint | AC #8 | 1 modify (backend/app/main.py — register router), 1 create (backend/app/api/portfolio_intelligence.py) | FastAPI | BLOCKED (by #2) |
| 4 | Tests | All ACs | 0 modify, 2 create (backend/tests/test_portfolio_intelligence.py, backend/tests/test_benchmark_service.py) | pytest | BLOCKED (by #3) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (benchmark service) ──→ Subtask 2 (intelligence engine) ──→ Subtask 3 (API) ──→ Subtask 4 (tests)
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | none | NO (but logical dep) |
| Subtask 2 | Subtask 3 | none | NO (but logical dep) |

### Batch Plan
- **Batch 1:** Subtask 1 (benchmark service)
- **Batch 2:** Subtask 2 (intelligence engine)
- **Batch 3:** Subtask 3 (API endpoint)
- **Batch 4:** Subtask 4 (tests)
- **Recommended workers:** 1
- **Estimated batches:** 4

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | yfinance (^NSEI, ^GSPC), pandas returns computation, FX rate lookup |
| 2 | HHI concentration, sector grouping, alpha = portfolio return - benchmark return |
| 3 | FastAPI router, Pydantic v2, JWT auth dependency |
| 4 | pytest, mock data fixtures |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Yahoo Finance ^NSEI data unreliable or delayed | MEDIUM | Cache benchmark returns daily; fallback to last known if fetch fails |
| FX conversion for blended benchmark requires fx_rates table populated | MEDIUM | Depend on Month 2 FX pipeline; fallback to hardcoded rate if missing |
| Sector data not available for all instruments | LOW | Default to "Unknown" sector; exclude from sector concentration if unknown |
| Rebalancing suggestions could be misinterpreted as advice | HIGH | Add prominent disclaimer: "For informational purposes only. Not investment advice." |

## Configuration
- **Workers:** 1
- **Mode:** sequential
- **Estimated batches:** 4
- **Branch:** `feat/m3-18-portfolio-intelligence`
- **Batch:** 7 (parallel with Jobs 15, 16, 17, 19)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-m3-18-portfolio-intelligence.md
```
