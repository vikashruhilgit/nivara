**PRODUCT REQUIREMENTS DOCUMENT**

**InvestIQ**

AI-Powered Investment Intelligence Platform

Version 1.2 (Consolidated) • March 2026 • Confidential

| *A smart middleware layer between investors and their broker accounts — connecting to Zerodha and Alpaca via official APIs, providing AI-driven portfolio analysis, risk management, and multi-mode trading intelligence built entirely on free and open-source data sources.* |
| --- |

| **Ver** | **Date** | **Changes** |
| --- | --- | --- |
| **1.0** | **Mar 2026** | **Initial draft** |
| **1.1** | **Mar 2026** | **MVP posture, market sessions, FX, risk meter, data caveats, LLM policy** |
| **1.2** | **Mar 2026** | **Instrument identity, corporate actions, sync idempotency, risk assumptions, benchmark logic, key rotation, CLI guardrails, notifications** |

*India (NSE/BSE via Zerodha) • United States (via Alpaca)*

## Table of Contents

1. Executive Summary

2. Product Vision & Scope

3. Target Users & Personas

4. System Architecture

5. Broker Integration Layer

6. Instrument Identity & Symbol Mapping

7. Market Sessions & Scheduling

8. Core Data Layer (Free-Only Stack)

9. Free Data: Productization Caveats

10. Corporate Actions

11. AI & Analysis Engine

12. LLM & Explanation Policy

13. Operating Modes

14. Risk Meter & Portfolio Health

15. Risk Model Assumptions & Stale Data

16. FX, Base Currency & Benchmark Logic

17. Safety & Risk Architecture

18. Sync Idempotency & Reconciliation

19. Notifications & Alerts

20. User Experience

21. Monetization Strategy

22. Development Roadmap

23. Regulatory Considerations

24. Success Metrics

25. Risks & Mitigations

26. Open Questions

## 1. Executive Summary

InvestIQ is an AI-powered investment intelligence platform that acts as a smart middleware layer between retail/active traders and their existing brokerage accounts. It is not a broker — it connects to Zerodha (India) and Alpaca (US) via their official APIs using OAuth-based authentication.

The platform aggregates market data exclusively from free and open-source providers, applies technical, fundamental, and sentiment analysis through a hybrid engine (classical math + open-source ML + optional LLM), and operates across five modes — from passive portfolio intelligence to fully automated trading with strict safety guardrails.

### 1.1 Key Differentiators

- **Middleware, not broker:** No custody of funds. No broker-dealer overhead.
- **Zero data cost (Phase 1):** All data from free sources (with documented caveats and escape hatches).
- **Deterministic-first AI:** All MVP analysis is reproducible math/rules. Phase 2+ adds optional AI-enhanced scoring (capped at 30%, audited, user opt-in) after legal review.
- **Dual-market:** India + US with session-aware scheduling and cross-currency intelligence.
- **Safety-first:** Kill switch, loss limits, position sizing, audit trail. MVP is strictly read-only.
- **Live accounts:** Developer has active Zerodha and Alpaca accounts for real API testing.

### 1.2 MVP Testing Posture

| *MVP default: Alpaca paper trading. All features validated there before any live interaction. Zerodha connected for portfolio sync but operates in “limited mode” until daily login completes. No write operations to any broker in MVP.* |
| --- |

## 2. Product Vision & Scope

### 2.1 Vision

| *Make institutional-grade investment intelligence accessible to every trader — through an AI layer that connects to the broker they already trust.* |
| --- |

### 2.2 In Scope (MVP)

- Broker connectivity: Alpaca (paper trading default) + Zerodha (sync-only, limited mode)
- Portfolio sync: positions, orders, balances — READ-ONLY, no write operations
- Instrument identity: canonical (exchange, symbol) with broker symbol mapping
- Market data: Alpaca free real-time (US), Yahoo Finance historical (caveats documented)
- Corporate actions: split/bonus detection and historical price adjustment
- Technical analysis: RSI, MACD, SMA/EMA, Bollinger, ATR via pandas-ta
- Fundamentals: P/E, revenue, earnings via Yahoo Finance + SEC EDGAR
- Sentiment: GNews + FinBERT (local). Social: Reddit (degradable)
- Recommendation Mode (A): deterministic scoring, template explanations (LLM optional)
- Portfolio Intelligence (D): diversification, sector allocation, per-market alpha vs benchmark
- Risk Guardian (E): volatility/earnings/macro alerts via dashboard + optional email
- Risk Meter: deterministic, transparent formula with drill-down
- FX: base currency per user, daily FX from FRED/ECB, cross-currency portfolio metrics
- Safety: loss limits, kill switch, position sizing, immutable audit trail
- Sync idempotency: broker is truth, upsert-based reconciliation

### 2.3 Explicitly NOT in MVP

| *No write operations to any broker. No order placement. No assisted/automated trading. No mobile app. No paid data. These are Phase 2+.* |
| --- |

| **Feature** | **Phase** | **Prerequisite** |
| --- | --- | --- |
| **Assisted trading (Mode B)** | **Phase 2** | **3+ months safety validation** |
| **Automated trading (Mode C)** | **Phase 2+** | **Backtesting + legal review** |
| **Backtesting engine** | **Phase 2** | **Historical data pipeline** |
| **Mobile app** | **Phase 2** | **Stable web app** |
| **Additional brokers** | **Phase 2+** | **Broker abstraction tested** |
| **Options / Crypto** | **Phase 3** | **Paid data provider** |
| **Strategy marketplace** | **Phase 3+** | **User base + backtesting** |
| **Custom ML pipeline** | **Phase 3** | **Sufficient training data** |
| **Dividend-adjusted returns** | **Phase 2** | **Corporate actions pipeline** |
| **FX risk in Risk Meter** | **Phase 2** | **FX volatility modeling** |
| **AI-Enhanced Analysis (live mode)** | **Phase 2+** | **Legal review + 3 months shadow data** |

### 2.4 Constraints

- **Solo developer:** Monolith-modular. No microservices until team.
- **Free data:** 15-min delay on some data. Documented ToS risks. Paid escape hatches named.
- **Fixed costs:** Zerodha ₹2K/mo. LLM optional $0–$150/mo. Hosting $0 (Docker) or $20–$50/mo.
- **Paper trading first:** All testing via Alpaca paper until safety validated.

## 3. Target Users & Personas

### 3.1 Primary: Active Retail Trader

Age 25–45. Trades 5–20x/month. Portfolio ₹5L–₹50L or $10K–$200K. Uses Zerodha or Alpaca. Wants AI insights while staying in control.

### 3.2 Secondary: Passive Investor

Age 30–55. MFs, ETFs, stocks. 1–5 trades/month. Portfolio health monitoring, rebalancing, risk alerts.

### 3.3 Future: Algorithmic Trader

Custom strategies + auto-execution. Phase 2+. Deferred until safety battle-tested.

### 3.4 MVP User Journey

- Sign up, select broker (Alpaca recommended for full experience)
- OAuth — authenticate directly with broker
- Portfolio syncs: positions, balances, history (read-only, idempotent)
- Instruments mapped: broker symbols → canonical (exchange, symbol)
- AI engine: technical + fundamental + sentiment analysis
- Dashboard: health score, risk meter (with drill-down), insight feed
- User reviews recommendations, executes manually on broker
- Risk Guardian monitors and sends dashboard/email alerts

## 4. System Architecture

| *Monolith-modular. FastAPI is sole auth authority. No NextAuth. Next.js is pure API consumer. Extract to services at team size 3+.* |
| --- |

### 4.1 Layers

- **Layer 1 — Broker Abstraction:** Unified adapter with feature flags, conformance tests, symbol mapping.
- **Layer 2 — Data Aggregation:** Free sources, DataProvider abstraction, session-aware collection.
- **Layer 3 — Analysis:** Deterministic. pandas-ta, fundamentals, FinBERT, risk models.
- **Layer 4 — Intelligence:** Weighted composite scoring. ExplainerProvider abstraction (template default).
- **Layer 5 — Safety:** All guardrails. Kill switch. Immutable audit. Nothing bypasses.
- **Layer 6 — Presentation:** Next.js dashboard, FastAPI REST + WebSocket.

### 4.2 Tech Stack

| **Component** | **Technology** | **Notes** |
| --- | --- | --- |
| **Backend + Auth** | **Python / FastAPI (JWT issuer)** | **Sole auth authority** |
| **Frontend** | **Next.js + Tailwind** | **Pure API consumer** |
| **Database** | **PostgreSQL + Redis** | **Relational + cache/queue** |
| **Task Queue** | **Celery + Redis** | **Session-aware scheduler** |
| **Technical Analysis** | **pandas-ta** | **Deterministic, $0** |
| **Sentiment** | **FinBERT (local)** | **CPU inference, $0** |
| **Explanations** | **TemplateExplainer (default)** | **LLM optional behind flag** |
| **Market Calendar** | **exchange_calendars** | **NSE (XBOM) + US (XNYS/XNAS)** |
| **Deployment** | **Docker Compose ($0) / Railway** | **$0 local or $20–$50 hosted** |
| **Encryption** | **AES-256-GCM, TLS 1.3** | **Dual-key rotation supported** |
| **Notifications** | **WebSocket + optional SMTP** | **Dashboard default, email opt-in** |

## 5. Broker Integration Layer

### 5.1 Adapter Design

Abstract BrokerAdapter with feature flags. Methods: authenticate(), refresh_token(), get_positions(), get_balances(), get_orders(), get_order_history(), normalize_symbol(). In MVP, place_order() raises NotImplementedError. Conformance test suite validates behavioral alignment between adapters.

### 5.2 Zerodha Kite

| **Parameter** | **Details** |
| --- | --- |
| **API / Auth** | **Kite Connect v3. OAuth-like redirect flow. Token expires daily (~6 AM IST).** |
| **MVP Posture** | **Limited mode: sync only after daily login. Dashboard badge shows token status.** |
| **Rate / Cost** | **10 req/sec. ₹2,000/month mandatory.** |
| **Symbol Format** | **RELIANCE, INFY (plain). Mapped to canonical via symbol_mappings.** |

### 5.3 Alpaca

| **Parameter** | **Details** |
| --- | --- |
| **API / Auth** | **Trading API v2. OAuth2 + API key/secret. Long-lived tokens.** |
| **MVP Posture** | **Default broker. Paper trading for all validation. Free real-time IEX data.** |
| **Rate / Cost** | **200 req/min. Free including paper trading.** |
| **Symbol Format** | **AAPL, INFY (standard US). Direct mapping to canonical.** |

### 5.4 Security

- **Encryption:** AES-256-GCM. Per-user key via HKDF. Dual-key rotation window.
- **Scope:** Read-only OAuth scopes in MVP.
- **Audit:** Every broker API call logged.
- **Key rotation:** Zero-downtime dual-key procedure (see Tech Spec for operational steps).

## 6. Instrument Identity & Symbol Mapping

### 6.1 Canonical Identifier

Every instrument is uniquely identified by (exchange, symbol) using ISO MIC codes: XNSE (NSE), XBOM (BSE), XNYS (NYSE), XNAS (NASDAQ). Optional ISIN for cross-listing correlation. INFY on XNSE and INFY on XNYS are separate instruments.

### 6.2 Broker Symbol Mapping

A symbol_mappings table resolves broker-specific symbol conventions:

| **Canonical** | **Exchange** | **Zerodha** | **Alpaca** | **Yahoo Finance** |
| --- | --- | --- | --- | --- |
| **RELIANCE** | **XNSE** | **RELIANCE** | **N/A** | **RELIANCE.NS** |
| **AAPL** | **XNAS** | **N/A** | **AAPL** | **AAPL** |
| **INFY** | **XNSE** | **INFY** | **N/A** | **INFY.NS** |
| **INFY** | **XNYS** | **N/A** | **INFY** | **INFY** |

### 6.3 Resolution Flow

On broker sync: broker_symbol → look up symbol_mappings → get instrument_id. If no mapping exists, create new instrument + mapping. Data layer uses data_symbol (e.g., RELIANCE.NS) for Yahoo Finance queries. Each adapter has normalize_symbol() in its conformance contract.

## 7. Market Sessions & Scheduling

### 7.1 Trading Hours

| **Market** | **Local Hours** | **UTC** | **Notes** |
| --- | --- | --- | --- |
| **NSE/BSE** | **9:15 AM–3:30 PM IST** | **3:45 AM–10:00 AM** | **Pre-open 9:00–9:15** |
| **NYSE/NASDAQ** | **9:30 AM–4:00 PM ET** | **2:30 PM–9:00 PM*** | ***DST shifts. Half-days handled.** |

### 7.2 Calendar Source

- **Primary:** exchange_calendars Python library (XBOM for NSE, XNYS/XNAS for US). Covers holidays, half-days, Muhurat trading.
- **Fallback:** calendar_overrides table for ad-hoc holidays. If broker returns “market closed” unexpectedly, auto-create override entry.
- **Verification:** Weekly job compares library output against broker holiday lists. Logs discrepancies.

### 7.3 Session-Aware Scheduler

- **In-session:** Quote streaming, 5-min indicator recalc, hourly portfolio sync. Per-market.
- **Post-close:** OHLCV, fundamentals, risk recalc, portfolio snapshot. Triggered by session close event (not fixed cron).
- **Always:** News (15 min), sentiment batch, FX daily at 6 AM UTC.
- **Holidays:** Skip in-session jobs. Run always-jobs.

## 8. Core Data Layer (Free-Only Stack)

| **Data Type** | **Source** | **Cost** | **Latency** | **Risk** |
| --- | --- | --- | --- | --- |
| **US Real-time** | **Alpaca** | **Free** | **Real-time** | **Low** |
| **IN Real-time** | **Zerodha Kite** | **₹2K/mo** | **Real-time** | **Low** |
| **Historical** | **Yahoo Finance** | **Free** | **15-min delay** | **HIGH** |
| **US Fundamentals** | **SEC EDGAR** | **Free** | **Quarterly** | **Low** |
| **Economic** | **FRED API** | **Free** | **Daily** | **Low** |
| **News** | **GNews** | **Free tier** | **Near RT** | **Medium** |
| **Sentiment** | **FinBERT (local)** | **Free** | **<1 sec** | **Low** |
| **FX Rates** | **FRED / ECB** | **Free** | **Daily** | **Low** |
| **Indicators** | **pandas-ta** | **Free** | **Computed** | **None** |

## 9. Free Data: Productization Caveats

| *Every free data dependency has documented risk, mitigation, and a named paid escape hatch.* |
| --- |

### 9.1 Yahoo Finance

- **Risk:** No official API. yfinance scrapes internal endpoints. ToS prohibits automated scraping. Can break without notice.
- **Mitigation:** Cache 24h (fundamentals), 1h (OHLCV). DataProvider abstraction for swap.
- **Escape hatch:** Polygon.io ($29/mo) or Twelve Data. Same interface, swap implementation.

### 9.2 GNews

- **Risk:** 100 req/day on free tier. Official API, commercial use allowed.
- **Mitigation:** Batch by sector. Supplement with RSS.
- **Escape hatch:** NewsAPI.org ($449/mo) or Aylien.

### 9.3 Reddit

- **Risk:** API access could be further restricted. Not critical dependency.
- **Mitigation:** Social sentiment at 20% weight. Degrade gracefully if unavailable.

### 9.4 Upgrade Trigger

Upgrade from free to paid when: source has >3 outages/month OR revenue exceeds 5x the data cost.

## 10. Corporate Actions

| *Without this, stock splits break historical indicators and P&L. Must be addressed before launch.* |
| --- |

### 10.1 Scope

| **Action** | **Effect** | **Handling** |
| --- | --- | --- |
| **Stock Split** | **Prices and quantities change** | **Adjust historical OHLCV + recalc indicators** |
| **Bonus Issue** | **Equivalent to split** | **Same adjustment logic** |
| **Dividend** | **Affects P&L attribution** | **Record. Include in attribution (Phase 2)** |
| **Rights Issue** | **Optional participation** | **Flag to user. No auto-handling.** |

### 10.2 Detection

Two sources: Yahoo Finance adjustment factors on daily data refresh, and broker sync anomaly detection (position qty changed without a corresponding trade in order history).

### 10.3 Adjustment Pipeline

- Detect action, record in corporate_actions table
- Multiply all pre-ex-date OHLCV by adjustment factor
- Invalidate cached indicators, trigger full recalculation
- Mark applied=true, log to audit trail

## 11. AI & Analysis Engine

| *All MVP analysis is deterministic. Given same inputs, same outputs. Phase 2+ adds optional AI-enhanced scoring (capped at 30%, fully audited, user opt-in) after legal review and 3 months of shadow-mode validation.* |
| --- |

### 11.1 Technical Analysis (pandas-ta)

RSI (20%), MACD (20%), MA alignment (25%), Bollinger (15%), Volume (10%), ATR (10%). Composite −1 to +1 → Strong Sell to Strong Buy.

### 11.2 Fundamental Analysis

Revenue Growth (25%), Earnings Trend (25%), Debt Health (20%), P/E Valuation (15%), Cash Flow (15%). Each 0–100 vs sector peers.

### 11.3 Sentiment (FinBERT)

News 50%, Social 20%, Macro 30%. Decay: 24h half-life (news), 1h (social).

### 11.4 Risk Modeling

VaR (95%/99% historical simulation), volatility (30d/90d annualized), drawdown from peak, position risk score 0–100.

### 11.5 Recommendation Synthesis

| **Signal** | **MVP** | **Phase 2+ (no AI)** | **Phase 2+ (AI at 20%)** |
| --- | --- | --- | --- |
| **Technical** | **40%** | **30%** | **32% (40% × 0.80)** |
| **Fundamental** | **25%** | **20%** | **20% (25% × 0.80)** |
| **Sentiment** | **20%** | **15%** | **16% (20% × 0.80)** |
| **Risk** | **15%** | **15%** | **12% (15% × 0.80)** |
| **Predictive** | **N/A** | **20%** | **N/A (mutually exclusive with AI)** |
| **AI Analysis** | **N/A** | **N/A** | **20% (max 30%)** |

Output: Action, Confidence (0–100%), Risk-Adjusted Rating, Explanation (template default, LLM optional).

## 12. LLM & Explanation Policy

| *In MVP, LLMs only generate explanations of decisions already made deterministically. Phase 2+ optionally blends AI-enhanced analysis scores (capped at 30%, fully audited, user opt-in) into recommendations after legal review.* |
| --- |

| **Provider** | **Availability** | **Cost** | **Notes** |
| --- | --- | --- | --- |
| **TemplateExplainer** | **Always (default)** | **$0** | **Deterministic, <10ms** |
| **ClaudeCliExplainer** | **Local/dev only** | **$0** | **Guarded: timeout 10s, PII redacted, hosted env blocked at code level** |
| **ApiExplainer** | **BYOK, Phase 2+** | **User pays** | **Pro/Premium only** |

Fallback chain: any provider failure → TemplateExplainer. Dashboard never blocked. Audit logs which provider generated each explanation.

## 13. Operating Modes

| *MVP: Modes A, D, E only. Strictly read-only. No broker writes.* |
| --- |

### 13.1 Mode A: Recommendation [MVP]

Deterministic scoring. Template explanations. User reads, acts manually on broker. Hourly + on-demand.

### 13.2 Mode B: Assisted Trading [Phase 2]

AI suggests → User approves → System executes. Requires 3+ months safety validation + regulatory review.

### 13.3 Mode C: Fully Automated [Phase 2+]

Strategy rules, auto-execution with guardrails. Requires backtesting + 1+ month paper validation + legal review.

### 13.4 Mode D: Portfolio Intelligence [MVP]

Diversification, risk concentration, sector allocation vs benchmark (per-market native currency), performance attribution, rebalancing suggestions (display only).

### 13.5 Mode E: Risk Guardian [MVP]

Position monitoring, volatility alerts (>2x ADR), earnings alerts (5-day lookahead), macro alerts (FRED). Channels: dashboard toast + in-app feed (default), email (opt-in).

### 13.6 Mode F: AI-Enhanced Analysis [Phase 1: Shadow, Phase 2+: Live]

**Shadow mode (Phase 1/MVP):** AI analysis runs asynchronously during recommendation generation. Claude analyzes earnings calls, 10-K filings, and management guidance to produce an AIAnalysisScore (outlook 0–1, risks 0–1, reasoning, model version). Score is logged to `ai_analysis_log` table alongside `traditional_score` and hypothetical `blended_score`, but is NOT blended into the recommendation. Recommendation uses ONLY deterministic scoring.

**Live mode (Phase 2+):** Same as shadow, but AI score IS blended: `(1 - AI_weight) × traditional + AI_weight × AI_score`. Hard-blocked if `DEPLOYMENT_ENV=production` AND no legal review flag. Weight cap: 0.30 max enforced in code constant (`MAX_AI_WEIGHT`), not just env var. Requires 3 months of shadow data + legal review.

Two providers: ClaudeCliAnalyzer (local/dev only, subprocess, $0) and ApiAnalyzer (Anthropic SDK, BYOK, user pays).

## 14. Risk Meter & Portfolio Health

| *Deterministic, transparent, drillable. Users click to see exactly how the score was computed.* |
| --- |

### 14.1 Risk Meter Formula (0–100)

| **Component** | **Weight** | **Calculation** |
| --- | --- | --- |
| **Concentration** | **30%** | **HHI of position weights. 0=diversified, 100=single stock.** |
| **Volatility/VaR** | **30%** | **Portfolio 95% VaR as % of value, normalized 0–100.** |
| **Drawdown** | **20%** | **Current drawdown from peak. 0%=0, >20%=100.** |
| **Events** | **20%** | **Holdings with earnings/macro events in next 5 days, scaled 0–100.** |

Display: 0–30 green, 31–60 yellow, 61–100 red.

### 14.2 Portfolio Health Score

Separate metric. Diversification quality (25%), fundamental strength (25%), technical alignment (25%), risk-adjusted return vs benchmark (25%). Scored 0–100 (higher=healthier). Updated daily.

## 15. Risk Model Assumptions & Stale Data

### 15.1 Core Assumptions

| **Parameter** | **Spec** |
| --- | --- |
| **Returns** | **Daily close-to-close log returns. Not intraday.** |
| **VaR lookback** | **252 trading days. Minimum 30 days required.** |
| **VaR method** | **Historical simulation (percentile of actual returns).** |
| **Volatility** | **Annualized std dev of daily returns. 30d and 90d windows.** |
| **Correlation** | **Pearson on daily returns. 90d rolling.** |
| **Missing data** | **Forward-fill up to 5 days. Beyond: exclude from correlation, flag insufficient.** |

### 15.2 Insufficient Data (<30 days)

VaR: not computed, show “Insufficient data.” Volatility: compute but label “(estimated).” Risk Score: use sector-average as proxy, flag “proxy-based.”

### 15.3 Stale Data Impact

| **Level** | **Age** | **Risk Meter** | **Recommendations** |
| --- | --- | --- | --- |
| **Fresh** | **<1h (in session)** | **Normal** | **Normal confidence** |
| **Aging** | **1–4 hours** | **Normal** | **Confidence −5%** |
| **Stale** | **4–24 hours** | **Yellow warning badge** | **Confidence −15%** |
| **Very stale** | **>24 hours** | **Red warning badge** | **Suppressed** |

## 16. FX, Base Currency & Benchmark Logic

### 16.1 Base Currency

User selects INR or USD at signup. All portfolio-level metrics in base currency. Position-level shows native + base.

### 16.2 FX Source

- **FRED API (primary) / ECB (fallback):** Daily rate, stored in fx_rates table. Refresh 6 AM UTC.
- **Conversion:** Positions in native currency. Converted for display. Historical P&L uses date-of-trade FX rate.

### 16.3 Benchmark Assignment

- **XNSE/XBOM positions:** Benchmark = Nifty 50 (^NSEI, in INR).
- **XNYS/XNAS positions:** Benchmark = S&P 500 (^GSPC, in USD).

### 16.4 Per-Market Alpha

Alpha computed per-market in native currency first. Indian holdings vs Nifty in INR. US holdings vs S&P in USD. No FX conflation in alpha.

### 16.5 Portfolio-Level Benchmark

Weighted blend: (IN allocation% × Nifty return in base currency) + (US allocation% × S&P return in base currency). Both converted via daily FX. Portfolio alpha = portfolio return minus blended benchmark.

### 16.6 FX Impact Attribution

For cross-currency positions: total return (base) = stock return (native) + FX return + cross term. Dashboard shows decomposition: “AAPL +8% USD, INR weakened 3%, your INR return: +11.2%.” Phase 1: simple note. Phase 2: full decomposition charts.

## 17. Safety & Risk Architecture

| *Foundational. Built first. In MVP, validates hypothetical actions for recommendation quality. Phase 2+, gates real execution.* |
| --- |

| **Control** | **Description** | **Default** | **Config?** |
| --- | --- | --- | --- |
| **Daily Loss Limit** | **Max portfolio loss/day** | **2%** | **Yes (min 1%)** |
| **Max Drawdown** | **Peak-to-trough** | **10%** | **Yes (min 5%)** |
| **Max Position** | **Single position %** | **10%** | **Yes (max 25%)** |
| **Kill Switch** | **Halt all automation** | **Always on** | **N/A** |
| **Duplicate Block** | **Block identical orders** | **60s window** | **Yes** |

### 17.1 Audit Trail

Append-only table. DB-level REVOKE UPDATE/DELETE + trigger guard. Personal: 1yr retention. SaaS: 7yr. Structured JSON, queryable.

## 18. Sync Idempotency & Reconciliation

| *Broker is ALWAYS source of truth. InvestIQ never assumes local state is correct.* |
| --- |

### 18.1 Idempotency Keys

| **Entity** | **Key** | **Behavior** |
| --- | --- | --- |
| **Position** | **(broker_connection_id, broker_symbol)** | **Upsert: update if exists, create if new** |
| **Order** | **(broker_connection_id, broker_order_id)** | **Upsert status/fills. Never duplicate.** |
| **Balance** | **(broker_connection_id, currency)** | **Overwrite with broker value** |

### 18.2 Reconciliation Rules

- **Position sync:** Fetch all from broker. Upsert each. Mark local positions absent from broker as closed (qty=0, user sold elsewhere).
- **Order sync:** Upsert by broker_order_id. Orders placed directly on broker are captured. Never delete orders.
- **Partial fills:** Update filled_qty from broker. Trust broker’s final position, not fill-level reconciliation.
- **Failure:** Each upsert is independent transaction. Partial sync → consistent but incomplete. Next sync completes. Stale threshold (2h) triggers confidence reduction.

## 19. Notifications & Alerts

### 19.1 Channels

| **Channel** | **Cost** | **Use** | **Mode** |
| --- | --- | --- | --- |
| **Dashboard toast** | **$0** | **All alerts, real-time WebSocket** | **Default (always)** |
| **In-app feed** | **$0** | **Persistent, queryable** | **Default (always)** |
| **Console log** | **$0** | **Alerts to stdout/file** | **Personal/local** |
| **Email (BYOSMTP)** | **$0** | **User provides SMTP creds** | **Personal opt-in** |
| **Email (Resend)** | **Free 100/day** | **Platform sends** | **SaaS Phase 2+** |

### 19.2 MVP Default

Dashboard toasts + in-app feed. No email required. Email is opt-in: personal users provide SMTP, SaaS uses Resend free tier. Future: Telegram bot, push, SMS.

## 20. User Experience

### 20.1 Dashboard

- **Portfolio Overview:** Total value (base currency), daily P&L, return.
- **Risk Meter:** 0–100 gauge with drill-down. Click to see formula components.
- **Broker Status:** Green (synced), Yellow (token expired), Gray (not connected).
- **Holdings:** Symbol, qty, price, P&L (native + base), AI rating, risk score.
- **Insight Feed:** Chronological cards. Shows explainer provider used.

### 20.2 Principles

- **Progressive disclosure:** Simple overview, depth on demand.
- **Transparency:** Every score shows formula. Every recommendation shows reasoning.
- **Safety visibility:** Risk meter + broker status always visible.
- **No dark patterns:** Never push toward riskier modes.

## 21. Monetization

| **Feature** | **Free** | **Pro $15–30** | **Premium $50–100** |
| --- | --- | --- | --- |
| **Brokers** | **1** | **2** | **Unlimited** |
| **Recommendations** | **Daily summary** | **Real-time** | **RT + history** |
| **Explainer** | **Template** | **Template + BYOK LLM** | **Template + BYOK** |
| **Email alerts** | **No (dashboard only)** | **Resend free tier** | **Priority email** |
| **Assisted Trading** | **No** | **Yes (Phase 2)** | **Yes** |
| **Automated** | **No** | **No** | **Yes (Phase 2+)** |

India: ₹499/mo (Pro), ₹1,499/mo (Premium).

## 22. Development Roadmap

### Phase 1: MVP (Months 1–4)

**Read-only modes A/D/E. Alpaca paper trading. Dashboard. Template explanations.**

**Month 1 — Core**

- FastAPI (sole auth + JWT) + Next.js + PostgreSQL + Redis + Docker Compose
- Alpaca adapter (paper). OAuth. AES-256-GCM token storage. Dual-key support.
- Instruments table + symbol_mappings. Broker conformance tests.
- Portfolio sync (idempotent upsert, broker=truth). Market calendar integration.

**Month 2 — Data & Analysis**

- Yahoo Finance pipeline + DataProvider abstraction + caching
- pandas-ta indicators, composite scoring
- FinBERT + GNews + sentiment pipeline
- FX pipeline (FRED/ECB). Corporate actions detection.
- Session-aware Celery scheduler. Calendar override table.

**Month 3 — Intelligence & Safety**

- Recommendation engine + TemplateExplainer + ExplainerProvider abstraction
- AI Analysis shadow mode (async, log-only, not blended into recommendations)
- Safety layer: limits, kill switch, immutable audit (trigger-guarded)
- Risk models: VaR (252d lookback, 30d min), volatility, drawdown
- Risk Meter (deterministic formula with drill-down)
- Portfolio Intelligence: diversification, sector allocation, per-market alpha

**Month 4 — Polish & Launch**

- Dashboard: risk meter, insight feed, holdings (native+base), broker status badges
- Risk Guardian + notification system (dashboard toasts + in-app feed)
- Zerodha adapter (limited mode, sandbox). Cross-market benchmark logic.
- Stale data handling. FX impact attribution (simple notes).
- Beta: 10–20 users on Alpaca paper trading

### Phase 2: Execution & Scale (Months 5–9)

- Assisted Trading (Mode B) — after regulatory review
- AI-Enhanced Analysis live mode (after legal review + 3 months shadow data)
- Backtesting. IBKR adapter. ApiExplainer (BYOK).
- Predictive models. Dividend-adjusted returns.
- Email via Resend. Stripe/Razorpay. Mobile-responsive.
- FX decomposition charts. FX risk in Risk Meter.

### Phase 3: Automation (Months 10–15)

- Fully Automated (Mode C). Strategy marketplace. Options/Crypto.
- Custom ML. AI strategy builder. Microservice extraction.

## 23. Regulatory Considerations

| *Not legal advice. Consult fintech attorney before execution features.* |
| --- |

- **India (SEBI):** IA registration for personalized paid advice. Algo trading rules tightening. DPDP Act compliance.
- **US (SEC):** IA Act for personalized advice. Publisher exclusion may apply. Not holding funds = likely no BD registration.
- **Mitigation:** Phase 1 read-only + disclaimers. Phase 2 engage attorney. Phase 3 full compliance ($10K–$50K).
- **AI Score Blending:** Legal review required before enabling live mode (AI scores blended into recommendations). Shadow mode (log-only) does not require legal review.

## 24. Success Metrics

| **Metric** | **Phase 1** | **Phase 2** | **Phase 3** |
| --- | --- | --- | --- |
| **Users** | **50–100** | **500–1K** | **5K+** |
| **WAU** | **30–50** | **200–400** | **2K+** |
| **AI accuracy** | **Baseline** | **>55%** | **>60%** |
| **Safety bypasses** | **ZERO** | **ZERO** | **ZERO** |

## 25. Risks & Mitigations

| **Risk** | **Severity** | **Mitigation** | **Contingency** |
| --- | --- | --- | --- |
| **Yahoo Finance breaks** | **High** | **DataProvider abstraction + cache** | **Swap to Polygon ($29/mo)** |
| **Regulatory action** | **High** | **Disclaimers + legal counsel** | **Read-only mode only** |
| **Bad AI advice** | **High** | **Deterministic scoring + disclaimers** | **Reduce confidence, add warnings** |
| **Security breach** | **Critical** | **AES-256, dual-key rotation, no tokens in logs** | **Immediate revocation** |
| **Stock split breaks data** | **Medium** | **Corporate actions pipeline** | **Manual adjustment + indicator recalc** |
| **Burnout** | **High** | **Strict MVP scope** | **Seek co-founder** |
| **Prompt injection in financial documents** | **High** | **Input sanitization (regex blocklist, max token limit, content classification pre-check)** | **Disable AI analysis; fall back to deterministic-only** |
| **AI model drift (score quality degrades over time)** | **Medium** | **Model version tracking per score, shadow mode comparison against traditional** | **Revert to shadow mode; retrain/update prompts** |
| **Weight misconfiguration (AI weight too high)** | **High** | **Hard cap 0.30 in code constant (MAX_AI_WEIGHT), audit log on weight changes** | **Automatic revert to 0.0 if anomaly detected** |

## 26. Open Questions

| **#** | **Question** | **Impact** | **By** |
| --- | --- | --- | --- |
| **1** | **Register as IA or publisher exclusion?** | **Regulatory** | **Before Phase 2** |
| **2** | **Simultaneous Zerodha + Alpaca?** | **Architecture** | **Month 1** |
| **3** | **Hosting region: India vs US vs multi?** | **Latency** | **Month 1** |
| **4** | **Entity structure: proprietorship/LLP/corp?** | **Tax, legal** | **Before revenue** |
| **5** | **Zerodha daily reauth UX: auto-retry or explicit?** | **UX** | **Month 1** |
| **6** | **Include FX risk in Risk Meter? (currently excluded)** | **Accuracy** | **Phase 2** |
| **7** | **BSE (XBOM) support alongside NSE, or NSE-only in MVP?** | **Instrument mapping** | **Month 1** |
| **8** | **Legal review for AI score blending — when to engage fintech attorney?** | **Regulatory** | **Before Phase 2 live mode** |

*End of PRD v1.2*

InvestIQ • March 2026

