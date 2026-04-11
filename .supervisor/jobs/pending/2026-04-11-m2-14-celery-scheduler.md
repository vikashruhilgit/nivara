# Supervisor Job: Session-Aware Celery Beat Scheduler

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected clean, branch: `feat/m2-14-celery-scheduler`
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Month 1 complete (Celery+Redis infrastructure, market calendar, exchange_calendars integration). **Jobs 9-13 must be complete** — this job wires all data/analysis pipelines into the scheduler.

## Task
**Goal:** Build a session-aware Celery Beat scheduler that orchestrates all data and analysis pipelines based on market session state. In-session jobs (per-market): quote streaming trigger, 5-min indicator recalculation, hourly portfolio sync. Post-close jobs (triggered by session close event, not fixed cron): OHLCV fetch, fundamentals refresh, risk recalc, portfolio snapshot. Always-running jobs: news+sentiment every 15 min, FX daily at 6AM UTC, corporate action check post-close. Holiday handling: skip in-session jobs, run always-jobs. Weekly calendar verification job compares exchange_calendars output against broker holiday lists.

**Problem Statement:**
Without a scheduler, all data pipelines must be triggered manually. The analysis engine needs fresh data at specific intervals tied to market sessions — not arbitrary crons. A session-aware scheduler ensures indicators are recalculated during trading hours, post-close batch processing happens at actual close time (handling half-days and DST), and always-running jobs (news, FX) execute regardless of market state. This is the orchestration backbone that ties together all Month 2 work into a coherent automated system.

## Acceptance Criteria
- [ ] Given NSE market open, when scheduler checks, then in-session jobs (indicator recalc every 5min, portfolio sync every 60min) are running for XBOM market
- [ ] Given NYSE market closed, when scheduler checks, then US in-session jobs are paused (not running)
- [ ] Given session close event for XNYS, then post-close batch triggered: OHLCV fetch (Job 9), fundamentals refresh (Job 10), risk recalc, portfolio snapshot
- [ ] Given holiday (e.g., July 4 for XNYS), then in-session jobs skipped, always-jobs (news every 15min, FX daily 6AM UTC) still run
- [ ] Given half-day session (e.g., day before Thanksgiving), then post-close triggers at actual close time (1:00 PM ET), not standard close (4:00 PM ET)

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | Session-aware scheduler core | AC #1, #2 | 0 modify, 2 create (`backend/app/scheduling/scheduler.py`, `backend/app/scheduling/__init__.py`) | Celery Beat, exchange_calendars | LAUNCHABLE |
| 2 | In-session task definitions | AC #1 | 0 modify, 2 create (`backend/app/tasks/in_session.py`, `backend/app/tasks/__init__.py`) | Celery tasks | BLOCKED (by #1) |
| 3 | Post-close batch orchestration | AC #3, #5 | 0 modify, 1 create (`backend/app/tasks/post_close.py`) | Celery chains/chords, session close event | BLOCKED (by #1) |
| 4 | Always-running task definitions | AC #4 | 0 modify, 1 create (`backend/app/tasks/always.py`) | Celery periodic tasks | BLOCKED (by #1) |
| 5 | Holiday + half-day handling | AC #4, #5 | 1 modify (`backend/app/scheduling/scheduler.py` — add holiday logic), 0 create | exchange_calendars, calendar_overrides table | BLOCKED (by #1) |
| 6 | Weekly calendar verification job | — (infrastructure) | 0 modify, 1 create (`backend/app/tasks/calendar_verify.py`) | exchange_calendars vs broker holiday comparison | BLOCKED (by #1) |
| 7 | Tests | All ACs | 0 modify, 2 create (`backend/tests/test_scheduler.py`, `backend/tests/test_tasks.py`) | pytest, time mocking, Celery test utilities | BLOCKED (by #2, #3, #4, #5, #6) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (scheduler core) ──┬──→ Subtask 2 (in-session tasks) ──────────→ Subtask 7 (tests)
                             ├──→ Subtask 3 (post-close batch) ──────────┘
                             ├──→ Subtask 4 (always tasks) ─────────────┘
                             ├──→ Subtask 5 (holiday handling) ─────────┘
                             └──→ Subtask 6 (calendar verify) ─────────┘
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 2 | Subtask 3 | none | NO |
| Subtask 2 | Subtask 4 | none | NO |
| Subtask 3 | Subtask 4 | none | NO |
| Subtask 1 | Subtask 5 | `scheduler.py` | YES |

### Batch Plan
- **Batch 1:** Subtask 1 (scheduler core)
- **Batch 2:** Subtask 2, 3, 4, 6 (parallel — different task files, no overlap)
- **Batch 3:** Subtask 5 (holiday handling — modifies scheduler.py)
- **Batch 4:** Subtask 7 (tests — depends on all)
- **Recommended workers:** 3 (Batch 2 has 4 independent subtasks)
- **Estimated batches:** 4

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | Celery Beat custom scheduler, exchange_calendars session queries, dynamic schedule modification |
| 2 | Celery @task decorator, indicator recalc (calls Job 13's technical.py), portfolio sync (calls Month 1's sync) |
| 3 | Celery chains/chords for batch orchestration, session close event detection |
| 4 | Celery periodic tasks (crontab), news/sentiment (calls Job 12), FX refresh (calls Job 11) |
| 5 | exchange_calendars half-day detection, calendar_overrides table queries |
| 6 | exchange_calendars vs broker API holiday list comparison, logging discrepancies |
| 7 | pytest-celery, freezegun/time-machine for time mocking, Celery eager mode |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Celery Beat custom scheduler is complex (dynamic schedule based on market state) | HIGH | Start with simple approach: check market state on each beat tick; upgrade to event-driven if needed |
| DST transitions cause schedule drift | MEDIUM | exchange_calendars handles DST; always use UTC internally; session times come from library, not hardcoded |
| Half-day detection requires knowing actual close time per day | MEDIUM | exchange_calendars provides actual session times per date; query daily at market open |
| Post-close batch failure leaves data inconsistent | MEDIUM | Each pipeline task is idempotent; failed tasks retry with exponential backoff; partial completion is OK (next run completes) |
| Multiple markets with overlapping sessions create scheduling complexity | MEDIUM | Per-market task queues; each market's scheduler state is independent |
| Jobs 9-13 must be complete before this job can wire their tasks | HIGH | This job is in Batch 6 (blocked by Batch 5); verify all pipeline entry points exist before wiring |
| Celery worker memory with FinBERT model loaded | MEDIUM | Dedicate sentiment tasks to a specific worker with more memory; use Celery task routing |

## Configuration
- **Workers:** 3
- **Mode:** parallel
- **Estimated batches:** 4
- **Branch:** `feat/m2-14-celery-scheduler`
- **Batch:** 6 (blocked by Jobs 9-13; wires all pipelines into scheduler)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-m2-14-celery-scheduler.md
```
