# Supervisor Job: Market Calendar Integration

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected initialized (by Job 1)
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Job 2 (database) must be complete (needs calendar_overrides table)

## Task
**Goal:** Wrap the exchange_calendars library (XBOM for NSE, XNYS, XNAS) and merge with calendar_overrides table (override wins). Provide helpers: is_market_open(exchange, ts_utc), next_session_close(exchange), get_session_hours(exchange, date). Create a weekly verification job stub and auto-create override on unexpected "market closed" from broker.

**Problem Statement:**
The session-aware scheduler (Celery jobs), portfolio sync timing, and future indicator recalculation all depend on knowing when markets are open. Without this, the platform cannot schedule jobs correctly, would waste resources polling closed markets, and would miss session-close triggers for post-market analysis.

## Acceptance Criteria
- [ ] Given Jan 1 (US holiday), when is_market_open("XNYS", ts_utc) called, then returns False
- [ ] Given July 4 (US holiday), when is_market_open("XNYS", ts_utc) called, then returns False
- [ ] Given calendar_override inserted for a custom holiday, when is_market_open() queried, then returns False for that date (override wins over library)
- [ ] Given Muhurat trading day (Diwali), when get_session_hours("XBOM", date) queried, then returns correct special session hours
- [ ] Given next_session_close("XNYS") called during market hours, then returns correct close time for today (handles half-days)
- [ ] Given unexpected "market closed" response from broker, when auto-override triggered, then calendar_overrides row created with reason

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | Calendar service (wrap exchange_calendars + override merge) | AC #1–4 | 1 modify (pyproject.toml — add exchange_calendars), 2 create (backend/app/services/calendar.py, backend/app/schemas/calendar.py) | — | LAUNCHABLE |
| 2 | Calendar API endpoints | AC #1–4 (via API) | 1 modify (main.py — register router), 1 create (backend/app/api/calendar.py) | — | BLOCKED (by #1) |
| 3 | Auto-override on broker "market closed" | AC #6 | 1 modify (backend/app/services/calendar.py — add method), 0 create | — | BLOCKED (by #1) |
| 4 | Weekly verification job stub | — (operational) | 0 modify, 1 create (backend/app/tasks/calendar_verify.py) | — | BLOCKED (by #1) |
| 5 | Tests | AC #1–6 | 0 modify, 1 create (backend/tests/test_calendar.py) | — | BLOCKED (by #1, #3) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (calendar service) ──┬──→ Subtask 2 (API endpoints)
                               ├──→ Subtask 3 (auto-override)
                               ├──→ Subtask 4 (verification job)
                               └──→ Subtask 5 (tests, also depends on #3)
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 2 | Subtask 3 | none | NO |
| Subtask 3 | Subtask 1 | calendar.py (modifies same file) | YES |

### Batch Plan
- **Batch 1:** Subtask 1 (foundation)
- **Batch 2:** Subtask 2, 3, 4 (parallel — 2 and 4 don't overlap with 3's calendar.py modification; but 3 modifies calendar.py so serialize with 1)
- **Batch 3:** Subtask 5 (tests, after all implementation)
- **Recommended workers:** 2
- **Estimated batches:** 3

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | exchange_calendars library API |
| 2 | FastAPI router patterns |
| 3 | Error handling, DB upsert |
| 4 | Celery periodic task patterns |
| 5 | pytest with date mocking |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| exchange_calendars may not have latest Indian holidays | MEDIUM | calendar_overrides table provides manual override; weekly verification catches gaps |
| Muhurat trading hours may not be in exchange_calendars | MEDIUM | Seed known Muhurat dates as calendar_overrides; verify annually |
| Timezone handling complexity (IST, ET, UTC) | HIGH | All internal timestamps UTC; convert only at display layer; use pytz/zoneinfo |
| exchange_calendars library version pinning | LOW | Pin in pyproject.toml; test with known holiday dates |

## Configuration
- **Workers:** 2
- **Mode:** parallel
- **Estimated batches:** 3
- **Branch:** `feat/m1-6-market-calendar`
- **Batch:** 2 (parallel with Jobs 4, 5, 7; blocked by Job 2)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-10-m1-6-market-calendar.md
```

## Outcome
- **Status:** completed
- **Completed:** 2026-04-14T00:00:00Z
- **PR:** https://github.com/vikashruhilgit/nivara/pull/6
- **Branch:** feat/m1-6-market-calendar
- **Files changed:** 10 (3 modified, 7 created)
- **Heal loop ran:** true
- **Heal decision:** PASS
- **Heal iterations:** 0
- **Heal fixable issues fixed:** 0
- **Heal remaining issues:** 0
- **Summary:** Implemented market calendar service wrapping exchange_calendars (XNYS/XNAS/XBOM) with calendar_overrides merge (override wins), FastAPI router at /api/calendar/* (is-open, session-hours, next-close) guarded by bearer auth, auto-override upsert on broker "market closed" reports (Postgres ON CONFLICT + SQLite fallback), and a Celery stub for the weekly verification job. All 6 ACs covered by 13 new tests (74 total pass); ruff/format/mypy clean. Resumed from mid-execution timeout — no code changes needed at resume, only quality gates, commit, push, PR. Self-heal holistic review passed without modifications.
