# Supervisor Job: Real Zerodha Adapter Implementation

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected clean
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Months 1-3 complete (broker abstraction layer, Alpaca adapter, conformance tests, symbol mappings table, all analysis/safety infrastructure)

## Task
**Goal:** Replace the Zerodha stub (from Month 1 Job 4) with a real ZerodhaAdapter implementation using Kite Connect v3 API. Limited mode: sync-only after daily login. Includes OAuth-like redirect flow via expo-auth-session, daily token expiry handling (~6AM IST), global rate limiter (10 req/sec shared across users), symbol mapping for Indian instruments (RELIANCE, INFY), and conformance test parity with Alpaca.

**Problem Statement:**
The developer has an active Zerodha account but the current ZerodhaAdapter is a stub that raises NotImplementedError. Indian market holdings cannot be synced, and the dual-market (India + US) value proposition is incomplete. Without this, beta users with Zerodha accounts cannot participate, and cross-market features (Job 23) have no Indian data to work with.

## Acceptance Criteria
- [ ] Given Zerodha OAuth flow completed via expo-auth-session, when get_positions() called, then returns List[NormalizedPosition] with all required fields
- [ ] Given Zerodha OAuth flow completed, when get_balances() called, then returns NormalizedBalance with cash, equity, buying_power in INR
- [ ] Given Zerodha OAuth flow completed, when get_orders() called, then returns List[NormalizedOrder] with status enum mapping
- [ ] Given token expired (past ~6AM IST), when any API call made, then raises BrokerAPIError with code AUTH_EXPIRED
- [ ] Given AUTH_EXPIRED error, then dashboard shows yellow broker badge with "Re-login required" action
- [ ] Given >10 requests/sec across all users, when API call made, then global rate limiter queues and delays (does not drop or error)
- [ ] Given Zerodha symbol "RELIANCE", when normalize_symbol() called, then resolves to instrument (RELIANCE, XNSE) via symbol_mappings
- [ ] Given conformance tests, when run against ZerodhaAdapter, then all pass (same contract as AlpacaAdapter)
- [ ] Given ZerodhaAdapter.features, then supports_realtime_streaming=True, supports_paper_trading=False, requires_daily_reauth=True, supports_order_placement=False

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | ZerodhaAdapter core implementation (Kite Connect v3) | AC #1, #2, #3, #9 | 1 modify (backend/app/brokers/zerodha.py — replace stub), 0 create | Kite Connect v3 API, BrokerAdapter contract | LAUNCHABLE |
| 2 | Global rate limiter (Redis-based, 10 req/sec) | AC #6 | 0 modify, 2 create (backend/app/brokers/rate_limiter.py, backend/tests/test_rate_limiter.py) | Redis token bucket / sliding window | LAUNCHABLE |
| 3 | Token expiry detection + AUTH_EXPIRED handling | AC #4, #5 | 1 modify (backend/app/brokers/zerodha.py), 1 modify (backend/app/api/auth.py — broker status endpoint update) | Kite Connect token lifecycle | BLOCKED (by #1) |
| 4 | Symbol mapping for Indian instruments | AC #7 | 1 modify (backend/app/brokers/zerodha.py — normalize_symbol), 1 create (backend/app/brokers/seed_indian_symbols.py or migration) | symbol_mappings table, instrument identity | BLOCKED (by #1) |
| 5 | Mobile broker connect screen update (Zerodha OAuth) | AC #5 | 1 modify (mobile/src/components/BrokerConnect.tsx), 0 create | expo-auth-session, Kite Connect OAuth redirect | LAUNCHABLE |
| 6 | Conformance tests for ZerodhaAdapter | AC #8 | 1 modify (backend/tests/brokers/conformance_tests.py or equivalent), 1 create (backend/tests/brokers/test_zerodha.py) | pytest, broker conformance contract | BLOCKED (by #1, #3, #4) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (Core adapter) ──┬──→ Subtask 3 (Token expiry)
                            ├──→ Subtask 4 (Symbol mapping)
                            └──→ Subtask 6 (Conformance tests — after #1, #3, #4)
Subtask 2 (Rate limiter) ────── (independent, integrated into #1 later)
Subtask 5 (Mobile OAuth) ────── (independent of backend)
Subtask 3 ──→ Subtask 6
Subtask 4 ──→ Subtask 6
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 3 | backend/app/brokers/zerodha.py | YES |
| Subtask 1 | Subtask 4 | backend/app/brokers/zerodha.py | YES |
| Subtask 2 | Subtask 5 | none | NO |
| Subtask 3 | Subtask 4 | backend/app/brokers/zerodha.py | YES |

### Batch Plan
- **Batch 1:** Subtask 1, 2, 5 (parallel — no file overlap)
- **Batch 2:** Subtask 3, 4 (sequential — both modify zerodha.py, but could be serialized within one worker)
- **Batch 3:** Subtask 6 (after all adapter work complete)
- **Recommended workers:** 3 (Batch 1), 1 (Batch 2), 1 (Batch 3)
- **Estimated batches:** 3

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | Kite Connect v3 API, BrokerAdapter abstract class, async SQLAlchemy |
| 2 | Redis sliding window / token bucket rate limiting |
| 3 | Kite Connect token lifecycle, IST timezone handling |
| 4 | symbol_mappings table, instrument identity (exchange, symbol) |
| 5 | expo-auth-session OAuth redirect flow, deep links |
| 6 | pytest, broker conformance test suite, parametrized tests |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Kite Connect v3 API may have undocumented quirks or changes | HIGH | Developer has active Zerodha account for real API testing; use kiteconnect Python SDK |
| Global rate limiter (10 req/sec per API key, shared across all users) may bottleneck with multiple users | HIGH | Use Redis sliding window; queue requests instead of dropping; log when queue depth > threshold |
| Token expiry detection at ~6AM IST is approximate, not exact | MEDIUM | Check token validity before each API call; handle 403/token-expired responses gracefully |
| Symbol mapping for Indian instruments requires seeding (hundreds of symbols) | MEDIUM | Start with top 100 Nifty 50 + frequently traded; auto-create mapping on first encounter via normalize_symbol() |
| Conformance tests may reveal behavioral differences between Alpaca and Zerodha | MEDIUM | Document known differences in adapter features dict; conformance tests test the contract, not identical behavior |
| expo-auth-session redirect for Kite Connect may differ from standard OAuth2 | MEDIUM | Kite uses request_token flow, not standard OAuth2; may need custom redirect handling |

## Configuration
- **Workers:** 3
- **Mode:** parallel
- **Estimated batches:** 3
- **Branch:** `feat/m4-22-zerodha-adapter`
- **Batch:** 9 (parallel with Jobs 21, 23; blocked by Month 3)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-m4-22-zerodha-adapter.md
```

## Outcome
- **status:** completed
- **branch:** feat/m4-22-zerodha-adapter
- **PR:** https://github.com/vikashruhilgit/nivara/pull/22
- **subtask commits:** b401ffa (S1), 316322c (S2), 3f02841 (S3), dfad067 (S4), 14ac766 (S5), 2af2445 (S6)
- **heal_loop_ran:** true
- **heal_decision:** PASS
- **heal_iterations:** 1 (review: NEEDS_HUMAN → fix 77ef678 → review: PASS)
- **heal_remaining_issues:** 1 LOW nit (sync test with asyncio pytestmark warning)
- **deferred follow-ups:**
  - `POST /api/brokers/zerodha/session/exchange` endpoint (mobile OAuth callback exchange)
  - `resolve_canonical` / `SymbolMappingService` consolidation — `_build_adapter` does not pass symbol_mapper; Zerodha production uses MIC-default fallback
- **tests:** 88 passed + 1 expected xfail; ruff/mypy --strict/tsc all clean
