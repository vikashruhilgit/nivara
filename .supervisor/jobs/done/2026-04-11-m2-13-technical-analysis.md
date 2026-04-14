# Supervisor Job: Technical Analysis Engine (pandas-ta Indicators + Composite Scoring)

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected clean, branch: `feat/m2-13-technical-analysis`
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Month 1 complete (database with price_history, instruments tables). Job 9 (DataProvider/Yahoo) is in same batch — this job reads from price_history table which Job 9 populates. Can develop against test fixtures independently.

## Task
**Goal:** Build the technical analysis engine using pandas-ta to compute 6 weighted indicators: RSI (20%), MACD (20%), MA alignment (25%), Bollinger Bands (15%), Volume (10%), ATR (10%). Produce a composite technical score from -1 to +1 mapping to Strong Sell / Sell / Hold / Buy / Strong Buy. Read OHLCV data from price_history table. Cache individual indicator results in Redis (key: tech:{instrument_id}:{name}, TTL: 5min). Expose API endpoint: GET /api/analysis/{symbol}/technical.

**Problem Statement:**
Technical analysis is 40% of the MVP recommendation composite score (the largest single component). Without it, the recommendation engine has no price-action signal. pandas-ta provides deterministic, reproducible indicator calculations at zero cost. The composite scoring system converts raw indicator values into actionable signals with clear thresholds. Caching at 5-min TTL balances freshness with computation cost during active trading sessions.

## Acceptance Criteria
- [ ] Given 252 days of AAPL OHLCV, when technical analysis runs, then returns all 6 indicators (RSI, MACD, MA alignment, Bollinger Bands, Volume, ATR) + composite score (-1 to +1)
- [ ] Given composite score, then maps to action: <-0.6 Strong Sell, -0.6 to -0.2 Sell, -0.2 to 0.2 Hold, 0.2 to 0.6 Buy, >0.6 Strong Buy
- [ ] Given cached indicators <5min old, then returns from Redis (key: tech:{instrument_id}:{name})
- [ ] Given insufficient data (<30 days), then returns partial analysis with "insufficient data" flags on indicators requiring more history

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | Individual indicator calculators | AC #1 | 1 modify (`pyproject.toml` — add pandas-ta), 1 create (`backend/app/analysis/technical.py`) | pandas-ta, pandas | LAUNCHABLE |
| 2 | Composite scoring + action mapping | AC #1, #2 | 1 modify (`backend/app/analysis/technical.py` — add scoring), 0 create | Weighted scoring, threshold mapping | BLOCKED (by #1) |
| 3 | Insufficient data handling | AC #4 | 1 modify (`backend/app/analysis/technical.py` — add guards), 0 create | Data validation | BLOCKED (by #1) |
| 4 | Redis caching layer | AC #3 | 1 modify (`backend/app/analysis/technical.py` — add caching), 0 create | Redis TTL patterns | BLOCKED (by #1) |
| 5 | API endpoint + tests | All ACs | 1 modify (`main.py` or `backend/app/api/analysis.py` — add technical route), 2 create (`backend/tests/test_technical.py`, `backend/tests/test_technical_api.py`) | FastAPI, pytest | BLOCKED (by #2, #3, #4) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (indicators) ──┬──→ Subtask 2 (composite scoring) ──→ Subtask 5 (API + tests)
                         ├──→ Subtask 3 (insufficient data) ──┘
                         └──→ Subtask 4 (Redis caching) ──────┘
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 2 | Subtask 3 | `technical.py` | YES |
| Subtask 2 | Subtask 4 | `technical.py` | YES |
| Subtask 3 | Subtask 4 | `technical.py` | YES |

Note: Subtasks 2, 3, 4 all modify `technical.py` — must serialize. Single worker handles all three sequentially after Subtask 1.

### Batch Plan
- **Batch 1:** Subtask 1 (indicator calculators)
- **Batch 2:** Subtask 2, 3, 4 (sequential — all modify technical.py)
- **Batch 3:** Subtask 5 (API + tests)
- **Recommended workers:** 1 (single file dominates; parallelism limited)
- **Estimated batches:** 3

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | pandas-ta (RSI, MACD, SMA/EMA, Bollinger Bands, Volume indicators, ATR), pandas DataFrame |
| 2 | Weighted composite scoring, normalization to [-1, +1] range |
| 3 | Data length validation, partial result patterns |
| 4 | Redis caching (key: tech:{instrument_id}:{name}, TTL: 5min per TechSpec 9.1) |
| 5 | FastAPI router, Pydantic response schema, pytest with OHLCV fixtures |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| pandas-ta may not be actively maintained | LOW | Library is stable for standard indicators; pin version; indicators are standard math — can reimplement if needed |
| Indicator normalization to [-1, +1] requires careful calibration | MEDIUM | Use established signal interpretation (RSI >70 = overbought = negative signal, etc.); document thresholds |
| 5-min cache TTL may be too aggressive during volatile markets | LOW | TTL is configurable; 5min balances freshness vs computation; can adjust per-market |
| MA alignment calculation needs clear definition (which MAs, crossover vs slope) | MEDIUM | Define: SMA20 vs SMA50 vs SMA200 alignment; bullish = 20>50>200, bearish = reverse |
| Volume indicator interpretation varies (relative volume vs absolute) | LOW | Use relative volume (current vs 20-day average); normalize to signal strength |
| Corporate action adjustments (Job 11) invalidate cached indicators | LOW | Job 11 handles cache invalidation via Redis key pattern deletion (tech:{instrument_id}:*) |

## Configuration
- **Workers:** 1
- **Mode:** sequential (single file dominates work)
- **Estimated batches:** 3
- **Branch:** `feat/m2-13-technical-analysis`
- **Batch:** 5 (parallel with Jobs 9, 10, 11, 12; blocked by Month 1 completion)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-m2-13-technical-analysis.md
```

## Outcome
- **Status:** completed
- **Completed:** 2026-04-14T00:00:00Z
- **PR:** https://github.com/vikashruhilgit/nivara/pull/13
- **Branch:** feat/m2-13-technical-analysis
- **Files changed:** 7 (pyproject.toml, uv.lock, backend/app/api/analysis.py, backend/app/analysis/technical.py, backend/tests/test_technical.py, backend/tests/test_technical_api.py, job brief)
- **Heal loop ran:** true
- **Heal decision:** PASS
- **Heal iterations:** 0 (inline integration review; no fixable new+HIGH issues found)
- **Summary:** Technical analysis engine with 6 pandas-ta indicators, composite scoring, Redis caching (5m TTL), and FastAPI endpoint. Resumed session fixed two regressions: (1) pyproject requires-python bumped to >=3.12 so pandas-ta resolves cleanly; (2) one mypy `sum()` generator-type ambiguity. Redis DI via `Depends(get_redis)` was already correctly applied by the prior worker. All 207 backend tests pass; ruff + mypy clean. Follow-up: CLAUDE.md still says Python 3.11 — needs doc update.
