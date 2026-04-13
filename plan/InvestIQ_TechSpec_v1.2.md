**TECHNICAL SPECIFICATION**

**InvestIQ**

Architecture, Schema, APIs & Implementation

Version 1.2 (Consolidated) • March 2026 • Confidential

| *Companion to PRD v1.2. Covers auth (FastAPI-only), full schema (instruments, symbol mapping, corporate actions, FX rates, notifications), API design, explainer abstraction, broker conformance, market calendar, sync idempotency, key rotation, CLI guardrails, deployment, and monitoring.* |
| --- |

## 1. Authentication Architecture

| *FastAPI is sole auth authority. No NextAuth. Next.js is pure API consumer.* |
| --- |

### 1.1 Token Spec

| **Token** | **Details** | **Storage** |
| --- | --- | --- |
| **Access** | **JWT RS256, 15 min, user_id+tier** | **Frontend React state (memory only)** |
| **Refresh** | **Opaque UUID, 7d, single-use rotation** | **httpOnly Secure SameSite=Strict cookie** |

### 1.2 CSRF & Session

- **CSRF:** SameSite=Strict cookie + X-CSRF-Token header on mutations.
- **Logout:** Clear cookie + blacklist refresh token in Redis (TTL = remaining life).
- **Password change:** Invalidate ALL refresh tokens for user.
- **Broker OAuth:** Separate from user auth. Tokens encrypted, never reach frontend.

## 2. Project Structure

investiq/

├── backend/ # FastAPI (sole auth)

│ ├── app/

│ │ ├── main.py, config.py

│ │ ├── models/ # SQLAlchemy: users, instruments, positions, ...

│ │ ├── schemas/ # Pydantic req/res

│ │ ├── api/ # auth, portfolio, analysis, recommendations, safety

│ │ ├── brokers/

│ │ │ ├── base.py # BrokerAdapter + features dict

│ │ │ ├── alpaca.py, zerodha.py

│ │ │ └── conformance_tests.py

│ │ ├── data/ # DataProvider abstraction

│ │ │ ├── base.py, yahoo.py, fred.py, gnews.py, reddit.py

│ │ ├── analysis/ # technical, fundamental, sentiment, risk

│ │ ├── intelligence/

│ │ │ ├── synthesizer.py

│ │ │ └── explainers/ # base, template, claude_cli, api

│ │ ├── safety/ # guardian, kill_switch, position_sizer

│ │ ├── scheduling/ # calendar.py, scheduler.py

│ │ ├── notifications/ # base, dashboard, email, console

│ │ ├── tasks/ # Celery tasks

│ │ └── manage.py # CLI: rotate_tokens, etc.

│ └── tests/

├── frontend/ # Next.js (pure API consumer)

├── docker-compose.yml # $0 local dev

├── docker-compose.prod.yml

└── .env.example

## 3. Database Schema

| *PostgreSQL + SQLAlchemy async. Timestamps UTC. Monetary DECIMAL(18,8). PKs UUID. Instrument identity: (exchange, symbol) composite unique.* |
| --- |

### 3.1 users

id (UUID PK), email (UNIQUE), password_hash (bcrypt), base_currency (INR|USD, set at signup), tier (free|pro|premium), created_at, updated_at.

### 3.2 instruments

| **Column** | **Type** | **Null** | **Notes** |
| --- | --- | --- | --- |
| **id** | **UUID** | **NO** | **PK** |
| **symbol** | **VARCHAR(20)** | **NO** | **AAPL, RELIANCE** |
| **exchange** | **VARCHAR(10)** | **NO** | **XNSE, XNYS, XNAS (ISO MIC)** |
| **isin** | **VARCHAR(12)** | **YES** | **Optional. UNIQUE if present.** |
| **name** | **VARCHAR(255)** | **YES** | **Company name** |
| **sector** | **VARCHAR(50)** | **YES** | **GICS sector** |
| **currency** | **VARCHAR(3)** | **NO** | **INR \\| USD** |

UNIQUE on (symbol, exchange). All other tables reference instrument_id.

### 3.3 symbol_mappings

id (BIGSERIAL), instrument_id (FK), broker (ENUM), broker_symbol (VARCHAR), data_symbol (VARCHAR — for Yahoo etc.). UNIQUE on (broker, broker_symbol). Each adapter’s normalize_symbol() resolves through this table.

### 3.4 broker_connections

id (UUID), user_id (FK), broker (ENUM), access_token_enc (BYTEA, AES-256-GCM), refresh_token_enc (BYTEA), token_expires_at, is_active, features_json (JSONB), last_sync_at, created_at.

### 3.5 positions

id (UUID), user_id (FK), broker_connection_id (FK), instrument_id (FK), quantity (DECIMAL), avg_price, current_price, market_value, unrealized_pnl, synced_at. All prices in instrument native currency. Idempotency key: (broker_connection_id, instrument_id).

### 3.6 orders

id (UUID), user_id (FK), broker_connection_id (FK), instrument_id (FK), broker_order_id (VARCHAR — from broker), side (buy|sell), order_type, quantity, price, filled_qty, avg_fill_price, status (ENUM), placed_at, filled_at. Idempotency key: (broker_connection_id, broker_order_id). Never deleted.

### 3.7 fx_rates

id (BIGSERIAL), currency_pair (USD_INR, INR_USD), rate_date (DATE), rate (DECIMAL), source (fred|ecb), fetched_at. UNIQUE on (currency_pair, rate_date). Index on (currency_pair, rate_date DESC).

### 3.8 corporate_actions

id (BIGSERIAL), instrument_id (FK), action_type (ENUM: split|reverse_split|dividend|bonus), ex_date (DATE), ratio_from (INT), ratio_to (INT), dividend_amount (DECIMAL), applied (BOOLEAN), source (yahoo|broker_sync|manual), created_at.

### 3.9 price_history (Partitioned)

Composite PK: (instrument_id, timestamp). Partitioned by month. open, high, low, close (DECIMAL), volume (BIGINT). Index on (instrument_id, timestamp DESC). Corporate action adjustments applied retroactively.

### 3.10 recommendations

id (UUID), user_id (FK), instrument_id (FK), action (ENUM), confidence (DECIMAL 0–100), technical_score, fundamental_score, sentiment_score, risk_score, explanation (TEXT), explainer_used (ENUM: template|claude_cli|api), is_stale, created_at.

### 3.11 notifications

id (UUID), user_id (FK), channel (ENUM: dashboard|email|console), title, body, severity (info|warning|critical), read (BOOLEAN), created_at. Index on (user_id, read, created_at DESC).

### 3.12 calendar_overrides

id (BIGSERIAL), exchange (VARCHAR), date (DATE), is_holiday (BOOLEAN), session_open (TIME), session_close (TIME), reason (TEXT), created_by. UNIQUE on (exchange, date). Takes precedence over exchange_calendars library.

### 3.13 audit_log (Immutable)

id (BIGSERIAL), user_id (UUID nullable), event_type (VARCHAR, indexed), event_data (JSONB), created_at (indexed). Immutability: REVOKE UPDATE, DELETE for app DB role. BEFORE UPDATE OR DELETE trigger raises exception. Personal: 1yr retention. SaaS: 7yr. Partitioned by month.

### 3.14 ai_analysis_log

| Column | Type | Null | Notes |
|--------|------|------|-------|
| id | BIGSERIAL | NO | PK |
| user_id | UUID | NO | FK to users |
| instrument_id | UUID | NO | FK to instruments |
| provider | ENUM(claude_cli, api) | NO | Which AI provider used |
| ai_score | JSONB | YES | AIAnalysisScore JSON (null on error) |
| traditional_score | DECIMAL | NO | The deterministic composite score |
| blended_score | DECIMAL | YES | Hypothetical: what blended score would have been |
| model_version | VARCHAR | YES | e.g., "claude-sonnet-4-20250514" |
| prompt_hash | VARCHAR | NO | SHA-256 of the prompt sent |
| status | ENUM(success, error, refused, timeout) | NO | Outcome |
| input_tokens | INT | YES | Tokens in prompt |
| output_tokens | INT | YES | Tokens in response |
| latency_ms | INT | YES | End-to-end AI call time |
| shadow_mode | BOOLEAN | NO | true = log-only, false = blended (Phase 2+) |
| created_at | TIMESTAMPTZ | NO | DEFAULT NOW() |

Index on (user_id, created_at DESC). Index on (instrument_id, created_at DESC). Index on (status).

## 4. Explainer Provider Abstraction

Interface: ExplainerProvider.explain(recommendation) → str. Provider name stored in audit.

### 4.1 TemplateExplainer (Default)

Deterministic templates. <10ms. Zero cost. Always available. No external dependencies.

### 4.2 ClaudeCliExplainer (Local Only)

subprocess: claude -p <prompt> --output-format json. Guarded by ENABLE_CLAUDE_CLI=true (default false) AND DEPLOYMENT_ENV check (hard block if hosted/production/saas). Security: 10s timeout, 2000 token max prompt, PII/token redaction, no URLs in prompt. Audit: logs prompt_hash (SHA-256) + latency + status. Actual prompt/response only at DEBUG level in local env.

### 4.3 ApiExplainer (Phase 2+, BYOK)

User provides API key in settings. Pro/Premium only. Falls back to template on failure.

### 4.4 Fallback

Any failure → TemplateExplainer. Recommendations never blocked by explainer. Audit logs actual provider used.

## 4b. AI Analysis Provider Abstraction

Interface: `AIAnalysisProvider.analyze(instrument, documents) → AIAnalysisScore`. Provider name stored in audit.

### AIAnalysisScore Schema (Pydantic)

```
outlook: float       # 0.0-1.0, clamped
risks: float         # 0.0-1.0, clamped
reasoning: str
model_version: str
latency_ms: int
status: str          # success | error | refused | timeout
```

### 4b.1 ClaudeCliAnalyzer (Local Only)

subprocess: `claude -p <prompt> --output-format json`. Guarded by `AI_ANALYSIS_ENABLED=true` AND `DEPLOYMENT_ENV=local`. Security: timeout configurable (default 10s), max document tokens (default 4000), PII/token redaction, input sanitization (regex blocklist for known injection patterns). Audit: logs prompt_hash (SHA-256), model_version, latency_ms, input/output token counts.

### 4b.2 ApiAnalyzer (BYOK)

Anthropic SDK. User provides `ANTHROPIC_API_KEY`. Works in any `DEPLOYMENT_ENV`. Rate limited (default 10 calls/hour). Same security and audit as CLI.

### 4b.3 Shadow Mode (Phase 1)

AI analysis triggers ONLY on `POST /api/recommendations/generate`, NOT on GET. Runs as async Celery task (does not block recommendation response). Result logged to `ai_analysis_log` table with `traditional_score` and hypothetical `blended_score`. Recommendation uses ONLY traditional deterministic score.

### 4b.4 Live Mode (Phase 2+)

Score IS blended: `(1 - AI_weight) × traditional + AI_weight × AI_score`. Hard-blocked if `DEPLOYMENT_ENV=production` AND no legal review flag set. Weight cap: 0.30 enforced as code constant `MAX_AI_WEIGHT` (not just env var). Requires 3 months shadow data.

### 4b.5 Input Sanitization

- Strip known injection patterns via regex blocklist (e.g., "ignore previous instructions", "system prompt")
- Max token limit per document: `AI_ANALYSIS_MAX_DOCUMENT_TOKENS` (default 4000)
- Content classification pre-check (reject non-financial content)

### 4b.6 Output Validation

- Pydantic schema enforcement (AIAnalysisScore)
- Range clamping: outlook and risks clamped to 0.0–1.0
- Refusal detection: check for refusal patterns in reasoning field
- Type checking: all fields validated before use

### 4b.7 Fallback

Any AI failure (timeout, error, refused, malformed output) → AI excluded from scoring. Weight redistributed to deterministic components. Warning logged. In shadow mode: status field records failure type.

### 4b.8 Safety Mitigations Summary

1. Output validation (Pydantic, range clamp, refusal detection)
2. Input sanitization (regex blocklist, token limit, classification)
3. Weight enforcement (MAX_AI_WEIGHT=0.30 code constant, audit on changes)
4. Fallback (any failure → deterministic only, weight redistributed)
5. Model version tracking (recorded per score in ai_analysis_log)
6. Log write failure (warning logged, AI result discarded, not retried)

## 5. Broker Conformance & Feature Flags

### 5.1 Feature Flags

AlpacaAdapter.features = {

supports_realtime_streaming: True, supports_paper_trading: True,

requires_daily_reauth: False, supports_order_placement: False }

ZerodhaAdapter.features = {

supports_realtime_streaming: True, supports_paper_trading: False,

requires_daily_reauth: True, supports_order_placement: False }

### 5.2 Conformance Tests

- get_positions() → List[NormalizedPosition] with required fields
- get_balances() → NormalizedBalance with cash, equity, buying_power
- get_orders() → List[NormalizedOrder] with status enum mapping
- All monetary values as Decimal (not float)
- All timestamps as timezone-aware UTC datetime
- Both raise BrokerAPIError with consistent error codes
- Idempotent: get_positions() twice = same result
- Rate limit: both implement exponential backoff on 429
- normalize_symbol() correctly resolves via symbol_mappings

### 5.3 Sync Idempotency

| *Broker is ALWAYS source of truth. Every sync: fetch from broker, upsert locally by idempotency key, mark missing positions as closed.* |
| --- |

- **Position key:** (broker_connection_id, broker_symbol). Upsert qty/price.
- **Order key:** (broker_connection_id, broker_order_id). Upsert status. Never delete.
- **Failure:** Each upsert independent. Partial sync = consistent but incomplete. Next sync completes. Stale >2h = reduced confidence.

## 6. Market Calendar & Scheduling

### 6.1 Source

- **Primary:** exchange_calendars library. XBOM (NSE), XNYS (NYSE), XNAS (NASDAQ). Covers holidays, half-days, Muhurat.
- **Fallback:** calendar_overrides table. Auto-created if broker returns “market closed” unexpectedly.
- **Verification:** Weekly job compares library vs broker holiday lists. Logs discrepancies.

### 6.2 Celery Scheduling

| **Job** | **Freq** | **Requirement** | **Scope** |
| --- | --- | --- | --- |
| **Stream quotes** | **Continuous** | **In-session only** | **Per-market** |
| **Indicator recalc** | **5 min** | **In-session** | **Per-market** |
| **Portfolio sync** | **60 min** | **In-session** | **Per-market** |
| **Post-close batch** | **Once** | **At session close** | **Per-market** |
| **News + sentiment** | **15 min** | **Always** | **All** |
| **FX refresh** | **Daily 6AM UTC** | **Always** | **N/A** |
| **Corp action check** | **Post-close** | **After OHLCV update** | **Per-market** |
| **Calendar verify** | **Weekly** | **Always** | **All** |

All internal timestamps UTC. Scheduler reads actual session close time per day (handles half-days). DST handled by exchange_calendars.

## 7. API Design

### 7.1 Auth

| **Method** | **Endpoint** | **Description** |
| --- | --- | --- |
| **POST** | **/api/auth/register** | **Create account. Returns access_token + sets refresh cookie.** |
| **POST** | **/api/auth/login** | **Login. access_token in body, refresh in httpOnly cookie.** |
| **POST** | **/api/auth/refresh** | **Cookie auto-sent. New access_token. Rotate refresh.** |
| **DELETE** | **/api/auth/logout** | **Clear cookie. Blacklist refresh in Redis.** |
| **GET** | **/api/auth/broker/{broker}/connect** | **OAuth redirect URL.** |
| **GET** | **/api/auth/broker/{broker}/callback** | **Store encrypted tokens.** |
| **GET** | **/api/auth/broker/status** | **Connection status + features for all brokers.** |

### 7.2 Portfolio

| **Method** | **Endpoint** | **Description** |
| --- | --- | --- |
| **GET** | **/api/portfolio/summary** | **Aggregated: value (base currency), P&L, allocation.** |
| **GET** | **/api/portfolio/positions** | **All positions. Native + base currency fields.** |
| **GET** | **/api/portfolio/intelligence** | **Diversification, risk, sector, benchmark alpha.** |
| **POST** | **/api/portfolio/sync** | **Manual sync trigger (idempotent upsert).** |

### 7.3 Analysis, Recommendations, Safety

GET /api/analysis/{symbol}/technical|fundamental|sentiment|risk. GET /api/recommendations. POST /api/recommendations/generate. POST /api/safety/kill-switch. GET /api/safety/status. GET /api/safety/audit-log (paginated).

### 7.4 Notifications

GET /api/notifications (paginated, filterable by read/severity). PATCH /api/notifications/{id}/read. WebSocket: ws://host/ws/alerts, ws://host/ws/portfolio, ws://host/ws/insights.

## 8. Security

### 8.1 Broker Token Encryption

- **Algo:** AES-256-GCM. Per-user key via HKDF from master + user_id.
- **Format:** nonce(12B) \|\| ciphertext \|\| tag(16B) in BYTEA.
- **Dual-key:** MASTER_ENCRYPTION_KEY accepts comma-separated pair for zero-downtime rotation.

### 8.2 Key Rotation Procedure

- Generate new key: python -c "import secrets; print(secrets.token_hex(32))"
- Set env: MASTER_ENCRYPTION_KEY=new,old (comma-separated). Restart.
- Verify: /health/brokers still decrypts all connections.
- Run: python manage.py rotate_tokens (decrypts with whichever key works, re-encrypts with new).
- Verify: CLI reports all rotated. Re-run if any failed (skips already-done).
- Remove old key: MASTER_ENCRYPTION_KEY=new (single). Restart.
- **Rollback:** Revert env to old key at any step before step 4 completes.
- **Both keys lost:** Tokens unrecoverable. Users must re-auth. Back up master key in password manager.
- **Frequency:** Manual, every 6–12 months or on suspected compromise. ~5 min for MVP-scale.

### 8.3 API Security

- **Rates:** 100/min general, 10/min analysis, 1/sec kill switch.
- **CORS:** Frontend origin only. Credentials: true.
- **CSRF:** SameSite=Strict + X-CSRF-Token.
- **Input:** Pydantic on all endpoints. Reject unknown fields.
- **TLS:** 1.3 enforced. HSTS.

### 8.4 Env Vars

DATABASE_URL, REDIS_URL

JWT_PRIVATE_KEY, JWT_PUBLIC_KEY, CSRF_SECRET

MASTER_ENCRYPTION_KEY (supports comma-separated dual-key)

ALPACA_CLIENT_ID, ALPACA_CLIENT_SECRET

ZERODHA_API_KEY, ZERODHA_API_SECRET

EXPLAINER_PROVIDER=template

ENABLE_CLAUDE_CLI=false

DEPLOYMENT_ENV=local (local|hosted|production|saas)

GNEWS_API_KEY

NOTIFICATION_EMAIL_PROVIDER=none (none|smtp|resend)

```
# AI Analysis (MODE 4)
AI_ANALYSIS_ENABLED=false
AI_ANALYSIS_PROVIDER=claude_cli       # claude_cli | api
AI_ANALYSIS_SHADOW_MODE=true          # true=log only, false=blend (Phase 2+)
AI_ANALYSIS_WEIGHT=0.20               # default weight when blending
AI_ANALYSIS_WEIGHT_CAP=0.30           # hard cap (also enforced as code constant)
AI_ANALYSIS_TIMEOUT=10                # seconds
AI_ANALYSIS_MAX_DOCUMENT_TOKENS=4000  # max tokens per document in prompt
AI_ANALYSIS_RATE_LIMIT=10             # max AI analysis calls per hour (API provider)
ANTHROPIC_API_KEY=                    # for API provider (BYOK)
```

## 9. Caching & Performance

### 9.1 Redis Cache

| **Data** | **Key Pattern** | **TTL** | **Invalidation** |
| --- | --- | --- | --- |
| **Current price** | **price:{instrument_id}** | **30s** | **On quote** |
| **Indicators** | **tech:{instrument_id}:{name}** | **5 min** | **On recalc** |
| **Portfolio** | **portfolio:{user_id}** | **60s** | **On sync** |
| **Recommendations** | **reco:{user_id}** | **15 min** | **On new analysis** |
| **FX rate** | **fx:{pair}** | **24h** | **Daily refresh** |
| **Fundamentals** | **fund:{instrument_id}** | **24h** | **Daily refresh** |

### 9.2 Latency Targets

| **Operation** | **p50** | **p99** |
| --- | --- | --- |
| **Dashboard (cached)** | **<500ms** | **<2s** |
| **Portfolio sync** | **<3s** | **<8s** |
| **Full analysis** | **<15s** | **<30s** |
| **Template explanation** | **<10ms** | **<50ms** |
| **CLI explanation** | **<3s** | **<8s** |
| **Kill switch** | **<500ms** | **<1s** |

### 9.3 DB Optimization

- **Partitioning:** price_history by month. audit_log by month. Auto-create 3 months ahead.
- **Indexing:** Composite on (instrument_id, timestamp). Partial on active positions. GIN on JSONB.
- **Pooling:** SQLAlchemy async, pool_size=20, max_overflow=10.
- **Archival:** >2yr data to archive tables. Keep aggregates.

## 10. Deployment

### 10.1 $0 Local (Default)

| *Docker Compose: PostgreSQL + Redis + FastAPI + Celery + Next.js. Total: $0.* |
| --- |

### 10.2 Degradation Without Services

| **Service** | **If Down** | **Impact** |
| --- | --- | --- |
| **PostgreSQL** | **App cannot start** | **CRITICAL: total failure** |
| **Redis** | **No cache, no Celery, no session revocation** | **HIGH: degraded, security risk** |

### 10.3 Hosted (Optional)

- **Backend:** Railway $5–$20/mo.
- **Frontend:** Vercel free tier.
- **DB:** Railway Postgres or Supabase free.
- **Redis:** Upstash free or Railway.

Total hosted: $20–$50/month.

### 10.4 CI/CD

- GitHub Actions: lint + types + unit + conformance tests
- Auto-deploy staging on merge. Manual promote to prod.
- Alembic migrations auto-run. Rollback always available.

## 11. Monitoring

### 11.1 Health Checks

- **/health:** DB + Redis + Celery.
- **/health/brokers:** Connection status, token freshness, features.
- **/health/data:** Pipeline freshness per source. Flags stale.

### 11.2 Alerting

| **Condition** | **Severity** | **Action** |
| --- | --- | --- |
| **API errors >5%** | **Warning** | **Email alert** |
| **API errors >15%** | **Critical** | **Auto kill switch + notify** |
| **Broker sync 3x fail** | **Warning** | **Email user + system alert** |
| **Data source >30min down** | **Warning** | **Flag analysis as stale** |
| **Kill switch activated** | **Critical** | **Notify all admins** |
| **Unexpected holiday detected** | **Info** | **Auto-create calendar override** |

### 11.3 Logging

- **Format:** Structured JSON (timestamp, level, service, event, user_id, metadata).
- **Sensitive:** NEVER log tokens, passwords, financial data. Mask to last 4 chars.
- **Retention:** 30d hot. Cold per audit policy.

*End of Tech Spec v1.2*

InvestIQ • March 2026

