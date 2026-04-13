# Supervisor Job: Instruments & Symbol Mapping

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected initialized (by Job 1)
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Job 2 (database) must be complete (needs instruments, symbol_mappings tables)

## Task
**Goal:** Build the instruments service that resolves (exchange, symbol) to instrument_id (creating if missing), symbol mapping lookup used by normalize_symbol(), data symbol resolution (e.g., RELIANCE -> RELIANCE.NS for Yahoo Finance), and API endpoints for instrument lookup.

**Problem Statement:**
Every part of the platform (broker sync, data fetching, analysis, portfolio display) needs a canonical instrument identity. Without this service, broker-specific symbols cannot be mapped to a common representation, and data providers cannot be queried correctly. This is used by portfolio sync (Job 8) and all future data/analysis jobs.

## Acceptance Criteria
- [ ] Given AAPL on XNAS, when resolved via instruments service, then returns existing instrument_id from seeded data
- [ ] Given unknown symbol (e.g., MSFT on XNAS), when resolved, then creates new instrument + mapping and returns new instrument_id
- [ ] Given broker_symbol "RELIANCE" on Zerodha, when normalized via normalize_symbol(), then maps to instrument (RELIANCE, XNSE)
- [ ] Given instrument (RELIANCE, XNSE), when data_symbol requested, then returns "RELIANCE.NS" for Yahoo Finance
- [ ] Given GET /api/instruments/search?q=AAPL, then returns matching instruments with exchange and symbol info
- [ ] Given GET /api/instruments/{id}, then returns instrument details including all symbol mappings

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | Instruments service (resolve, create-if-missing) | AC #1, #2 | 0 modify, 2 create (backend/app/services/instruments.py, backend/app/schemas/instrument.py) | — | LAUNCHABLE |
| 2 | Symbol mapping resolver | AC #3, #4 | 0 modify, 1 create (backend/app/services/symbol_mapping.py) | — | LAUNCHABLE |
| 3 | Instrument API endpoints | AC #5, #6 | 1 modify (main.py — register router), 1 create (backend/app/api/instruments.py) | — | BLOCKED (by #1, #2) |
| 4 | Tests | AC #1–6 | 0 modify, 2 create (backend/tests/test_instruments.py, backend/tests/test_symbol_mapping.py) | — | BLOCKED (by #3) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (instruments service) ──┬──→ Subtask 3 (API endpoints) ──→ Subtask 4 (tests)
Subtask 2 (symbol mapping) ───────┘
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | none | NO |

### Batch Plan
- **Batch 1:** Subtask 1, 2 (parallel)
- **Batch 2:** Subtask 3 (depends on 1, 2)
- **Batch 3:** Subtask 4 (depends on 3)
- **Recommended workers:** 2
- **Estimated batches:** 3

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | SQLAlchemy 2.x async queries, upsert patterns |
| 2 | Lookup table patterns |
| 3 | FastAPI router, query parameter patterns |
| 4 | pytest-asyncio |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Symbol mapping data may be incomplete for all brokers | LOW | Start with seeded data from Job 2; auto-create on first encounter |
| Yahoo Finance data_symbol format may vary for some exchanges | MEDIUM | Document mapping convention (e.g., .NS for NSE, .BO for BSE) in code comments |
| Concurrent create-if-missing could cause duplicates | MEDIUM | Use database UNIQUE constraint + INSERT ON CONFLICT DO NOTHING |

## Configuration
- **Workers:** 2
- **Mode:** parallel
- **Estimated batches:** 3
- **Branch:** `feat/m1-5-instruments`
- **Batch:** 2 (parallel with Jobs 4, 6, 7; blocked by Job 2)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-10-m1-5-instruments.md
```

## Outcome
- **Status:** completed
- **Completed:** 2026-04-13T00:00:00Z
- **PR:** https://github.com/vikashruhilgit/nivara/pull/5
- **Branch:** feat/m1-5-instruments
- **Files changed:** 7 (5 created, 2 modified) — +1005 lines
- **Heal loop ran:** true
- **Heal decision:** PASS
- **Heal iterations:** 0
- **Summary:** Implemented InstrumentsService (resolve-or-create with ON CONFLICT DO NOTHING), SymbolMappingService (normalize_symbol + data_symbol for Yahoo), and /api/instruments router (resolve, search, detail, data-symbol). All 6 ACs covered by 18 new tests; full suite 61/61 passing; ruff, mypy --strict, format checks clean. Integration self-review PASSED with 0 fixes.
