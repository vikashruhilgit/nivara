# Supervisor Job: DataProvider Abstraction + Yahoo Finance Implementation

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected clean, branch: `feat/m2-9-data-provider-yahoo`
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Month 1 complete (database with instruments, symbol_mappings, price_history tables; broker adapter; market calendar)

## Task
**Goal:** Create the DataProvider abstraction layer (base.py with get_ohlcv, get_fundamentals, get_quote interfaces) and a Yahoo Finance implementation using yfinance, with Redis caching (OHLCV 1h TTL, fundamentals 24h TTL) and storage of OHLCV data in the price_history table (partitioned by month).

**Problem Statement:**
The analysis engine needs historical price data and fundamentals to compute technical indicators, fundamental scores, and risk models. Without a data layer, no analysis is possible. The DataProvider abstraction allows swapping Yahoo Finance (free, ToS risk) for Polygon.io ($29/mo) later without changing consumers. Yahoo has a 15-minute delay and no official API (yfinance scrapes internal endpoints), so caching and error handling are critical.

## Acceptance Criteria
- [ ] Given DataProvider interface, when YahooProvider.get_ohlcv("AAPL", 252 days), then returns DataFrame with OHLCV columns stored in price_history
- [ ] Given cached data <1h old, when get_ohlcv called, then returns from Redis (no Yahoo API call)
- [ ] Given Yahoo unavailable, when get_ohlcv called, then raises DataProviderError with clear message
- [ ] Given instrument with data_symbol mapping, when fetching, then uses correct Yahoo symbol (e.g., RELIANCE.NS)
- [ ] Given fundamentals request, when cached data <24h old, then returns from Redis cache
- [ ] Given get_quote called, when Yahoo responds, then returns current price with 15-min delay disclaimer

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | DataProvider abstract base + errors | AC #1, #3 | 0 modify, 3 create (`backend/app/data/__init__.py`, `backend/app/data/base.py`, `backend/app/data/errors.py`) | Python ABC, Pydantic v2 | LAUNCHABLE |
| 2 | Yahoo Finance provider implementation | AC #1, #3, #4, #6 | 1 modify (`pyproject.toml` — add yfinance), 1 create (`backend/app/data/yahoo.py`) | yfinance SDK | BLOCKED (by #1) |
| 3 | Redis caching layer for data providers | AC #2, #5 | 0 modify, 1 create (`backend/app/data/cache.py`) | Redis caching patterns | BLOCKED (by #1) |
| 4 | Price history storage (DB write pipeline) | AC #1 | 1 modify (ensure price_history model exists), 1 create (`backend/app/data/storage.py`) | SQLAlchemy async, partitioned tables | BLOCKED (by #2) |
| 5 | Integration + symbol mapping resolution | AC #4 | 0 modify, 0 create (wiring in yahoo.py) | — | BLOCKED (by #2) |
| 6 | Tests | All ACs | 0 modify, 2 create (`backend/tests/test_data_provider.py`, `backend/tests/test_yahoo_provider.py`) | pytest, pytest-asyncio | BLOCKED (by #2, #3, #4) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (abstract base) ──┬──→ Subtask 2 (Yahoo impl) ──→ Subtask 4 (DB storage) ──→ Subtask 6 (tests)
                            └──→ Subtask 3 (Redis cache) ──────────────────────────────┘
                                 Subtask 5 (symbol mapping) ────────────────────────────┘
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 3 | none | NO |
| Subtask 2 | Subtask 3 | none | NO |
| Subtask 2 | Subtask 4 | none | NO |

### Batch Plan
- **Batch 1:** Subtask 1 (abstract base)
- **Batch 2:** Subtask 2, 3 (parallel — Yahoo impl + cache layer)
- **Batch 3:** Subtask 4, 5 (DB storage + symbol mapping wiring)
- **Batch 4:** Subtask 6 (tests)
- **Recommended workers:** 2
- **Estimated batches:** 4

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | Python ABC patterns, Pydantic v2 schemas |
| 2 | yfinance SDK, pandas DataFrame handling |
| 3 | Redis caching with TTL, key patterns from TechSpec 9.1 |
| 4 | SQLAlchemy async bulk insert, partitioned tables |
| 6 | pytest-asyncio, mock/patch for external APIs |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| yfinance breaks (no official API, scrapes Yahoo endpoints) | HIGH | DataProvider abstraction enables swap to Polygon.io; cache reduces call frequency |
| Yahoo ToS prohibits automated scraping | MEDIUM | Cache aggressively (1h OHLCV, 24h fundamentals); document risk; name Polygon.io as escape hatch |
| yfinance returns inconsistent data for Indian stocks | MEDIUM | Validate data_symbol mapping (RELIANCE.NS format); add data quality checks |
| Redis cache invalidation on corporate actions | LOW | Corporate actions job (Job 11) will call cache invalidation; design invalidation interface |
| price_history partitioning complexity | LOW | Month 1 should have created partitioned table; verify partition exists before insert |

## Configuration
- **Workers:** 2
- **Mode:** parallel
- **Estimated batches:** 4
- **Branch:** `feat/m2-9-data-provider-yahoo`
- **Batch:** 5 (parallel with Jobs 10, 11, 12, 13; blocked by Month 1 completion)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-m2-9-data-provider-yahoo.md
```

## Outcome
- **Status:** completed
- **Completed:** 2026-04-14T00:00:00Z
- **PR:** https://github.com/vikashruhilgit/nivara/pull/9
- **Branch:** feat/m2-9-data-provider-yahoo
- **Files changed:** 13 (8 new source/tests, 5 config/supervisor)
- **Heal loop ran:** true
- **Heal decision:** PASS
- **Heal iterations:** 0
- **Summary:** DataProvider ABC + YahooProvider implementation with Redis cache (OHLCV 1h / fundamentals 24h / quotes 1m TTLs per TechSpec §9.1), OHLCV ON CONFLICT DO UPDATE into price_history, and 34 new tests (120 total passing). Ruff + mypy --strict clean. Self-heal integration review passed with 0 iterations; no BLOCKING/HIGH issues.
