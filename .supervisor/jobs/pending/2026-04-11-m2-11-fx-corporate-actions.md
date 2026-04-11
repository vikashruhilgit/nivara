# Supervisor Job: FX Pipeline + Corporate Actions Detection & Adjustment

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected clean, branch: `feat/m2-11-fx-corporate-actions`
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Month 1 complete (database with fx_rates, corporate_actions, price_history, instruments tables; broker adapter for sync anomaly detection)

## Task
**Goal:** Build the FX pipeline (FRED API primary, ECB fallback) storing daily USD/INR rates in the fx_rates table with 6AM UTC daily refresh, and the corporate actions detection + adjustment pipeline. Corporate actions detection uses two sources: Yahoo adjustment factors on daily OHLCV refresh, and broker sync anomaly detection (position qty changed without matching order). The adjustment pipeline: detect action, record in corporate_actions table, multiply pre-ex-date OHLCV by adjustment factor, invalidate cached indicators, mark applied=true, log to audit trail.

**Problem Statement:**
Without FX rates, cross-currency portfolio metrics cannot be computed — Indian holdings cannot be displayed in USD (or vice versa), and portfolio-level benchmarking breaks. Without corporate actions handling, stock splits corrupt historical OHLCV data, breaking all technical indicators and P&L calculations. Both are foundational data integrity requirements that must be in place before Month 3's risk models and recommendation engine.

## Acceptance Criteria
- [ ] Given 6AM UTC, when FX refresh runs, then fx_rates has today's USD_INR rate from FRED (key: fx:USD_INR, TTL: 24h)
- [ ] Given FRED unavailable, when FX refresh runs, then falls back to ECB and logs warning
- [ ] Given stock split detected (adjustment factor != 1.0), then historical OHLCV adjusted (pre-ex-date prices multiplied by factor), indicators invalidated, corporate_actions record created with applied=true
- [ ] Given position qty changed without matching order in order history, then flagged as potential corporate action for review

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | FRED API client + FX service | AC #1, #2 | 0 modify, 2 create (`backend/app/data/fred.py`, `backend/app/services/fx.py`) | FRED API, HTTP client | LAUNCHABLE |
| 2 | ECB fallback for FX | AC #2 | 1 modify (`backend/app/services/fx.py` — add fallback logic), 0 create | ECB SDMX API | BLOCKED (by #1) |
| 3 | Corporate actions detection (Yahoo adj factors) | AC #3 | 0 modify, 1 create (`backend/app/services/corporate_actions.py`) | yfinance adjustment factors | LAUNCHABLE |
| 4 | Corporate actions detection (broker sync anomaly) | AC #4 | 1 modify (`backend/app/services/corporate_actions.py` — add anomaly detection), 0 create | Reconciliation logic | BLOCKED (by #3) |
| 5 | OHLCV adjustment pipeline + cache invalidation | AC #3 | 1 modify (`backend/app/services/corporate_actions.py` — add adjustment logic), 0 create | SQLAlchemy bulk update, Redis invalidation | BLOCKED (by #3) |
| 6 | Tests | All ACs | 0 modify, 3 create (`backend/tests/test_fx.py`, `backend/tests/test_corporate_actions.py`, `backend/tests/test_fred.py`) | pytest-asyncio | BLOCKED (by #1, #3, #4, #5) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (FRED client + FX) ──→ Subtask 2 (ECB fallback) ──→ Subtask 6 (tests)
Subtask 3 (Yahoo adj detection) ──┬──→ Subtask 4 (broker anomaly) ──→ Subtask 6
                                  └──→ Subtask 5 (OHLCV adjustment) ──→ Subtask 6
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 3 | none | NO |
| Subtask 3 | Subtask 4 | `corporate_actions.py` | YES |
| Subtask 3 | Subtask 5 | `corporate_actions.py` | YES |

### Batch Plan
- **Batch 1:** Subtask 1, 3 (parallel — FX + corporate actions detection)
- **Batch 2:** Subtask 2, 4, 5 (ECB fallback + anomaly detection + adjustment pipeline — serialize 4,5 due to shared file)
- **Batch 3:** Subtask 6 (tests)
- **Recommended workers:** 2
- **Estimated batches:** 3

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | FRED API (api.stlouisfed.org), series DEXINUS for USD/INR |
| 2 | ECB SDMX API (sdw-wsrest.ecb.europa.eu) |
| 3 | yfinance adjustment factors, split detection logic |
| 4 | Position/order reconciliation, anomaly detection |
| 5 | SQLAlchemy bulk UPDATE on price_history, Redis key pattern invalidation (tech:{instrument_id}:*) |
| 6 | pytest-asyncio, time mocking for scheduled tasks |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| FRED API requires free API key registration | LOW | Register at fred.stlouisfed.org; add FRED_API_KEY to env vars |
| ECB API returns XML (not JSON) | LOW | Use xmltodict or lxml for parsing; well-documented SDMX format |
| Yahoo adjustment factors may not cover all corporate actions (e.g., bonus issues for Indian stocks) | MEDIUM | Broker sync anomaly detection provides second detection path; manual override in corporate_actions table |
| Retroactive OHLCV adjustment on large history is expensive | MEDIUM | Limit adjustment to 2 years of history; use bulk UPDATE with WHERE clause on timestamp < ex_date |
| Cache invalidation for indicators must coordinate with technical analysis (Job 13) | MEDIUM | Use Redis key pattern deletion (tech:{instrument_id}:*); document invalidation contract |
| FX rate weekend/holiday gaps | LOW | Forward-fill: use most recent available rate for non-trading days |

## Configuration
- **Workers:** 2
- **Mode:** parallel
- **Estimated batches:** 3
- **Branch:** `feat/m2-11-fx-corporate-actions`
- **Batch:** 5 (parallel with Jobs 9, 10, 12, 13; blocked by Month 1 completion)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-m2-11-fx-corporate-actions.md
```
