# Supervisor Job: Portfolio Sync

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected initialized (by Job 1)
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisites:** Job 2 (database), Job 3 (auth), Job 4 (broker adapter), Job 5 (instruments) must all be complete

## Task
**Goal:** Implement portfolio sync endpoints: POST /api/portfolio/sync (manual trigger), GET /api/portfolio/summary (aggregated value in base currency, P&L), GET /api/portfolio/positions (all positions with native + base currency). Sync logic: fetch positions from broker via BrokerAdapter, resolve instrument_id via symbol mapping service, upsert positions by (broker_connection_id, instrument_id), mark missing positions as closed (qty=0), upsert orders by broker_order_id (never delete), write audit log entries. Stale threshold (2h) triggers confidence reduction.

**Problem Statement:**
The platform cannot show the user their portfolio without syncing data from their broker. This is the core value proposition of the MVP — connecting to a broker and displaying positions with cross-currency portfolio metrics. Without this, the app has auth but nothing to show. This job ties together broker adapters, instruments, database, and auth into the first end-to-end user flow.

## Acceptance Criteria
- [ ] Given Alpaca paper account with positions, when POST /api/portfolio/sync, then positions appear in DB with correct instrument_id resolution
- [ ] Given sync already ran, when POST /api/portfolio/sync again, then no duplicates created (idempotent upsert by broker_connection_id + instrument_id)
- [ ] Given position closed on Alpaca (no longer in broker response), when sync runs, then local position marked qty=0 (closed)
- [ ] Given orders on Alpaca, when sync runs, then orders upserted by broker_order_id (never deleted, status updated)
- [ ] Given GET /api/portfolio/summary, then returns total portfolio value in user's base currency + daily P&L (converted via fx_rates)
- [ ] Given GET /api/portfolio/positions, then returns all positions with fields in both native currency and base currency
- [ ] Given sync completed, then audit_log contains entry for the sync event with metadata
- [ ] Given last sync > 2 hours ago, then portfolio data flagged as stale with reduced confidence

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | Portfolio schemas (Pydantic v2) | — (supporting) | 0 modify, 1 create (backend/app/schemas/portfolio.py) | — | LAUNCHABLE |
| 2 | Portfolio sync service | AC #1–4, #7, #8 | 0 modify, 2 create (backend/app/services/portfolio_sync.py, backend/app/services/audit.py) | — | LAUNCHABLE |
| 3 | Portfolio summary service (base currency aggregation) | AC #5, #6 | 0 modify, 1 create (backend/app/services/portfolio_summary.py) | — | LAUNCHABLE |
| 4 | FX conversion utility | AC #5, #6 | 0 modify, 1 create (backend/app/services/fx.py) | — | LAUNCHABLE |
| 5 | Portfolio API endpoints | AC #1–8 | 1 modify (main.py — register router), 1 create (backend/app/api/portfolio.py) | — | BLOCKED (by #1, #2, #3) |
| 6 | Tests (sync idempotency, currency conversion, stale detection) | AC #1–8 | 0 modify, 2 create (backend/tests/test_portfolio_sync.py, backend/tests/test_portfolio_summary.py) | — | BLOCKED (by #5) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (schemas) ──────┐
Subtask 2 (sync service) ──┤──→ Subtask 5 (API endpoints) ──→ Subtask 6 (tests)
Subtask 3 (summary service)┤
Subtask 4 (FX utility) ────┘
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | none | NO |
| Subtask 2 | Subtask 3 | none | NO |
| Subtask 3 | Subtask 4 | none (4 is a utility used by 3) | NO |
| Subtask 1 | Subtask 3 | none | NO |

### Batch Plan
- **Batch 1:** Subtask 1, 2, 3, 4 (all parallel — no file overlap)
- **Batch 2:** Subtask 5 (depends on 1, 2, 3)
- **Batch 3:** Subtask 6 (depends on 5)
- **Recommended workers:** 3
- **Estimated batches:** 3

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | Pydantic v2 response models |
| 2 | SQLAlchemy upsert (INSERT ON CONFLICT), BrokerAdapter integration |
| 3 | Aggregation queries, FX conversion |
| 4 | FRED/ECB FX rate lookup, decimal arithmetic |
| 5 | FastAPI router, Depends() auth injection |
| 6 | pytest-asyncio, mock broker responses |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| FX rates not yet populated (fx_rates table empty on first sync) | HIGH | Seed USD_INR and INR_USD rates in Job 2 seed data; FX service fetches from FRED on first call |
| Alpaca paper account may have zero positions initially | LOW | Test with mock data; create paper positions via Alpaca dashboard before integration test |
| Position idempotency key uses instrument_id (resolved), not broker_symbol | MEDIUM | Resolve symbol BEFORE upsert; handle resolution failure gracefully (skip position, log warning) |
| Stale detection requires comparing timestamps | LOW | Use synced_at column on positions table; compare against 2h threshold |
| Concurrent sync requests for same user | MEDIUM | Use Redis lock per user_id during sync; second request returns "sync in progress" |

## Configuration
- **Workers:** 3
- **Mode:** parallel
- **Estimated batches:** 3
- **Branch:** `feat/m1-8-portfolio-sync`
- **Batch:** 3 (blocked by Jobs 2, 3, 4, 5)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-10-m1-8-portfolio-sync.md
```

## Outcome
- **Status:** completed
- **Completed:** 2026-04-14T00:00:00Z
- **PR:** https://github.com/vikashruhilgit/nivara/pull/8
- **Branch:** feat/m1-8-portfolio-sync
- **Files changed:** 9 (7 created, 2 modified in feat commit; 1 renamed in chore commit)
- **Heal loop ran:** true
- **Heal decision:** PASS
- **Heal iterations:** 0
- **Summary:** All 6 subtasks implemented. 22 new tests (9 sync + 13 summary), 86 total pass. Ruff + mypy --strict clean. Inline holistic SELF_HEAL review found no new BLOCKING/HIGH issues — conventions match existing m1-1 through m1-7 modules (bearer auth, async I/O, settings via get_settings, idempotency key = (broker_connection_id, instrument_id)). PR #8 opened against feat/m1-1-repo-scaffold.
