# InvestIQ — Implementation Overview

## What We're Building

InvestIQ is an **AI-powered investment intelligence platform** that acts as a middleware layer between retail traders and their existing brokerage accounts (Zerodha for India, Alpaca for US). It is **not a broker** — it never holds funds. It connects to brokers via OAuth, syncs portfolio data (read-only in MVP), and applies AI-driven analysis to provide recommendations, risk monitoring, and portfolio intelligence.

**MVP delivers:** a mobile app (iOS + Android) where users connect their Alpaca paper trading account, see their portfolio with AI-generated insights, risk scores, and alerts — all without placing a single trade through InvestIQ.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          MOBILE APP                                  │
│                   React Native + Expo (managed)                      │
│                                                                      │
│   ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌──────────────┐   │
│   │ Portfolio  │  │  Insights │  │ Settings  │  │Broker Connect│   │
│   │   Tab     │  │   Tab     │  │   Tab     │  │   Screen     │   │
│   └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └──────┬───────┘   │
│         │               │               │               │           │
│   ┌─────┴───────────────┴───────────────┴───────────────┴─────┐    │
│   │  API Client (axios + auto-refresh interceptor)             │    │
│   │  TanStack Query (server state) + Zustand (client state)   │    │
│   │  expo-secure-store (refresh token → Keychain/Keystore)    │    │
│   └───────────────────────────┬───────────────────────────────┘    │
└───────────────────────────────┼─────────────────────────────────────┘
                                │ HTTPS (Bearer JWT RS256)
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        FASTAPI BACKEND                               │
│                 Python 3.12 · Sole Auth Authority                    │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  REST API + WebSocket                                         │  │
│  │  /api/auth/*           → register, login, refresh, logout     │  │
│  │  /api/portfolio/*      → summary, positions, sync, intel      │  │
│  │  /api/analysis/*       → technical, fundamental, sentiment    │  │
│  │  /api/recommendations  → AI-scored buy/sell/hold              │  │
│  │  /api/safety/*         → kill switch, status, audit log       │  │
│  │  /api/notifications    → in-app feed, read status             │  │
│  │  /ws/alerts            → real-time risk/price alerts          │  │
│  └──────────────────────────┬────────────────────────────────────┘  │
│                              │                                       │
│  ┌──────────────────────────┴────────────────────────────────────┐  │
│  │                    6-LAYER ARCHITECTURE                        │  │
│  │                                                               │  │
│  │  Layer 6: Presentation  (API endpoints, WebSocket, responses) │  │
│  │  Layer 5: Safety        (kill switch, loss limits, audit log) │  │
│  │  Layer 4: Intelligence  (recommendation synthesis, explainer) │  │
│  │  Layer 3: Analysis      (pandas-ta, FinBERT, risk models)     │  │
│  │  Layer 2: Data          (Yahoo, FRED, GNews, SEC EDGAR, FX)   │  │
│  │  Layer 1: Broker        (Alpaca, Zerodha, symbol mapping)     │  │
│  │                                                               │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  SECURITY                                                     │  │
│  │  JWT RS256 (15min access, kid for rotation)                   │  │
│  │  Opaque refresh token (7d, Redis, single-use rotation)        │  │
│  │  argon2id password hashing                                    │  │
│  │  AES-256-GCM broker token encryption (per-user HKDF)         │  │
│  │  Dual-key rotation (zero-downtime)                            │  │
│  │  Immutable audit trail (DB trigger-enforced)                  │  │
│  │  structlog (masked PII, never log tokens)                     │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  SCHEDULING (Celery + Redis)                                  │  │
│  │  Session-aware: triggers tied to market open/close, not cron  │  │
│  │  exchange_calendars (XBOM, XNYS, XNAS) + calendar_overrides  │  │
│  │  In-session: quotes stream, 5min indicator recalc, hourly sync│  │
│  │  Post-close: OHLCV, fundamentals, risk recalc, snapshot       │  │
│  │  Always: news 15min, FX daily 6AM UTC                         │  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
┌──────────────┐  ┌─────────────┐  ┌──────────────────────────────┐
│ PostgreSQL 16│  │   Redis 7   │  │      External APIs           │
│              │  │             │  │                              │
│ 14 tables:   │  │ JWT blacklst│  │ Alpaca    (realtime quotes)  │
│ users        │  │ cache layer │  │ Zerodha   (India positions)  │
│ instruments  │  │ Celery brkr │  │ Yahoo Fin (OHLCV, fundmntls)│
│ positions    │  │ rate limits │  │ SEC EDGAR (US fundamentals)  │
│ orders       │  │ sync locks  │  │ FRED/ECB  (FX rates, macro)  │
│ price_history│  │             │  │ GNews     (news articles)    │
│ audit_log    │  │ TTLs:       │  │ Reddit    (social sentiment) │
│ ...          │  │ price: 30s  │  │                              │
│              │  │ tech:  5min │  │ All FREE tier.               │
│ Partitioned: │  │ portf: 60s  │  │ Paid escape hatches named:   │
│ price_history│  │ reco: 15min │  │ Polygon.io ($29/mo)          │
│ audit_log    │  │ fx:   24h   │  │ NewsAPI ($449/mo)            │
│ (by month)   │  │ fund: 24h   │  │                              │
└──────────────┘  └─────────────┘  └──────────────────────────────┘
```

---

## Tech Stack

### Backend

| Component | Technology | Version | Why |
|-----------|-----------|---------|-----|
| Language | Python | 3.12 | Latest stable, best async support |
| Package manager | uv | latest | Fastest Python installer, modern lockfile |
| Web framework | FastAPI | latest | Async, auto OpenAPI docs, Pydantic native |
| ORM | SQLAlchemy | 2.x async | Modern `Mapped[]` typing, asyncpg driver |
| Migrations | Alembic | latest | SQLAlchemy-native, auto-generate from models |
| Validation | Pydantic | v2 | FastAPI-native, 5-50x faster than v1 |
| Database | PostgreSQL | 16 | Partitioning, JSONB, UUID, triggers |
| Cache / Queue | Redis | 7 | JWT blacklist, Celery broker, price cache |
| Task queue | Celery + Beat | latest | Session-aware scheduling |
| Market calendar | exchange_calendars | latest | Holidays, half-days, DST, Muhurat |
| Technical analysis | pandas-ta | latest | RSI, MACD, SMA, Bollinger, ATR — deterministic |
| Sentiment | FinBERT (ProsusAI/finbert) | HuggingFace | Local CPU inference, $0 |
| Market data | yfinance | latest | Historical OHLCV + fundamentals (free, ToS risk) |
| Fundamentals | SEC EDGAR API | free | Official, reliable for US stocks |
| News | GNews API | free tier | 100 req/day, batch by sector |
| FX rates | FRED API / ECB | free | Daily USD/INR rates |
| Password hashing | argon2-cffi | latest | OWASP recommended, memory-hard |
| Encryption | cryptography (Fernet/AESGCM) | latest | AES-256-GCM, HKDF per-user key derivation |
| Logging | structlog | latest | Structured JSON, PII masking |
| Linting | ruff | latest | Replaces flake8 + isort + black |
| Type checking | mypy --strict | latest | Full type safety |
| Testing | pytest + pytest-asyncio + httpx | latest | Async test support |

### Mobile

| Component | Technology | Why |
|-----------|-----------|-----|
| Framework | React Native + Expo (managed) | Cross-platform, OTA updates, EAS Build |
| Router | Expo Router (file-based) | Next.js-like routing for RN |
| Server state | TanStack Query (React Query) | Caching, refetching, optimistic updates |
| Client state | Zustand | Minimal, no boilerplate |
| Secure storage | expo-secure-store | iOS Keychain / Android Keystore |
| Auth redirect | expo-auth-session | Deep link OAuth (`investiq://`) |
| Push notifications | Expo Push API | Simpler than raw FCM/APNs |
| Biometric | expo-local-authentication | Face ID / fingerprint gate |
| Charts | react-native-wagmi-charts + victory-native | Candlestick/line + bar/pie |
| HTTP client | axios | Interceptors for auto-refresh |
| Validation | zod | Runtime schema validation |
| Build / deploy | EAS Build + EAS Update | Cloud builds, OTA updates |
| Distribution | TestFlight (iOS) + Play Internal Testing (Android) | Beta channel |
| Testing | jest + @testing-library/react-native | Unit + component tests |
| E2E testing | Maestro | Mobile-specific E2E |
| Linting | biome or eslint | Fast, opinionated |

### Infrastructure

| Component | Technology | Cost |
|-----------|-----------|------|
| Local dev | Docker Compose | $0 |
| Backend hosting | Railway | $5–$20/mo |
| Database hosting | Railway Postgres or Supabase | free–$25/mo |
| Redis hosting | Upstash or Railway | free–$10/mo |
| Frontend hosting | EAS Build (Expo) | free tier |
| Error tracking | Sentry | free tier |
| CI/CD | GitHub Actions | free tier |

---

## Authentication Model (Mobile-First)

```
┌─────────────────────────────────────────────────┐
│                 USER AUTH                         │
│                                                  │
│  Access Token (JWT RS256)                        │
│  ├─ TTL: 15 minutes                             │
│  ├─ Contains: user_id, tier, base_currency, kid │
│  ├─ Stored: React state (memory only)           │
│  └─ Verified: RS256 public key                  │
│                                                  │
│  Refresh Token (opaque UUID)                     │
│  ├─ TTL: 7 days                                 │
│  ├─ Stored: expo-secure-store (Keychain)         │
│  ├─ Backend: Redis (refresh:{token} → user_id)  │
│  ├─ Single-use rotation (GETDEL atomic)          │
│  └─ Blacklisted on logout                       │
│                                                  │
│  NO cookies. NO CSRF. Bearer token only.         │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│               BROKER AUTH (separate)             │
│                                                  │
│  Alpaca: OAuth2 → code exchange server-side      │
│  Zerodha: Kite Connect redirect → request_token  │
│                                                  │
│  Tokens encrypted: AES-256-GCM                   │
│  ├─ Per-user key: HKDF(master_key + user_id)    │
│  ├─ Dual-key rotation (zero-downtime)            │
│  └─ Never reach mobile app                      │
│                                                  │
│  Deep link: investiq://auth/callback/{broker}    │
│  via expo-auth-session                           │
└─────────────────────────────────────────────────┘
```

---

## Data Flow

```
                    BROKER SYNC (hourly in-session)
                    ┌──────────────────────────────┐
                    │ Alpaca API / Zerodha Kite API │
                    └──────────────┬───────────────┘
                                   │ positions, orders, balances
                                   ▼
                    ┌──────────────────────────────┐
                    │   Broker Adapter Layer        │
                    │   normalize_symbol()          │
                    │   → (exchange, symbol)        │
                    │   → instrument_id             │
                    └──────────────┬───────────────┘
                                   │ upsert (idempotent)
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                      PostgreSQL                               │
│  positions (broker=truth)  orders (never deleted)  audit_log │
└──────────────────────────────────┬───────────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
  DATA PIPELINES              ANALYSIS                 INTELLIGENCE
  (Celery scheduled)          (on data refresh)        (on analysis done)
                                                      
  Yahoo Finance ──► OHLCV     pandas-ta ──► technicals  Synthesizer:
  SEC EDGAR   ──► fundmntls   FinBERT   ──► sentiment   tech 40% + fund 25%
  GNews       ──► news        VaR/Vol   ──► risk        + sent 20% + risk 15%
  FRED/ECB    ──► FX rates    Fundmntls ──► scoring          │
  Reddit      ──► social                                     ▼
         │                         │                   Recommendation
         └──► Redis cache          └──► Redis cache    + TemplateExplainer
              (TTL-based)               (TTL-based)          │
                                                             ▼
                                                    ┌────────────────┐
                                                    │  Mobile App    │
                                                    │  via REST API  │
                                                    │  + WebSocket   │
                                                    └────────────────┘
```

---

## AI Engine Design

**Core principle:** All analysis is deterministic. Same inputs = same outputs. LLMs never in the decision loop.

### Recommendation Scoring

```
                    ┌─────────────────────┐
                    │   COMPOSITE SCORE   │
                    │   -1.0 to +1.0      │
                    └─────────┬───────────┘
                              │
           ┌──────────┬───────┴───────┬──────────┐
           ▼          ▼               ▼          ▼
    ┌────────────┐ ┌────────────┐ ┌────────┐ ┌────────┐
    │ Technical  │ │Fundamental │ │Sentimnt│ │  Risk  │
    │   40%      │ │   25%      │ │  20%   │ │  15%   │
    └──────┬─────┘ └──────┬─────┘ └───┬────┘ └───┬────┘
           │              │           │           │
    RSI    20%     Revenue   25%  News   50%  VaR 95/99%
    MACD   20%     Earnings  25%  Social 20%  Volatility
    MA     25%     Debt      20%  Macro  30%  Drawdown
    Bollnr 15%     P/E       15%              Position
    Volume 10%     CashFlow  15%              risk 0-100
    ATR    10%
```

### Explainer Chain

```
Recommendation made (deterministic)
        │
        ▼
ExplainerProvider.explain(recommendation)
        │
        ├── TemplateExplainer (default, $0, <10ms, always available)
        ├── ClaudeCliExplainer (local/dev only, guarded by env check)
        └── ApiExplainer (BYOK, Phase 2+, Pro/Premium only)
        │
        └── ANY failure → TemplateExplainer (fallback)
```

---

## Risk Meter (0–100, deterministic)

```
┌─────────────────────────────────────────────────────────────┐
│                    RISK METER                                │
│                                                              │
│  ┌─────────────────┐ ┌─────────────────┐                   │
│  │ Concentration    │ │ Volatility/VaR  │                   │
│  │ 30% weight       │ │ 30% weight       │                   │
│  │ HHI of position  │ │ 95% VaR as %    │                   │
│  │ weights          │ │ of portfolio     │                   │
│  └─────────────────┘ └─────────────────┘                   │
│  ┌─────────────────┐ ┌─────────────────┐                   │
│  │ Drawdown         │ │ Events          │                   │
│  │ 20% weight       │ │ 20% weight       │                   │
│  │ Current from     │ │ Holdings with    │                   │
│  │ peak, 0-20%→0-100│ │ earnings/macro   │                   │
│  └─────────────────┘ │ in next 5 days   │                   │
│                       └─────────────────┘                   │
│                                                              │
│  Score: 0–30 🟢 green  │  31–60 🟡 yellow  │  61–100 🔴 red │
│                                                              │
│  Tap to drill down → see each component + formula            │
└─────────────────────────────────────────────────────────────┘
```

---

## Safety Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                SAFETY LAYER (nothing bypasses)                │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────────┐  │
│  │ Daily Loss   │  │ Max Position│  │ Kill Switch        │  │
│  │ Limit: 2%    │  │ Size: 10%   │  │ POST /api/safety/  │  │
│  │ (min 1%)     │  │ (max 25%)   │  │ kill-switch        │  │
│  └─────────────┘  └─────────────┘  │ Halts ALL          │  │
│  ┌─────────────┐  ┌─────────────┐  │ automation         │  │
│  │ Max Drawdown│  │ Duplicate   │  │ < 500ms latency    │  │
│  │ Limit: 10%  │  │ Order Block │  └────────────────────┘  │
│  │ (min 5%)    │  │ 60s window  │                          │
│  └─────────────┘  └─────────────┘                          │
│                                                              │
│  MVP: validates hypothetical actions for recommendation      │
│  quality. Phase 2+: gates real order execution.              │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  IMMUTABLE AUDIT TRAIL                                │   │
│  │  Append-only. REVOKE UPDATE/DELETE for app role.      │   │
│  │  BEFORE UPDATE/DELETE trigger raises exception.       │   │
│  │  Structured JSON. Queryable. Partitioned by month.    │   │
│  │  Personal: 1yr retention. SaaS: 7yr.                 │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
Nivara/                                  # repo root
├── InvestIQ_PRD_v1.3.md                 # product requirements
├── InvestIQ_TechSpec_v1.3.md            # technical specification
├── implementation.md                     # this file
├── docker-compose.yml                   # Postgres + Redis + backend + Celery
├── .env.example                         # all env vars
├── .supervisor/jobs/pending/            # Supervisor-Ready Briefs
│
├── backend/                             # FastAPI (Python 3.12)
│   ├── pyproject.toml                   # uv-managed dependencies
│   ├── alembic/                         # database migrations
│   │   ├── env.py
│   │   └── versions/
│   ├── app/
│   │   ├── main.py                      # FastAPI entrypoint
│   │   ├── config.py                    # Pydantic Settings v2
│   │   ├── db/
│   │   │   └── session.py              # SQLAlchemy 2.x async engine
│   │   ├── models/                      # SQLAlchemy ORM models
│   │   │   ├── user.py
│   │   │   ├── instrument.py
│   │   │   ├── position.py
│   │   │   ├── order.py
│   │   │   └── ...
│   │   ├── schemas/                     # Pydantic v2 request/response
│   │   ├── api/                         # route handlers
│   │   │   ├── auth.py
│   │   │   ├── portfolio.py
│   │   │   ├── analysis.py
│   │   │   ├── recommendations.py
│   │   │   ├── safety.py
│   │   │   └── notifications.py
│   │   ├── brokers/                     # broker abstraction
│   │   │   ├── base.py                 # BrokerAdapter + normalized schemas
│   │   │   ├── alpaca.py
│   │   │   ├── zerodha.py
│   │   │   └── conformance_tests.py
│   │   ├── data/                        # DataProvider abstraction
│   │   │   ├── base.py
│   │   │   ├── yahoo.py
│   │   │   ├── fred.py
│   │   │   ├── gnews.py
│   │   │   └── reddit.py
│   │   ├── analysis/                    # analysis engines
│   │   │   ├── technical.py            # pandas-ta indicators
│   │   │   ├── fundamental.py          # scoring vs sector peers
│   │   │   ├── sentiment.py            # FinBERT + news/social/macro
│   │   │   └── risk.py                 # VaR, volatility, drawdown
│   │   ├── intelligence/
│   │   │   ├── synthesizer.py          # weighted composite scoring
│   │   │   └── explainers/
│   │   │       ├── base.py             # ExplainerProvider interface
│   │   │       ├── template.py         # TemplateExplainer (default)
│   │   │       ├── claude_cli.py       # ClaudeCliExplainer (local)
│   │   │       └── api.py             # ApiExplainer (BYOK, Phase 2)
│   │   ├── safety/
│   │   │   ├── guardian.py             # Risk Guardian (Mode E)
│   │   │   ├── kill_switch.py
│   │   │   └── position_sizer.py
│   │   ├── scheduling/
│   │   │   ├── calendar.py            # exchange_calendars wrapper
│   │   │   └── scheduler.py           # session-aware Celery config
│   │   ├── notifications/
│   │   │   ├── base.py
│   │   │   ├── push.py                # Expo Push
│   │   │   ├── email.py               # SMTP / Resend
│   │   │   └── console.py
│   │   ├── security/
│   │   │   ├── encryption.py          # AES-256-GCM + HKDF
│   │   │   └── tokens.py             # JWT RS256 + refresh store
│   │   ├── services/
│   │   │   ├── instruments.py         # canonical identity + mapping
│   │   │   ├── portfolio.py           # sync + reconciliation
│   │   │   └── fx.py                  # FX conversion
│   │   ├── tasks/                      # Celery task definitions
│   │   └── manage.py                  # CLI: rotate_tokens, seed, etc.
│   ├── scripts/
│   │   └── seed_instruments.py
│   └── tests/
│
├── mobile/                              # React Native + Expo
│   ├── package.json
│   ├── app.json                        # Expo config, deep link scheme
│   ├── eas.json                        # EAS Build profiles
│   ├── app/                            # Expo Router (file-based routing)
│   │   ├── _layout.tsx                # root layout
│   │   ├── (auth)/
│   │   │   ├── sign-in.tsx
│   │   │   └── sign-up.tsx
│   │   ├── (tabs)/
│   │   │   ├── portfolio.tsx
│   │   │   ├── insights.tsx
│   │   │   └── settings.tsx
│   │   └── broker/
│   │       └── connect/[broker].tsx   # OAuth flow
│   └── src/
│       ├── api/
│       │   └── client.ts              # axios + refresh interceptor
│       ├── stores/
│       │   └── auth.ts                # Zustand auth store
│       ├── lib/
│       │   ├── secure-store.ts        # expo-secure-store wrapper
│       │   └── queries.ts            # TanStack Query hooks
│       └── components/
│           ├── RiskMeter.tsx
│           ├── HoldingCard.tsx
│           ├── InsightCard.tsx
│           └── BrokerStatusBadge.tsx
│
└── CLAUDE.md                           # project context for AI tools
```

---

## Build & Run

### Local Development (Docker Compose)

```bash
# Clone and setup
git clone <repo-url> && cd Nivara

# Copy env
cp .env.example .env  # fill in ALPACA_CLIENT_ID, MASTER_ENCRYPTION_KEY, etc.

# Start backend stack
docker compose up -d  # Postgres 16 + Redis 7 + FastAPI + Celery worker + beat

# Run migrations + seed
docker compose exec backend alembic upgrade head
docker compose exec backend python manage.py seed

# Verify
curl http://localhost:8000/health  # → {"status": "ok"}

# Start mobile app
cd mobile
npm install
npx expo start  # → opens Metro bundler, scan QR for Expo Go
```

### Environment Variables

```
# Database
DATABASE_URL=postgresql+asyncpg://investiq:password@localhost:5432/investiq
REDIS_URL=redis://localhost:6379/0

# Auth (generate with: python -c "from cryptography.hazmat.primitives.asymmetric import rsa; ...")
JWT_PRIVATE_KEY=...
JWT_PUBLIC_KEY=...

# Encryption (generate with: python -c "import secrets; print(secrets.token_hex(32))")
MASTER_ENCRYPTION_KEY=<hex-key>  # supports comma-separated dual-key for rotation

# Brokers
ALPACA_CLIENT_ID=...
ALPACA_CLIENT_SECRET=...
ZERODHA_API_KEY=...
ZERODHA_API_SECRET=...

# Data
GNEWS_API_KEY=...

# Config
EXPLAINER_PROVIDER=template  # template | claude_cli | api
ENABLE_CLAUDE_CLI=false
DEPLOYMENT_ENV=local  # local | hosted | production | saas
NOTIFICATION_EMAIL_PROVIDER=none  # none | smtp | resend
CORS_ORIGINS=http://localhost:3000
```

---

## Development Roadmap

```
Month 1 — FOUNDATION (Jobs 1-8)         "I can connect, sync, and see my portfolio"
├── Repo scaffold, Docker, CLAUDE.md, GitHub remote
├── Database (14 tables, immutable audit, partitioning)
├── Auth (JWT RS256, bearer refresh, argon2id)
├── Broker adapter (Alpaca paper + Zerodha stub)
├── Instruments & symbol mapping
├── Market calendar (exchange_calendars + overrides)
├── Mobile app shell (tabs, sign-in, broker connect)
└── Portfolio sync (idempotent upsert, broker=truth)

Month 2 — DATA & ANALYSIS (Jobs 9-14)   "AI tells me what's happening"
├── DataProvider abstraction + Yahoo Finance pipeline
├── SEC EDGAR fundamentals
├── FX pipeline (FRED/ECB) + corporate actions
├── News & sentiment (GNews + FinBERT + Reddit)
├── Technical analysis (pandas-ta composite scoring)
└── Session-aware Celery scheduler (all jobs wired)

Month 3 — INTELLIGENCE & SAFETY (Jobs 15-20)  "Guardrails protect me"
├── Risk models (VaR, volatility, drawdown, correlation)
├── Risk Meter + Portfolio Health Score
├── Recommendation engine + TemplateExplainer
├── Portfolio Intelligence (diversification, alpha, benchmark)
├── Safety layer (loss limits, kill switch, position sizing)
└── Risk Guardian + notifications (alerts, push, in-app feed)

Month 4 — POLISH & BETA (Jobs 21-24)    "10-20 users on Alpaca paper"
├── Dashboard screens (risk meter gauge, holdings, insights)
├── Zerodha adapter (real implementation, limited mode)
├── Cross-market benchmark + FX attribution + stale data UX
└── Beta launch (EAS Build, TestFlight, Sentry, onboarding)
```

---

## Key Design Principles

1. **Broker is always source of truth** — InvestIQ never assumes local state is correct. Every sync fetches from broker and upserts.
2. **Deterministic-first AI** — All MVP analysis is reproducible math/rules. Phase 2+ adds optional AI-enhanced scoring (capped at 30%, audited, user opt-in) after legal review.
3. **Safety layer nothing bypasses** — Kill switch, loss limits, and audit trail are foundational, not bolt-on.
4. **Free data with escape hatches** — Every free source has a named paid alternative and a DataProvider abstraction for swapping.
5. **Progressive disclosure** — Simple overview at a glance, depth on demand (tap risk meter → see formula).
6. **No dark patterns** — Never push users toward riskier modes.

---

## Operating Modes (MVP)

| Mode | Name | What It Does | MVP? |
|------|------|-------------|------|
| **A** | Recommendation | Deterministic scoring + template explanations. User reads, acts on broker. | Yes |
| **B** | Assisted Trading | AI suggests → user approves → system executes | Phase 2 |
| **C** | Fully Automated | Strategy rules, auto-execution with guardrails | Phase 2+ |
| **D** | Portfolio Intelligence | Diversification, sector allocation, benchmark alpha, rebalancing suggestions | Yes |
| **E** | Risk Guardian | Volatility/earnings/macro alerts via dashboard + push + optional email | Yes |
| **F** | AI-Enhanced Analysis | Shadow: AI scores logged but not blended. Live (Phase 2+): blended at max 30% weight. | Shadow: Yes, Live: Phase 2+ |

---

## MODE 4: AI-Enhanced Analysis (Shadow + Live)

```
Phase 1 (MVP): SHADOW MODE — AI scores computed + logged, NOT blended
Phase 2+ (after legal review): LIVE MODE — AI scores blended at configurable weight
```

### Design

```
                    POST /api/recommendations/generate
                                  |
                    ┌─────────────┴─────────────┐
                    v                           v
             Traditional Scoring          AI Analysis (async)
             (deterministic, sync)        (Celery task, if enabled)
             tech 40% + fund 25%               |
             + sent 20% + risk 15%             v
                    |                   AIAnalysisProvider
                    |                   .analyze(instrument, docs)
                    |                        |
                    |              ┌─────────┴─────────┐
                    |              v                   v
                    |      ClaudeCliAnalyzer     ApiAnalyzer
                    |      (local, subprocess)   (Anthropic SDK)
                    |              |                   |
                    |              └─────────┬─────────┘
                    |                        v
                    |                  AIAnalysisScore
                    |                  {outlook, risks,
                    |                   reasoning, model_version,
                    |                   latency_ms, status}
                    |                        |
                    v                        v
             ┌──────────────┐     ┌──────────────────────┐
             │ Recommendation│     │  ai_analysis_log     │
             │ (traditional │     │  (shadow: log only)  │
             │  score ONLY) │     │  (live: also blend)  │
             └──────────────┘     └──────────────────────┘
```

### Flag System

| Flag | Default | Effect |
|------|---------|--------|
| `AI_ANALYSIS_ENABLED` | false | Master switch. If false, no AI analysis runs. |
| `AI_ANALYSIS_SHADOW_MODE` | true | true = log only. false = blend into score (Phase 2+). |
| `AI_ANALYSIS_PROVIDER` | claude_cli | claude_cli (local, $0) or api (BYOK, user pays). |
| `AI_ANALYSIS_WEIGHT` | 0.20 | Weight given to AI score when blending. |
| `AI_ANALYSIS_WEIGHT_CAP` | 0.30 | Hard cap. Also enforced as `MAX_AI_WEIGHT` code constant. |

### Weight Redistribution (Live Mode)

```
Without AI (default):          With AI (AI_ANALYSIS_WEIGHT=0.20):
  Technical:    40%              Technical:    32%  (40% × 0.80)
  Fundamental:  25%              Fundamental:  20%  (25% × 0.80)
  Sentiment:    20%              Sentiment:    16%  (20% × 0.80)
  Risk:         15%              Risk:         12%  (15% × 0.80)
  AI:            0%              AI Analysis:  20%
```

### Safety Mitigations (from red team review)

1. **Output validation:** Pydantic schema, range clamp 0.0–1.0, refusal detection
2. **Input sanitization:** Regex blocklist, max token limit, content classification
3. **Weight enforcement:** `MAX_AI_WEIGHT=0.30` code constant, audit log on changes
4. **Fallback:** Any AI failure → deterministic only, weight redistributed
5. **Model version tracking:** Recorded per score in `ai_analysis_log`
6. **Log write failure:** Warning logged, AI result discarded, not retried

---

*InvestIQ — April 2026*
