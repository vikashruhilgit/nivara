# Supervisor Job: Broker Abstraction + Alpaca Adapter + Zerodha Stub

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected initialized (by Job 1)
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Job 2 (database) must be complete (needs instruments, symbol_mappings, broker_connections tables)

## Task
**Goal:** Build the abstract BrokerAdapter with features dict, normalized Pydantic schemas (NormalizedPosition, NormalizedBalance, NormalizedOrder), BrokerAPIError with enumerated codes, a working AlpacaAdapter (alpaca-py, paper trading default, place_order raises NotImplementedError), ZerodhaAdapter stub, AES-256-GCM encryption for broker tokens with dual-key support, broker OAuth endpoints, and a conformance test suite.

**Problem Statement:**
Portfolio sync (Job 8) requires a broker abstraction layer to fetch positions, orders, and balances. Without this, the platform cannot communicate with any broker. The abstraction must be clean enough that adding future brokers (IBKR, etc.) is straightforward.

## Acceptance Criteria
- [ ] Given BrokerAdapter abstract interface, when AlpacaAdapter implements it, then conformance tests pass (get_positions, get_balances, get_orders, normalize_symbol)
- [ ] Given ZerodhaAdapter stub, when any method called (except features), then NotImplementedError raised
- [ ] Given plaintext broker token, when encrypted with AES-256-GCM (per-user HKDF from MASTER_ENCRYPTION_KEY + user_id), then decrypted output matches original
- [ ] Given dual-key env (MASTER_ENCRYPTION_KEY=new,old), when decrypt with old key, then succeeds (fallback)
- [ ] Given Alpaca paper account credentials, when get_positions() called, then returns List[NormalizedPosition] with all required fields
- [ ] Given BrokerAPIError, then error codes include: AUTH_EXPIRED, RATE_LIMITED, INSTRUMENT_UNKNOWN, UPSTREAM_DOWN, NETWORK_TIMEOUT
- [ ] Given broker OAuth flow, when GET /api/auth/broker/alpaca/connect, then returns OAuth redirect URL
- [ ] Given AlpacaAdapter, when place_order() called, then NotImplementedError raised (MVP read-only)

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | BrokerAdapter abstract + schemas + errors | AC #1, #6 | 0 modify, 4 create (backend/app/brokers/base.py, backend/app/brokers/__init__.py, backend/app/schemas/broker.py, backend/app/brokers/errors.py) | — | LAUNCHABLE |
| 2 | AES-256-GCM encryption service | AC #3, #4 | 0 modify, 2 create (backend/app/services/encryption.py, backend/tests/test_encryption.py) | — | LAUNCHABLE |
| 3 | AlpacaAdapter implementation | AC #1, #5, #8 | 1 modify (pyproject.toml — add alpaca-py), 1 create (backend/app/brokers/alpaca.py) | — | BLOCKED (by #1) |
| 4 | ZerodhaAdapter stub | AC #2 | 0 modify, 1 create (backend/app/brokers/zerodha.py) | — | BLOCKED (by #1) |
| 5 | Broker OAuth endpoints | AC #7 | 1 modify (main.py — register router), 1 create (backend/app/api/broker_auth.py) | — | BLOCKED (by #2, #3) |
| 6 | Conformance test suite | AC #1, #2 | 0 modify, 2 create (backend/tests/test_broker_conformance.py, backend/tests/test_broker_oauth.py) | — | BLOCKED (by #3, #4, #5) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (abstract + schemas) ──┬──→ Subtask 3 (Alpaca) ──┬──→ Subtask 5 (OAuth) ──→ Subtask 6 (tests)
                                 └──→ Subtask 4 (Zerodha) ─┘
Subtask 2 (encryption) ─────────────────────────────────────┘
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | none | NO |
| Subtask 3 | Subtask 4 | none | NO |

### Batch Plan
- **Batch 1:** Subtask 1, 2 (parallel)
- **Batch 2:** Subtask 3, 4 (parallel, depend on 1)
- **Batch 3:** Subtask 5 (depends on 2, 3)
- **Batch 4:** Subtask 6 (depends on 3, 4, 5)
- **Recommended workers:** 2
- **Estimated batches:** 4

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | Python ABC patterns, Pydantic v2 |
| 2 | cryptography library (AESGCM, HKDF) |
| 3 | alpaca-py SDK |
| 4 | — (stub only) |
| 5 | FastAPI OAuth2 flow |
| 6 | pytest conformance patterns |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| alpaca-py SDK version / API changes | MEDIUM | Pin version in pyproject.toml; use paper trading endpoint |
| Alpaca OAuth flow requires registered redirect URI | HIGH | Register investiq:// deep link scheme with Alpaca; also support localhost for backend testing |
| HKDF key derivation must be deterministic across restarts | HIGH | Use fixed salt derived from user_id; document in CLAUDE.md |
| Zerodha stub may need partial implementation for OAuth test | LOW | OAuth endpoint returns NotImplementedError for Zerodha in MVP |

## Configuration
- **Workers:** 2
- **Mode:** parallel
- **Estimated batches:** 4
- **Branch:** `feat/m1-4-broker-adapter`
- **Batch:** 2 (parallel with Jobs 5, 6, 7; blocked by Job 2)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-10-m1-4-broker-adapter.md
```

## Outcome
- **Status:** completed
- **Completed:** 2026-04-13T00:00:00Z
- **PR:** https://github.com/vikashruhilgit/nivara/pull/4
- **Branch:** feat/m1-4-broker-adapter
- **Files changed:** 16 (8 created, 4 modified backend app files, 3 test files, 1 lockfile)
- **Heal loop ran:** true
- **Heal decision:** PASS
- **Heal iterations:** 1
- **Summary:** Implemented BrokerAdapter abstract base with normalized Pydantic schemas, AlpacaAdapter (httpx-based, read-only), ZerodhaAdapter stub, AES-256-GCM encryption service with HKDF per-user subkeys and dual-key rotation, broker OAuth endpoints behind bearer auth, and conformance/OAuth/encryption test suites. Quality gates (ruff, mypy --strict, pytest 43 passed) green. Self-heal integration review found no new BLOCKING/HIGH issues.
