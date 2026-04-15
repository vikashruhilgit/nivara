# Supervisor Job: Safety Layer — Limits, Kill Switch, Position Sizer, Audit Trail

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected initialized (by Job 1)
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Month 2 complete (portfolio sync, positions table populated)

## Task
**Goal:** Build the Safety layer: Daily loss limit (2% default, configurable min 1%), Max drawdown (10% default, min 5%), Max position size (10% default, max 25%), Kill switch (POST /api/safety/kill-switch, <500ms latency, halts all automation flags), Duplicate order block (60s window). In MVP, validates hypothetical actions for recommendation quality — Phase 2+ gates real execution. Enhance audit trail with structured JSON events and queryable API (GET /api/safety/audit-log paginated). Safety status API (GET /api/safety/status).

**Problem Statement:**
Safety is foundational — built first so all other intelligence features can validate against safety constraints. Without the safety layer, recommendations cannot be quality-checked against position limits, loss limits, or drawdown thresholds. The kill switch is a non-negotiable requirement for any future execution capability. Currently, no safety guardrails exist. Success looks like a comprehensive safety validation system that can be called by any module to check whether an action is safe, with an immutable audit trail.

**Note (MODE 4 scope):** Safety validation (loss limits, position sizing, drawdown) applies to the `traditional_score` only. The `blended_score` stored in `ai_analysis_log` is informational in shadow mode — it represents what the score would have been if AI were blended. Safety does not validate `blended_score`. In Phase 2+ live mode, safety will validate the final blended recommendation score.

## Acceptance Criteria
- [ ] Given hypothetical buy that would make position >10% of portfolio, when validated, then rejected with reason "Exceeds max position size (10%)"
- [ ] Given max position size configured to 15%, when hypothetical buy checked, then uses 15% threshold
- [ ] Given portfolio down 2% today, when daily loss limit checked, then flag raised with "Daily loss limit reached (2%)"
- [ ] Given portfolio drawdown from peak is 12%, when max drawdown checked, then flag raised with "Max drawdown exceeded (10%)"
- [ ] Given POST /api/safety/kill-switch, then completes in <500ms and sets kill_switch_active=true, halting all automation flags
- [ ] Given kill switch active, when any safety check performed, then all automation blocked
- [ ] Given duplicate order (same symbol, side, qty) within 60s, when checked, then blocked with "Duplicate order detected"
- [ ] Given GET /api/safety/audit-log?page=1&per_page=20, then returns paginated structured JSON events sorted by created_at DESC
- [ ] Given GET /api/safety/status, then returns current state of all safety controls (limits, kill switch, recent violations)
- [ ] Given safety violation, then event logged to audit_log table as structured JSON with event_type, details, and timestamp

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | Safety guardian (limits + validation engine) | AC #1, #2, #3, #4, #7 | 0 modify, 3 create (backend/app/safety/__init__.py, backend/app/safety/guardian.py, backend/app/schemas/safety.py) | Pydantic v2, business logic | LAUNCHABLE |
| 2 | Kill switch service | AC #5, #6 | 0 modify, 1 create (backend/app/safety/kill_switch.py) | Redis (for fast state), FastAPI | LAUNCHABLE |
| 3 | Position sizer | AC #1, #2 | 0 modify, 1 create (backend/app/safety/position_sizer.py) | decimal math | LAUNCHABLE |
| 4 | Safety API endpoints + audit log query | AC #5, #8, #9, #10 | 1 modify (backend/app/main.py — register router), 1 create (backend/app/api/safety.py) | FastAPI, SQLAlchemy pagination | BLOCKED (by #1, #2, #3) |
| 5 | Tests | All ACs | 0 modify, 2 create (backend/tests/test_safety_guardian.py, backend/tests/test_safety_api.py) | pytest, time mocking | BLOCKED (by #4) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (guardian) ──┐
Subtask 2 (kill switch)├──→ Subtask 4 (API) ──→ Subtask 5 (tests)
Subtask 3 (position)  ─┘
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | none | NO |
| Subtask 1 | Subtask 3 | none | NO |
| Subtask 2 | Subtask 3 | none | NO |

### Batch Plan
- **Batch 1:** Subtask 1, 2, 3 (parallel — no file overlap, independent modules)
- **Batch 2:** Subtask 4 (API, depends on 1, 2, 3)
- **Batch 3:** Subtask 5 (tests)
- **Recommended workers:** 3
- **Estimated batches:** 3

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | Business rules validation, Pydantic v2, decimal precision |
| 2 | Redis atomic operations, FastAPI background tasks |
| 3 | Portfolio weight calculation, decimal math |
| 4 | FastAPI router, SQLAlchemy async pagination, Pydantic v2 |
| 5 | pytest, Redis mocking, httpx AsyncClient |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Kill switch latency >500ms under load | HIGH | Use Redis for kill switch state (single key read); avoid DB roundtrip |
| Duplicate order detection requires recent order cache | MEDIUM | Use Redis sorted set with TTL=60s for recent orders |
| Daily loss requires knowing start-of-day portfolio value | MEDIUM | Store daily_snapshot at market open; compare current value against it |
| audit_log immutability (REVOKE UPDATE/DELETE) requires DB migration | LOW | Add migration if not already created by Month 1; check schema first |

## Configuration
- **Workers:** 3
- **Mode:** parallel
- **Estimated batches:** 3
- **Branch:** `feat/m3-19-safety-layer`
- **Batch:** 7 (parallel with Jobs 15, 16, 17, 18)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-m3-19-safety-layer.md
```

## Outcome
- heal_loop_ran: true
- heal_decision: PASS
- heal_iterations: 1
- heal_remaining_issues: 0 (HIGH); 5 MEDIUM/LOW accepted as follow-ups (Decimal→float in audit JSONB, inverted lower-bound schema validators, Redis/audit commit ordering, redundant activation audit rows, API test fake reimplements SUT)
- pr: https://github.com/vikashruhilgit/nivara/pull/19
- final_commit: f3ccf4e
- tests: 330 passing (full suite); 17 safety tests
