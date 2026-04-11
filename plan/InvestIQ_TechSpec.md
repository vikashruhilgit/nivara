**TECHNICAL SPECIFICATION**

**InvestIQ**

Architecture, Database, APIs & Implementation Guide

Version 1.0 • March 2026 • Confidential

|  |
| --- |
| *Companion document to the InvestIQ PRD. This spec covers database schema, API design, security implementation, deployment architecture, and performance optimization for the development team.* |

# **1. Project Structure**

## **1.1 Repository Layout**

Monolith-modular: single repo, clean module boundaries, shared database.

investiq/

├── backend/ # FastAPI application

│ ├── app/

│ │ ├── main.py # App entry, middleware, startup

│ │ ├── config.py # Settings, env vars

│ │ ├── models/ # SQLAlchemy ORM models

│ │ ├── schemas/ # Pydantic request/response

│ │ ├── api/ # Route handlers

│ │ │ ├── auth.py

│ │ │ ├── portfolio.py

│ │ │ ├── analysis.py

│ │ │ ├── recommendations.py

│ │ │ └── settings.py

│ │ ├── brokers/ # Broker adapters

│ │ │ ├── base.py # Abstract BrokerAdapter

│ │ │ ├── alpaca.py

│ │ │ └── zerodha.py

│ │ ├── data/ # Data collection pipelines

│ │ │ ├── yahoo.py

│ │ │ ├── fred.py

│ │ │ ├── gnews.py

│ │ │ └── reddit.py

│ │ ├── analysis/ # Analysis engine

│ │ │ ├── technical.py

│ │ │ ├── fundamental.py

│ │ │ ├── sentiment.py

│ │ │ └── risk.py

│ │ ├── intelligence/ # Recommendation engine

│ │ │ ├── synthesizer.py

│ │ │ └── explainer.py # Claude API integration

│ │ ├── safety/ # Safety & risk controls

│ │ │ ├── guardian.py

│ │ │ ├── kill\_switch.py

│ │ │ └── position\_sizer.py

│ │ └── tasks/ # Celery background tasks

│ ├── tests/

│ └── requirements.txt

├── frontend/ # Next.js application

│ ├── src/

│ │ ├── app/ # Next.js app router

│ │ ├── components/ # React components

│ │ ├── hooks/ # Custom hooks (usePortfolio, etc)

│ │ ├── lib/ # API client, utils

│ │ └── stores/ # State management

│ └── package.json

├── docker-compose.yml

├── .env.example

└── README.md

# **2. Database Schema**

|  |
| --- |
| *PostgreSQL with SQLAlchemy ORM. All timestamps in UTC. All monetary values stored as DECIMAL(18,8) to handle both INR and USD with precision. UUIDs for all primary keys.* |

## **2.1 Core Tables**

### **users**

|  |  |  |  |
| --- | --- | --- | --- |
| **Column** | **Type** | **Nullable** | **Notes** |
| **id** | UUID | NO | PK, default uuid\_generate\_v4() |
| email | VARCHAR(255) | NO | UNIQUE, indexed |
| password\_hash | VARCHAR(255) | NO | bcrypt hashed |
| name | VARCHAR(100) | YES | Display name |
| tier | ENUM | NO | free | pro | premium |
| created\_at | TIMESTAMPTZ | NO | DEFAULT now() |
| updated\_at | TIMESTAMPTZ | NO | Auto-updated |

### **broker\_connections**

|  |  |  |  |
| --- | --- | --- | --- |
| **Column** | **Type** | **Nullable** | **Notes** |
| **id** | UUID | NO | PK |
| user\_id | UUID | NO | FK → users.id |
| broker | ENUM | NO | alpaca | zerodha |
| access\_token\_enc | BYTEA | NO | AES-256-GCM encrypted |
| refresh\_token\_enc | BYTEA | YES | Encrypted (Alpaca only) |
| token\_expires\_at | TIMESTAMPTZ | YES | For refresh scheduling |
| is\_active | BOOLEAN | NO | DEFAULT true |
| last\_sync\_at | TIMESTAMPTZ | YES | Last successful sync |
| created\_at | TIMESTAMPTZ | NO | DEFAULT now() |

### **positions**

|  |  |  |  |
| --- | --- | --- | --- |
| **Column** | **Type** | **Nullable** | **Notes** |
| **id** | UUID | NO | PK |
| user\_id | UUID | NO | FK → users.id |
| broker\_connection\_id | UUID | NO | FK → broker\_connections.id |
| symbol | VARCHAR(20) | NO | Ticker (e.g., AAPL, RELIANCE) |
| exchange | VARCHAR(10) | NO | NSE, NYSE, NASDAQ |
| quantity | DECIMAL(18,8) | NO | Current holding qty |
| avg\_price | DECIMAL(18,8) | NO | Average entry price |
| current\_price | DECIMAL(18,8) | YES | Last synced price |
| currency | VARCHAR(3) | NO | INR | USD |
| market\_value | DECIMAL(18,8) | YES | qty \* current\_price |
| unrealized\_pnl | DECIMAL(18,8) | YES | Computed on sync |
| sector | VARCHAR(50) | YES | GICS sector classification |
| synced\_at | TIMESTAMPTZ | NO | Last broker sync |

### **Additional Core Tables**

- **orders:** Tracks all orders (placed via platform or synced from broker). Fields: id, user\_id, broker\_connection\_id, symbol, side (buy/sell), order\_type, quantity, price, status, broker\_order\_id, placed\_at, filled\_at.
- **portfolio\_snapshots:** Daily snapshots of portfolio value for historical tracking. Fields: id, user\_id, date, total\_value, total\_pnl, currency. Indexed on (user\_id, date).
- **watchlist:** User watchlist items. Fields: id, user\_id, symbol, exchange, added\_at.

## **2.2 Market Data Tables**

### **price\_history (Partitioned by month)**

|  |  |  |  |
| --- | --- | --- | --- |
| **Column** | **Type** | **Nullable** | **Notes** |
| **symbol** | VARCHAR(20) | NO | Part of composite PK |
| **timestamp** | TIMESTAMPTZ | NO | Part of composite PK |
| open | DECIMAL(18,8) | NO |  |
| high | DECIMAL(18,8) | NO |  |
| low | DECIMAL(18,8) | NO |  |
| close | DECIMAL(18,8) | NO |  |
| volume | BIGINT | NO |  |
| exchange | VARCHAR(10) | NO | For multi-market queries |

Partitioned by month on timestamp. Index on (symbol, timestamp DESC). This is the highest-volume table — expect millions of rows within months.

### **technical\_indicators**

Stores computed indicator values. Fields: id, symbol, timestamp, indicator\_name (RSI, MACD, etc.), value\_json (JSONB — stores indicator-specific fields like RSI value, MACD histogram, signal line, etc.), computed\_at. Index on (symbol, indicator\_name, timestamp DESC).

### **sentiment\_scores**

Fields: id, symbol (nullable — null for macro sentiment), source (gnews, reddit, fred), sentiment\_label (positive/negative/neutral), confidence, raw\_text\_hash (for dedup), scored\_at. Index on (symbol, source, scored\_at DESC).

### **fundamental\_data**

Fields: id, symbol, exchange, metric\_name (pe\_ratio, revenue\_growth, etc.), value, period (Q1-2026, FY-2025, etc.), source (yahoo, edgar), fetched\_at. Index on (symbol, metric\_name, period).

### **news\_articles**

Fields: id, title, source\_url, source\_name, published\_at, symbols (TEXT[] — related tickers), sentiment\_score, sentiment\_label, fetched\_at. Index on (published\_at DESC), GIN index on symbols array.

## **2.3 AI & Recommendation Tables**

### **recommendations**

|  |  |  |  |
| --- | --- | --- | --- |
| **Column** | **Type** | **Nullable** | **Notes** |
| **id** | UUID | NO | PK |
| user\_id | UUID | NO | FK → users.id |
| symbol | VARCHAR(20) | NO |  |
| action | ENUM | NO | strong\_buy|buy|hold|sell|strong\_sell |
| confidence | DECIMAL(5,2) | NO | 0.00 to 100.00 |
| technical\_score | DECIMAL(5,4) | YES | -1.0 to +1.0 |
| fundamental\_score | DECIMAL(5,4) | YES | -1.0 to +1.0 |
| sentiment\_score | DECIMAL(5,4) | YES | -1.0 to +1.0 |
| risk\_score | DECIMAL(5,2) | YES | 0 to 100 |
| explanation | TEXT | YES | Claude API generated |
| is\_stale | BOOLEAN | NO | True if based on old data |
| created\_at | TIMESTAMPTZ | NO |  |

## **2.4 Safety & Audit Tables**

### **audit\_log (Append-only, immutable)**

|  |  |  |  |
| --- | --- | --- | --- |
| **Column** | **Type** | **Nullable** | **Notes** |
| **id** | BIGSERIAL | NO | PK, auto-increment |
| user\_id | UUID | YES | Nullable for system events |
| event\_type | VARCHAR(50) | NO | Indexed. See event types below |
| event\_data | JSONB | NO | Full event payload |
| ip\_address | INET | YES | User IP for security |
| created\_at | TIMESTAMPTZ | NO | Indexed, DEFAULT now() |

Event types: recommendation\_generated, recommendation\_viewed, order\_placed, order\_filled, order\_failed, safety\_check\_pass, safety\_check\_fail, kill\_switch\_activated, kill\_switch\_deactivated, config\_changed, broker\_sync, token\_refreshed, login, logout.

### **safety\_config**

Per-user safety settings. Fields: id, user\_id (UNIQUE FK), daily\_loss\_limit\_pct, max\_drawdown\_pct, max\_position\_pct, max\_trade\_pct, max\_trades\_per\_day, cooldown\_hours, kill\_switch\_active (BOOLEAN), last\_triggered\_at, updated\_at. Defaults applied on user creation.

# **3. API Design**

## **3.1 Authentication Endpoints**

|  |  |  |
| --- | --- | --- |
| **Method** | **Endpoint** | **Description** |
| **POST** | /api/auth/register | Create account (email + password) |
| **POST** | /api/auth/login | Login, returns JWT access + refresh tokens |
| **POST** | /api/auth/refresh | Refresh JWT using refresh token |
| **GET** | /api/auth/broker/{broker}/connect | Initiate OAuth flow (redirect URL) |
| **GET** | /api/auth/broker/{broker}/callback | OAuth callback, store encrypted tokens |
| **DELETE** | /api/auth/broker/{broker}/disconnect | Revoke and delete broker tokens |

## **3.2 Portfolio Endpoints**

|  |  |  |
| --- | --- | --- |
| **Method** | **Endpoint** | **Description** |
| **GET** | /api/portfolio/summary | Aggregated portfolio: value, P&L, allocation |
| **GET** | /api/portfolio/positions | All positions across connected brokers |
| **GET** | /api/portfolio/history | Portfolio value over time (chart data) |
| **POST** | /api/portfolio/sync | Trigger manual broker sync |
| **GET** | /api/portfolio/intelligence | Diversification, risk concentration, allocation |

## **3.3 Analysis & Recommendations**

|  |  |  |
| --- | --- | --- |
| **Method** | **Endpoint** | **Description** |
| **GET** | /api/analysis/{symbol}/technical | Technical indicators for symbol |
| **GET** | /api/analysis/{symbol}/fundamental | Fundamental metrics |
| **GET** | /api/analysis/{symbol}/sentiment | Sentiment scores (news + social) |
| **GET** | /api/analysis/{symbol}/risk | VaR, volatility, drawdown, risk score |
| **GET** | /api/recommendations | Latest recommendations for portfolio |
| **POST** | /api/recommendations/generate | Trigger fresh analysis + recommendations |
| **GET** | /api/recommendations/{id} | Full detail including explanation |

## **3.4 Safety Endpoints**

|  |  |  |
| --- | --- | --- |
| **Method** | **Endpoint** | **Description** |
| **POST** | /api/safety/kill-switch | Activate kill switch (immediate halt) |
| **DELETE** | /api/safety/kill-switch | Deactivate kill switch |
| **GET** | /api/safety/status | Current safety status + limit usage |
| **PUT** | /api/safety/config | Update safety parameters |
| **GET** | /api/safety/audit-log | Query audit trail (paginated) |

## **3.5 WebSocket Endpoints**

- **ws://host/ws/portfolio:** Real-time portfolio value and P&L updates during market hours.
- **ws://host/ws/alerts:** Risk Guardian alerts, safety notifications, kill switch events.
- **ws://host/ws/insights:** Live AI insight feed updates as new analysis completes.

# **4. Security Implementation**

## **4.1 Authentication Flow**

User auth: JWT (access token 15 min, refresh token 7 days). Access token in Authorization header. Refresh token in httpOnly cookie. Tokens signed with RS256 (asymmetric — public key for verification, private for signing).

Broker auth: OAuth2/OAuth-like per broker. Tokens encrypted (AES-256-GCM) with per-user encryption keys derived from master key via HKDF. Master key in environment variable, never in code or database.

## **4.2 Encryption Spec**

- **Algorithm:** AES-256-GCM (authenticated encryption).
- **Key derivation:** HKDF-SHA256 from master key + user\_id salt.
- **IV:** 96-bit random nonce, stored alongside ciphertext.
- **Storage format:** nonce (12 bytes) || ciphertext || tag (16 bytes) in BYTEA column.
- **Key rotation:** Master key rotatable. Re-encrypt all tokens on rotation.

## **4.3 API Security**

- **Rate limiting:** 100 req/min per user (general). 10 req/min for analysis generation. 1 req/sec for kill switch.
- **CORS:** Whitelist frontend domain only.
- **Input validation:** Pydantic schemas on all endpoints. Reject unknown fields.
- **SQL injection:** SQLAlchemy ORM with parameterized queries only. Never raw SQL from user input.
- **XSS:** Next.js automatic escaping. CSP headers.
- **HTTPS:** TLS 1.3 enforced. HSTS header.

## **4.4 Secrets Management**

All secrets in environment variables. .env file for local development (gitignored). Production: Railway/Render secret management or Vault if self-hosted. Required env vars:

DATABASE\_URL=postgresql://...

REDIS\_URL=redis://...

JWT\_PRIVATE\_KEY=...

JWT\_PUBLIC\_KEY=...

MASTER\_ENCRYPTION\_KEY=... (64 hex chars)

ALPACA\_CLIENT\_ID=...

ALPACA\_CLIENT\_SECRET=...

ZERODHA\_API\_KEY=...

ZERODHA\_API\_SECRET=...

CLAUDE\_API\_KEY=...

GNEWS\_API\_KEY=...

# **5. Performance Optimization**

## **5.1 Caching Strategy (Redis)**

|  |  |  |  |
| --- | --- | --- | --- |
| **Data** | **Cache Key Pattern** | **TTL** | **Invalidation** |
| Current prices | price:{symbol} | 30 sec | On new quote |
| Technical indicators | tech:{symbol}:{indicator} | 5 min | On recalc |
| Portfolio summary | portfolio:{user\_id} | 60 sec | On sync |
| Recommendations | reco:{user\_id} | 15 min | On new analysis |
| Sentiment scores | sent:{symbol} | 15 min | On new batch |
| Fundamental data | fund:{symbol} | 24 hr | On daily refresh |

## **5.2 Database Optimization**

- **Partitioning:** price\_history partitioned by month. Auto-create partitions 3 months ahead.
- **Indexing:** Composite indexes on (symbol, timestamp) for all time-series. Partial indexes on active positions.
- **Connection pooling:** SQLAlchemy async with pool\_size=20, max\_overflow=10.
- **Query optimization:** Avoid N+1 queries. Use eager loading for portfolio + positions. Explain analyze on slow queries.
- **Archival:** Move data older than 2 years to archive tables. Keep aggregates.

## **5.3 Background Processing (Celery)**

- **portfolio\_sync:** Hourly per user. Priority queue for active market hours.
- **analysis\_pipeline:** Triggered on price update or on-demand. Chains: technical → fundamental → sentiment → risk → synthesize.
- **news\_fetch:** Every 15 min. Batch by sector to maximize GNews free tier.
- **sentiment\_batch:** Process news queue through FinBERT in batches of 50.
- **daily\_maintenance:** After market close: snapshot portfolio, refresh fundamentals, recalculate risk models, clean expired cache.

## **5.4 Latency Targets**

|  |  |  |
| --- | --- | --- |
| **Operation** | **Target (p50)** | **Target (p99)** |
| Dashboard load (cached) | < 500ms | < 2s |
| Portfolio sync | < 3s | < 8s |
| Single stock analysis | < 5s | < 15s |
| Full portfolio analysis | < 15s | < 30s |
| AI explanation (Claude) | < 3s | < 8s |
| Kill switch activation | < 500ms | < 1s |
| WebSocket message delivery | < 200ms | < 1s |

# **6. Deployment Architecture**

## **6.1 MVP Deployment (Railway/Render)**

Single-server deployment optimized for solo developer. Estimated cost: $20–$50/month.

- **Backend:** FastAPI on Railway ($5–$20/mo). Auto-scaling, managed deployment.
- **Frontend:** Next.js on Vercel (free tier). CDN, edge functions.
- **Database:** Railway PostgreSQL ($5–$20/mo) or Supabase free tier.
- **Redis:** Railway Redis ($5/mo) or Upstash free tier.
- **Celery workers:** Same Railway instance. 1 worker with concurrency=4.

## **6.2 Scale Deployment (Phase 2+)**

- **Backend:** Docker containers on Railway/AWS ECS. Horizontal scaling.
- **Database:** Managed PostgreSQL (RDS/Supabase Pro). Read replicas.
- **Redis:** Managed Redis (ElastiCache/Upstash Pro).
- **Workers:** Separate Celery worker containers. Auto-scale based on queue depth.
- **Monitoring:** Sentry for errors. Prometheus + Grafana for metrics. PagerDuty for alerts.

## **6.3 CI/CD Pipeline**

- GitHub Actions for CI: lint, type check, unit tests, integration tests
- Automatic deployment to staging on PR merge to develop
- Manual promotion to production from staging
- Database migrations via Alembic (auto-run on deploy)
- Rollback capability: previous deployment always available

# **7. Monitoring & Observability**

## **7.1 Health Checks**

- **/health:** Returns 200 if app is running. Checks: DB connection, Redis connection, Celery worker ping.
- **/health/brokers:** Checks active broker connections. Flags stale tokens.
- **/health/data:** Checks data pipeline freshness. Flags if any source is stale.

## **7.2 Alerting Rules**

|  |  |  |
| --- | --- | --- |
| **Condition** | **Severity** | **Action** |
| API error rate > 5% | Warning | Email alert |
| API error rate > 15% | Critical | PagerDuty + auto kill switch |
| Broker sync failure > 3 consecutive | Warning | Email user + system alert |
| Data source down > 30 min | Warning | Flag analysis as stale |
| Kill switch activated | Critical | Email all admins immediately |
| Database CPU > 80% | Warning | Review queries, consider scaling |

## **7.3 Logging**

- **Format:** Structured JSON (timestamp, level, service, event, user\_id, metadata).
- **Levels:** DEBUG (dev only), INFO (normal ops), WARNING (degraded), ERROR (failures), CRITICAL (safety events).
- **Retention:** 30 days hot (searchable). 7 years cold (audit compliance).
- **Sensitive data:** NEVER log tokens, passwords, or full API responses containing user financial data. Mask to last 4 chars.

*End of Technical Specification*

InvestIQ v1.0 • March 2026
