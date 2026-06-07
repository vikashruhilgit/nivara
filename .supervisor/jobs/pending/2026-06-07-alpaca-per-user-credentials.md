# Supervisor Job: Per-User Alpaca Broker Credentials

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** ✓ Found (fresh)
- **Git:** clean working tree, branch: `main`
- **GitHub CLI:** ✓ Authenticated (vikashruhilgit)
- **Base branch:** `main` (canonical/default after repo cleanup). Cut the feature branch from `main` (e.g. `feat/m4-alpaca-per-user-creds`). NOTE: CLAUDE.md still says the PR base is `feat/m1-1-repo-scaffold` — that is stale; use `main`. Fixing that CLAUDE.md line is in scope (Subtask 3).
- **Blockers:** 0 | **Warnings:** 1 (stale CLAUDE.md PR-base line — fixed in Subtask 3)
- **Prerequisites:** Local stack runs (Docker, JWT keys, MASTER_ENCRYPTION_KEY) — already in place.

## Task
**Goal:** Replace the MVP shortcut where Alpaca broker access effectively shares one global `ALPACA_API_SECRET` with genuine **per-user** Alpaca credentials, so each user's portfolio sync uses that user's own broker authorization. Pre-beta (Job 24) security/correctness prerequisite.

**Problem Statement:**
- `backend/app/api/broker_auth.py::broker_callback` is **stubbed**: it stores placeholder tokens (`alpaca-access-{code}`, `alpaca-refresh-{code}`) instead of exchanging the OAuth `code` (`TODO(m1-4): replace with real Alpaca token exchange`).
- `backend/app/api/portfolio.py::_build_adapter` (Alpaca branch) decrypts the per-user `access_token_encrypted` for the **api-key** but pulls `api_secret = settings.alpaca_api_secret` — a **global** secret shared across all users. No true per-user Alpaca credential exists today.
- Contrast (correct, do not change): Zerodha uses app-level `ZERODHA_API_KEY/SECRET` + a per-user daily `access_token` stored encrypted per `broker_connections` row.

## Design Decision (resolved)

Two patterns evaluated:

| Pattern | Pros | Cons |
|---|---|---|
| **(2) Per-user API keys** ⭐ chosen | No Alpaca OAuth app registration/approval; `AlpacaAdapter` already uses key+secret headers (minimal change); **removes the global secret entirely**; users self-serve paper keys trivially | Mobile connect UX changes from OAuth redirect to a key/secret form |
| (1) Real Alpaca OAuth | "Proper" multi-user model; no user-pasted secrets | Requires registering+approving an Alpaca OAuth app; `AlpacaAdapter` needs a Bearer-token mode (`Authorization: Bearer`); larger change |

**Chosen: Pattern 2 (per-user API keys)** — fully closes the shared-secret gap with the smallest, lowest-risk change and no external app-registration dependency. Pattern 1 (OAuth) is a documented post-beta follow-up (separate brief). All subtasks assume Pattern 2.

**Endpoint shape (decided):** Add `POST /api/auth/broker/alpaca/credentials` in `broker_auth.py`. Define its Pydantic request model **inline in `broker_auth.py`** (consistent with the existing inline `BrokerCallbackRequest` / `BrokerConnectionResponse` — do NOT move broker schemas to `schemas/auth.py`):
- Request: `AlpacaCredentialsRequest { api_key_id: str, api_secret: str }`
- Response: reuse existing `BrokerConnectionResponse { id, broker, account_id, status }`

**Storage shape (decided):** Reuse existing columns — encrypted **Key ID** → `access_token_encrypted`; encrypted **Secret** → `refresh_token_encrypted` (both `LargeBinary`; the latter already nullable). Avoids an Alembic migration. Add a clear code comment documenting the repurposing. (Dedicated `api_secret_encrypted` column + migration is a possible cleaner alternative; deferred to keep this job migration-free.)

**Mobile contract reconciliation:** The legacy mobile `CallbackResponse { connected: boolean }` does NOT match the backend `BrokerConnectionResponse { id, broker, account_id, status }`. Subtask 4 must consume the real response and treat `status === "active"` as connected (AC #6, #9).

## Acceptance Criteria
- [ ] AC#1 Given a user POSTs a valid Alpaca paper Key ID + Secret to `POST /api/auth/broker/alpaca/credentials`, when processed, then the backend verifies them via Alpaca `GET /v2/account` and persists a `BrokerConnection` with **both** credentials encrypted per-user (`encrypt_token(..., user_id=...)`), `account_id` from the verified account, `status="active"`.
- [ ] AC#2 Given invalid Alpaca credentials, when POSTed, then the API returns a 4xx with a clear error and **no** `BrokerConnection` row is created.
- [ ] AC#3 Given a connected user, when `POST /api/portfolio/sync` runs, then `_build_adapter` uses that user's decrypted Key ID **and** decrypted Secret; `settings.alpaca_api_secret` is **no longer referenced** in the per-user path.
- [ ] AC#4 Given two users with different Alpaca keys, when each syncs, then each adapter uses its own user's credentials (no cross-user leakage).
- [ ] AC#5 Given the credential payload, then neither Key ID nor Secret is ever logged (audit `logger` calls; honor CLAUDE.md "never log secrets or raw tokens").
- [ ] AC#6 Given the new connect endpoint, then its request body is exactly `{ api_key_id, api_secret }` and its response is `BrokerConnectionResponse { id, broker, account_id, status }`.
- [ ] AC#7 Given the mobile Settings → Connect Alpaca flow, then the user enters Key ID + Secret in a form, submits to the backend, and lands in a "connected" state (derived from `status === "active"`); the secret is sent straight to the backend over HTTPS and **not** persisted in client storage.
- [ ] AC#8 Given a pre-existing `BrokerConnection` created by the old stub path (placeholder tokens), when sync runs after this change, then it does not silently use a bogus secret — such rows are invalidated/require reconnect (see Risk + Subtask 2).
- [ ] AC#9 Given order upsert, then it still keys on `(broker_connection_id, instrument_id)` (unchanged).
- [ ] AC#10 Given new/changed backend code, then `ruff`, `mypy --strict`, and `pytest` pass with ≥80% coverage on new code; mobile passes `tsc --noEmit`.

## Subtask Structure

| # | Title | AC Subset | Est. Files (modify/create) | Status |
|---|-------|-----------|---------------------------|--------|
| 1 | Backend: Alpaca credential connect/store endpoint | AC#1, #2, #5, #6 | 1 modify (backend/app/api/broker_auth.py) | LAUNCHABLE |
| 2 | Backend: `_build_adapter` per-user secret + invalidate stale rows | AC#3, #4, #8 | 1 modify (backend/app/api/portfolio.py) | BLOCKED (by #1) |
| 3 | Config + env + docs cleanup | AC#3 (support) | 4 modify (backend/app/config.py, .env.example, docker-compose.yml, CLAUDE.md) | LAUNCHABLE |
| 4 | Mobile: Alpaca key+secret connect form | AC#7, #9-derived | 1 modify (mobile/src/components/BrokerConnect.tsx) | BLOCKED (by #1) |
| 5 | Tests: storage, per-user wiring, no-global-secret, sync, stale-row | AC#1-5, #8, #10 | 2-3 modify/create (backend/tests/test_broker_oauth.py, backend/tests/test_portfolio_sync.py, optional new test) | BLOCKED (by #1, #2) |

### Subtask Contracts

```yaml
# Subtask 1 — credential connect/store endpoint
subtask: 1
requires: []
provides:
  - {kind: endpoint, method: POST, path: /api/auth/broker/alpaca/credentials, file: backend/app/api/broker_auth.py}
  - {kind: schema, name: AlpacaCredentialsRequest, fields: [api_key_id, api_secret], location: inline in backend/app/api/broker_auth.py}
  - {kind: response, name: BrokerConnectionResponse, fields: [id, broker, account_id, status]}
  - {kind: contract, name: alpaca_credential_storage, detail: "Key ID -> access_token_encrypted; Secret -> refresh_token_encrypted; both via encrypt_token(..., user_id=...)"}
  - {kind: contract, name: alpaca_credential_validation, detail: "verify via AlpacaAdapter GET /v2/account before persisting"}
```
```yaml
# Subtask 2 — adapter per-user secret + stale-row invalidation
subtask: 2
requires:
  - {from: 1, name: alpaca_credential_storage}
provides:
  - {kind: behavior, name: build_adapter_per_user, detail: "_build_adapter alpaca branch decrypts Key ID + Secret per-connection; no settings.alpaca_api_secret"}
  - {kind: behavior, name: stale_row_handling, detail: "connections from the old stub path are invalidated / require reconnect (AC#8)"}
```
```yaml
# Subtask 3 — config + env + docs
subtask: 3
requires: []
provides:
  - {kind: config, name: alpaca_global_creds_deprecated, detail: "alpaca_api_key/secret annotated dev/single-account-only in config.py + .env.example; per-user path independent of them"}
  - {kind: docs, name: claude_md_pr_base_fixed, detail: "CLAUDE.md PR-base line updated to main"}
```
```yaml
# Subtask 4 — mobile connect form
subtask: 4
requires:
  - {from: 1, name: AlpacaCredentialsRequest}
  - {from: 1, name: BrokerConnectionResponse}
provides:
  - {kind: ui, name: alpaca_credentials_form, file: mobile/src/components/BrokerConnect.tsx, detail: "Key ID + Secret form; POST to /credentials; connected when status==='active'; no client-side secret persistence"}
```
```yaml
# Subtask 5 — tests
subtask: 5
requires:
  - {from: 1, name: alpaca_credential_storage}
  - {from: 2, name: build_adapter_per_user}
provides:
  - {kind: tests, detail: "store+validate (AC#1,#2), per-user wiring + no global secret (AC#3,#4), no-secret-logging (AC#5), stale-row (AC#8), sync regression"}
```

## Parallelism Analysis

### Dependency Graph
```
#1 (connect/store) ──┬──► #2 (_build_adapter) ──► #5 (tests)
                     └──► #4 (mobile form)
#3 (config/env/docs) ····· (independent files; LAUNCHABLE alongside #1)
```

### Batches
- **Batch 1 (parallel):** #1 (broker_auth.py) + #3 (config/.env/compose/CLAUDE.md) — no file overlap.
- **Batch 2 (parallel, after #1):** #2 (portfolio.py) + #4 (mobile BrokerConnect.tsx) — no file overlap; both consume #1's contracts.
- **Batch 3 (after #2):** #5 (tests).
- **Recommended workers:** 2

### File Overlap Check
- #1 → `broker_auth.py`; #2 → `portfolio.py`; #3 → `config.py`, `.env.example`, `docker-compose.yml`, `CLAUDE.md`; #4 → `BrokerConnect.tsx`; #5 → `backend/tests/*`. **No overlaps across parallel batches.**

## Configuration
- **No new runtime env vars** for Pattern 2 (credentials come from the user at connect time).
- Skills: project has **no skills directory**; backend auth uses the existing FastAPI `Depends(get_current_user)` from `backend/app/auth/dependencies.py` — follow that pattern (no NestJS).
- `settings.alpaca_api_key` / `alpaca_api_secret` (config.py:58-59) become **dev/single-account-only** (optional). Subtask 3: annotate in config.py + `.env.example`; ensure the per-user path no longer depends on them.
- `alpaca_oauth_client_id` / `alpaca_oauth_redirect_uri` (config.py:61-62) are unused by Pattern 2 — leave for the future Pattern-1 follow-up but mark as currently unused.
- `MASTER_ENCRYPTION_KEY` already required and present. No change.

## Risk Assessment

| Risk | Severity | Source | Mitigation |
|---|---|---|---|
| Secret/Key leakage via logs | HIGH | Analysis | No `logger` calls include credential values; review `broker_auth.py` + `portfolio.py`; test asserts creds absent from responses (AC#5) |
| Pre-existing stub rows: `refresh_token_encrypted` previously held a placeholder refresh token, now reinterpreted as the API Secret → silent auth failure at sync | HIGH | Plan Review | AC#8 + Subtask 2: detect/invalidate old-stub connections (e.g. on decrypt-or-account-verify failure, set `status` to require reconnect); do not feed a bogus secret to the adapter |
| Removing global secret breaks dev/seed + existing tests relying on `settings.alpaca_api_secret` | MEDIUM | Analysis | Subtask 5 updates `test_broker_oauth.py` (currently asserts stub behavior) and sync tests; document per-user paper-keys dev path |
| Dead Alpaca OAuth path: `GET /{broker}/connect` still returns an Alpaca OAuth URL that the new form flow makes misleading | MEDIUM | Plan Review | Subtask 1/4: decide the fate of the Alpaca branch of `/connect` (remove or gate); keep Zerodha's `/connect` intact |
| Repurposing `refresh_token_encrypted` to hold the Secret is semantically non-obvious | MEDIUM | Analysis | Clear code comment + this brief's storage-shape contract; revisit with a dedicated column if it causes confusion |
| Mobile form could persist the secret locally | MEDIUM | Analysis | Send Key+Secret directly to backend over HTTPS; never write to `expo-secure-store`/AsyncStorage (only the user's session token lives there) |
| Credential validation calls live Alpaca at connect time (external dependency) | LOW | Analysis | Reuse `AlpacaAdapter` + `httpx`; treat timeout/4xx as a clean connect failure (AC#2) |

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-06-07-alpaca-per-user-credentials.md
```
Run in a fresh Claude Code session (clean context). Cut the feature branch from `main`.
