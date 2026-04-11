**PRODUCT REQUIREMENTS DOCUMENT**

**InvestIQ**

AI-Powered Investment Intelligence Platform

Version 1.0 • March 2026 • Confidential

|  |
| --- |
| *A smart middleware layer between investors and their broker accounts — connecting to Zerodha and Alpaca via official APIs, providing AI-driven portfolio analysis, risk management, and multi-mode trading intelligence built entirely on free and open-source data sources.* |

*Target Markets: India (NSE/BSE via Zerodha) • United States (via Alpaca)*

# **Table of Contents**

1. Executive Summary

2. Product Vision & Scope

3. Target Users & Personas

4. System Architecture Overview

5. Broker Integration Layer

6. Core Data Layer (Free-Only Stack)

7. AI & Analysis Engine

8. Operating Modes

9. Safety & Risk Architecture

10. User Experience

11. Monetization Strategy

12. Development Roadmap

13. Regulatory Considerations

14. Success Metrics & KPIs

15. Risks & Mitigations

16. Open Questions

# **1. Executive Summary**

InvestIQ is an AI-powered investment intelligence platform that acts as a smart middleware layer between retail/active traders and their existing brokerage accounts. It is not a broker — it connects to brokers (Zerodha for India, Alpaca for US) via official APIs using OAuth-based authentication.

The platform aggregates market data exclusively from free and open-source providers, applies technical, fundamental, and sentiment analysis through a hybrid AI engine, and operates across five distinct modes — from passive portfolio intelligence to fully automated trading with strict safety guardrails.

## **1.1 Problem Statement**

Retail and active traders face a fragmented experience: broker platforms offer execution but limited intelligence, third-party analysis tools are disconnected from execution, and AI-powered insights are either prohibitively expensive or require deep technical expertise. No unified, affordable platform combines intelligent analysis with broker-connected execution across both Indian and US markets.

## **1.2 Key Differentiators**

- **Middleware approach:** No regulatory burden of holding customer funds.
- **Zero data cost (Phase 1):** Yahoo Finance, FRED, SEC EDGAR, FinBERT, pandas-ta — all free.
- **Multi-mode operation:** Users choose their comfort level from passive insights to full automation.
- **Dual-market:** India (Zerodha/Kite) + US (Alpaca) with abstracted broker interface.
- **Safety-first:** Kill switch, loss limits, position sizing, audit trail built into core.
- **Live accounts:** Developer has active Zerodha and Alpaca accounts for real API testing.

# **2. Product Vision & Scope**

## **2.1 Vision**

|  |
| --- |
| *Make institutional-grade investment intelligence accessible to every trader — regardless of portfolio size, technical skill, or market — through an AI layer that connects to the broker they already trust.* |

## **2.2 In Scope (MVP)**

- Broker connectivity: Alpaca (US) + Zerodha Kite (India) via OAuth
- Portfolio sync: positions, orders, balances, trade history
- Market data: Alpaca free real-time (US), Yahoo Finance historical
- Technical analysis: RSI, MACD, SMA/EMA, Bollinger Bands, ATR
- Basic fundamentals: P/E, revenue, earnings via Yahoo Finance + SEC EDGAR
- News + sentiment: GNews free tier + FinBERT (local, open-source)
- Recommendation Mode: AI buy/sell suggestions with confidence and reasoning
- Portfolio Intelligence: diversification score, sector allocation, risk concentration
- Safety layer: daily loss limit, kill switch, position limits, audit trail
- Web dashboard: portfolio view, risk meter, AI insight feed

## **2.3 Deferred Features**

|  |  |  |
| --- | --- | --- |
| **Feature** | **Target Phase** | **Dependency** |
| Fully automated trading | Phase 2 | Safety validation |
| Assisted trading (execute via API) | Phase 2 | Regulatory review |
| Backtesting engine | Phase 2 | Historical data pipeline |
| Mobile application | Phase 2 | Stable web app |
| Additional brokers (IBKR, etc.) | Phase 2+ | Broker abstraction |
| Options strategies | Phase 3 | Paid data provider |
| Crypto asset support | Phase 3 | Exchange APIs |
| Strategy marketplace | Phase 3+ | User base + backtesting |
| Custom ML training pipeline | Phase 3 | Training data |

## **2.4 Constraints**

- **Solo developer:** Monolith-modular architecture. Microservices deferred.
- **Free data only:** 15-min delay on some data. Real-time only via Alpaca/Zerodha.
- **Fixed costs:** Zerodha Kite ₹2K/mo + LLM API ~$50–150/mo. Everything else: $0.
- **Paper trading first:** All testing via Alpaca paper trading until safety layer validated.

# **3. Target Users & Personas**

## **3.1 Primary: The Active Retail Trader**

Age 25–45. Trades 5–20 times/month. Portfolio ₹5L–₹50L or $10K–$200K across Indian and/or US markets. Uses Zerodha or Alpaca. Follows markets daily but lacks time for deep analysis. Wants AI-assisted insights but wants to stay in control.

## **3.2 Secondary: The Passive Investor**

Age 30–55. Holds mutual funds, ETFs, some stocks. Trades 1–5 times/month. Wants portfolio health monitoring, rebalancing suggestions, and risk alerts. Values Portfolio Intelligence and Risk Guardian modes.

## **3.3 Future: The Algorithmic Trader**

Technically sophisticated. Wants custom strategies with auto-execution. Served by Phase 2+ features. Deliberately deferred until safety architecture is battle-tested.

## **3.4 MVP User Journey**

1. Sign up and select broker (Zerodha or Alpaca)
2. OAuth flow — authenticate directly with broker
3. Portfolio syncs: positions, balances, order history
4. AI engine runs analysis: technical, fundamental, sentiment
5. Dashboard shows portfolio health, risk meter, AI insight feed
6. User reviews recommendations, executes manually on broker
7. Risk Guardian monitors positions and sends alerts

# **4. System Architecture**

## **4.1 Philosophy**

|  |
| --- |
| *Start monolith-modular, not microservices. A solo developer maintaining 8+ services is a recipe for burnout. Single deployable app with clean module boundaries, extractable into services later.* |

## **4.2 Layered Architecture**

- **Layer 1 — Broker Abstraction:** Unified interface wrapping Zerodha Kite and Alpaca APIs. OAuth, token mgmt, order routing, portfolio sync.
- **Layer 2 — Data Aggregation:** Collects/normalizes from free sources. Unified data access layer.
- **Layer 3 — Analysis Engine:** Technical (pandas-ta), fundamental, sentiment (FinBERT), risk models. Modular, independently testable.
- **Layer 4 — Intelligence:** Combines analysis into actionable signals. Confidence scores + natural language explanations.
- **Layer 5 — Safety & Risk:** Between intelligence and execution. All guardrails enforced here. Nothing bypasses this.
- **Layer 6 — Presentation:** Web dashboard (React/Next.js), API endpoints, WebSocket for real-time.

## **4.3 Tech Stack**

|  |  |  |
| --- | --- | --- |
| **Layer** | **Technology** | **Rationale** |
| **Backend** | Python / FastAPI | Best financial/ML ecosystem |
| **Frontend** | Next.js + TailwindCSS | SSR, fast iteration |
| **Database** | PostgreSQL + Redis | Relational + caching |
| **Real-time** | WebSockets (FastAPI) | Live updates, alerts |
| **Task Queue** | Celery + Redis | Background jobs |
| **Technical Analysis** | pandas-ta / TA-Lib | All indicators, zero cost |
| **Sentiment / NLP** | FinBERT (local) | Financial sentiment, free |
| **LLM** | Claude API (pay-as-go) | Trade reasoning |
| **Auth** | NextAuth.js + JWT | OAuth, sessions |
| **Deployment** | Railway / Render / VPS | Low cost, solo-dev friendly |
| **Encryption** | AES-256-GCM, TLS 1.3 | Tokens encrypted at rest |

# **5. Broker Integration Layer**

## **5.1 Unified Adapter Interface**

A BrokerAdapter abstract class wrapping broker-specific differences. Methods: authenticate(), refresh\_token(), get\_positions(), get\_balances(), get\_orders(), get\_order\_history(), place\_order(), cancel\_order(), get\_portfolio\_summary(). All return normalized data models.

## **5.2 Zerodha Kite**

|  |  |
| --- | --- |
| **Parameter** | **Details** |
| **API** | Kite Connect v3 |
| **Auth** | OAuth-like: redirect → request\_token → access\_token |
| **Token Life** | One trading day (expires ~6 AM IST next day) |
| **Rate Limits** | 10 req/sec. Orders: 5/sec |
| **Cost** | ₹2,000/month (mandatory) |
| **Data** | WebSocket real-time (Kite Ticker) + historical OHLCV |
| **Limitation** | Daily token refresh — user re-login or stored session |

## **5.3 Alpaca**

|  |  |
| --- | --- |
| **Parameter** | **Details** |
| **API** | Trading API v2 + Market Data API |
| **Auth** | OAuth2 standard + API key/secret for dev |
| **Rate Limits** | 200 req/min (trading) |
| **Cost** | Free (including real-time IEX + paper trading) |
| **Paper Trading** | Built-in, separate endpoint, same API |
| **Advantage** | Most developer-friendly broker API |

## **5.4 Security Requirements**

- **Encryption:** AES-256-GCM for all broker tokens at rest. Key in env var.
- **Refresh:** Automated before expiry. Zerodha: daily re-auth. Alpaca: token rotation.
- **Scope:** Minimum required OAuth scopes. Read-only for MVP.
- **Audit:** Every broker API call logged with timestamp and status.
- **Rate limiting:** Client-side limiter. Exponential backoff on 429s.

# **6. Core Data Layer (Free-Only Stack)**

|  |
| --- |
| *Every data source is free or open-source. Only paid dependency: Zerodha Kite ₹2K/mo (mandatory for broker access). LLM API ~$50–150/mo is optional.* |

## **6.1 Data Source Matrix**

|  |  |  |  |  |
| --- | --- | --- | --- | --- |
| **Data Type** | **Source** | **Cost** | **Latency** | **Reliability** |
| US Real-time | Alpaca Market Data | Free | Real-time | High |
| IN Real-time | Zerodha Kite Ticker | ₹2K/mo | Real-time | High |
| Historical OHLCV | Yahoo Finance | Free | 15-min delay | Medium |
| US Fundamentals | SEC EDGAR API | Free | Quarterly | High |
| IN Fundamentals | Yahoo Finance | Free | Daily | Medium |
| Economic Data | FRED API | Free | Daily | High |
| News | GNews API | Free tier | Near RT | Medium |
| Sentiment | FinBERT (local) | Free | < 1 sec | High |
| Social | Reddit API | Free | Polling | Low-Med |
| Indicators | pandas-ta (local) | Free | Computed | High |
| AI Explanations | Claude API | ~$100/mo | 2–5 sec | High |

## **6.2 Collection Schedule**

- **Real-time (WebSocket):** Alpaca streaming (US hours), Kite Ticker (NSE hours).
- **Every 5 min:** Technical indicator recalculation.
- **Every 15 min:** News fetch (GNews) + sentiment scoring batch.
- **Hourly:** Portfolio sync with broker.
- **Daily (market close):** Historical OHLCV, fundamentals refresh, risk model recalc.
- **Weekly:** SEC EDGAR filings, economic calendar update.

## **6.3 Free Tier Limitations**

- **Yahoo Finance:** Unofficial API (yfinance). Mitigation: cache aggressively, fallback to Alpaca historical.
- **GNews:** 100 req/day. Mitigation: batch by sector, supplement with RSS feeds.
- **Reddit:** Rate limits. Mitigation: poll key subreddits every 30 min, cache scores.

# **7. AI & Analysis Engine**

|  |
| --- |
| *Technical indicators = classical math, not AI. Sentiment = pre-trained ML. Only recommendation synthesis uses LLM APIs. This keeps AI costs minimal.* |

## **7.1 Technical Analysis (pandas-ta)**

|  |  |  |
| --- | --- | --- |
| **Indicator** | **Purpose** | **Output** |
| RSI (14) | Overbought/oversold detection | 0–100 + zone |
| MACD | Trend momentum, signal crossovers | Bullish/Bearish/Neutral |
| SMA/EMA | Trend direction, support/resistance | Above/Below + crossovers |
| Bollinger Bands | Volatility, mean reversion | Squeeze/Expansion |
| ATR (14) | Volatility for position sizing | Value + percentile |
| Volume Profile | Volume confirmation | Above/Below avg |

### **Composite Technical Score**

Each indicator → normalized signal (−1 to +1). Weighted average: RSI 20%, MACD 20%, MA alignment 25%, Bollinger 15%, Volume 10%, ATR 10%. Output: Strong Sell to Strong Buy.

## **7.2 Fundamental Analysis**

- **Revenue Growth:** YoY/QoQ. Flags deceleration.
- **Earnings Trend:** EPS over 4–8 quarters. Beats/misses streak.
- **Debt Ratio:** D/E vs. sector median. Flags high leverage.
- **P/E Ratio:** Current vs. sector avg and historical range.
- **Cash Flow:** FCF trend. Flags negative/declining.

Composite: each metric 0–100 vs. peers. Weighted: Revenue 25%, Earnings 25%, Debt 20%, Valuation 15%, Cash Flow 15%.

## **7.3 Sentiment Analysis**

### **FinBERT (Primary — Free, Local)**

BERT fine-tuned on financial text. Runs on CPU. Outputs positive/negative/neutral with confidence. ~50–100 headlines/sec.

- **News:** GNews + RSS feeds. Scored per-stock and per-sector.
- **Social:** Reddit API. r/stocks, r/wallstreetbets, r/IndianStreetBets.
- **Macro:** FRED indicators as positive/negative signals.

Composite: News 50%, Social 20%, Macro 30%. Decay: 24h half-life (news), 1h (social).

## **7.4 Risk Modeling**

- **Historical Volatility:** 30-day and 90-day annualized from daily returns.
- **Value at Risk:** 95% and 99% VaR, historical simulation. 1-day and 5-day horizons.
- **Drawdown Probability:** Current drawdown from peak + historical recovery times.
- **Position Risk Score:** Composite of volatility, VaR, concentration, correlation. 0–100.

## **7.5 Recommendation Synthesis**

|  |  |  |
| --- | --- | --- |
| **Signal Source** | **MVP Weight** | **Phase 2+ Weight** |
| Technical Analysis | 40% | 30% |
| Fundamental | 25% | 20% |
| Sentiment | 20% | 15% |
| Risk Model | 15% | 15% |
| Predictive (Phase 2) | N/A | 20% |

Output: Action (Strong Buy–Strong Sell), Confidence (0–100%), Risk-Adjusted Rating, Natural Language Explanation (Claude API).

# **8. Operating Modes**

Five modes, escalating trust. MVP: Modes A, D, E. Phase 2: Modes B, C.

## **8.1 Mode A: Recommendation [MVP]**

|  |
| --- |
| *Read-only. No execution. Safest starting point.* |

- **Function:** Analyzes portfolio, generates buy/sell/hold per holding + watchlist.
- **Output:** Action + confidence + reasoning for each.
- **Frequency:** On portfolio sync (hourly) and on-demand.
- **User action:** Reviews and manually executes on broker.

## **8.2 Mode B: Assisted Trading [Phase 2]**

|  |
| --- |
| *AI suggests, user approves, system executes. Requires write access.* |

- **Flow:** AI suggests → User reviews → Clicks Approve → System places order.
- **Safety:** Every trade through Safety Layer. No batch approvals.
- **Prerequisite:** 3+ months safety validation. Regulatory review.

## **8.3 Mode C: Fully Automated [Phase 2+]**

|  |
| --- |
| *System trades autonomously. Highest risk, most validation.* |

- **Guardrails:** Daily loss 2%, max position 5%, max 10 trades/day, kill switch.
- **Prerequisite:** Backtesting engine. 1+ month paper trading per strategy. Legal review.

## **8.4 Mode D: Portfolio Intelligence [MVP]**

- **Diversification Score:** Sector, geography, asset class distribution.
- **Risk Concentration:** Correlated positions, single-sector overweight.
- **Sector Allocation:** GICS breakdown vs. benchmark (Nifty 50 / S&P 500).
- **Performance Attribution:** P&L decomposition by position and sector.
- **Rebalancing:** Target vs. current drift, specific trade suggestions.

## **8.5 Mode E: Risk Guardian [MVP]**

- **Position Monitoring:** Real-time P&L, drawdown, volatility per position.
- **Volatility Alerts:** Stock moves > 2x average daily range.
- **Earnings Risk:** Flags positions with earnings in next 5 trading days.
- **Macro Risk:** FRED-sourced rate decisions, CPI, unemployment alerts.
- **Alert Channels:** Dashboard + email (MVP). Future: push, SMS, Telegram.

# **9. Safety & Risk Architecture**

|  |
| --- |
| *THIS IS THE MOST CRITICAL SECTION. The safety layer is foundational, not optional. No action bypasses it. Build first, not bolt on.* |

## **9.1 Safety Controls**

|  |  |  |  |
| --- | --- | --- | --- |
| **Control** | **Description** | **Default** | **Configurable?** |
| **Daily Loss Limit** | Max portfolio loss/day | 2% of portfolio | Yes (min 1%) |
| **Max Drawdown** | Max peak-to-trough | 10% of portfolio | Yes (min 5%) |
| **Max Position** | Single position % limit | 10% | Yes (max 25%) |
| **Max Trade Size** | Single trade value | 5% of portfolio | Yes (max 15%) |
| **Max Trades/Day** | Orders per day cap | 10 | Yes (max 50) |
| **Kill Switch** | Halt all automated activity | Always available | N/A |
| **Duplicate Block** | Block identical orders | 60-sec window | Yes |
| **Cooldown** | Pause after loss trigger | 24 hours | Yes (min 1h) |

## **9.2 Kill Switch**

One-click interrupt: cancels pending orders, disables automation, sets read-only, sends notification, logs full context. Triggers: dashboard button, API endpoint, automatic (any limit breach), health check failure.

## **9.3 Position Sizing Engine**

Calculates before any recommendation: fixed fractional (1% risk/trade), ATR-based (inverse proportional to volatility), Kelly Criterion (optional, half-Kelly capped). All capped by Max Position and Max Trade controls.

## **9.4 Audit Trail**

Immutable log: all recommendations (accepted/rejected), all orders (success/fail), all safety checks, all kill switch activations, all config changes, all broker API calls. Retention: 7+ years. Format: structured JSON, queryable via dashboard.

## **9.5 Error Handling**

- **Broker errors:** Retry with backoff (3x max). Verify order status before retry.
- **Data errors:** Stale data detection. Reduce confidence if data > threshold age.
- **Analysis errors:** Graceful degradation. Lower confidence from incomplete analysis.
- **System errors:** Health check failure → auto kill switch + notify user.

# **10. User Experience**

## **10.1 Dashboard (MVP)**

- **Portfolio Overview (top):** Total value, daily P&L, total return, health summary.
- **Risk Meter (top-right):** 0–100 gauge. Green/yellow/red.
- **Holdings Table (center):** Symbol, qty, avg price, current, P&L, AI rating, risk score. Sortable.
- **AI Insight Feed (right):** Chronological cards: title, summary, confidence, timestamp, expand for detail.

## **10.2 Additional Views**

- **Trade History:** All broker trades with P&L attribution.
- **Strategy Performance:** Win rate, avg return, Sharpe of followed vs ignored recommendations.
- **Risk Dashboard:** VaR chart, sector heatmap, correlation matrix, drawdown history.
- **Settings:** Broker connections, safety params, notifications, display prefs.

## **10.3 UX Principles**

- **Progressive disclosure:** Simple overview first, depth on demand.
- **Transparency:** Every AI recommendation shows reasoning. No black boxes.
- **Safety visibility:** Risk meter always visible. Users never forget risk controls exist.
- **No dark patterns:** Never push toward riskier modes. Automation requires multiple confirms.

# **11. Monetization Strategy**

## **Freemium SaaS**

|  |  |  |  |
| --- | --- | --- | --- |
| **Feature** | **Free** | **Pro $15–30/mo** | **Premium $50–100/mo** |
| Brokers | 1 | 2 | Unlimited |
| Dashboard | Basic | Full | Full + custom |
| AI Recommendations | Daily summary | Real-time | RT + history |
| Indicators | 3 basic | All | All + combos |
| Risk Alerts | Email, daily | Real-time | RT + hedging |
| Assisted Trading | No | Yes | Yes |
| Automated Trading | No | No | Yes |
| Backtesting | No | Basic | Full |

Indian pricing: ₹499/mo (Pro), ₹1,499/mo (Premium) adjusted for PPP.

# **12. Development Roadmap**

## **Phase 1: MVP (Months 1–4)**

**Working product with Alpaca paper trading, portfolio sync, basic AI, dashboard.**

**Month 1 — Core Infrastructure**

- FastAPI + Next.js + PostgreSQL + Redis setup
- Alpaca broker adapter (paper trading)
- OAuth + AES-256 token storage
- Portfolio sync: positions, balances, history
- Basic dashboard shell

**Month 2 — Data & Analysis**

- Yahoo Finance pipeline + caching
- pandas-ta: RSI, MACD, SMA/EMA, Bollinger, ATR
- Yahoo Finance fundamentals (P/E, revenue, earnings)
- FinBERT setup + GNews integration

**Month 3 — Intelligence & Safety**

- Recommendation engine + Claude API explanations
- Safety layer: limits, kill switch, audit trail
- Risk models: VaR, volatility, drawdown
- Portfolio Intelligence mode

**Month 4 — Polish & Launch**

- Complete dashboard: risk meter, insight feed, holdings
- Risk Guardian mode + alerts
- Zerodha Kite adapter (sandbox + live account)
- E2E testing, beta launch (10–20 users)

## **Phase 2: Execution & Scale (Months 5–9)**

- Assisted Trading mode (AI suggests, user approves, system executes)
- Backtesting engine
- Interactive Brokers adapter
- Predictive models: gradient boosting trends, GARCH volatility
- Mobile-responsive or React Native wrapper
- Freemium gating + Stripe/Razorpay payments
- SEC EDGAR deep fundamentals

## **Phase 3: Automation & Growth (Months 10–15)**

- Fully Automated Trading with comprehensive guardrails
- Regime detection (HMM), custom ML pipeline
- Options + Crypto support
- Strategy marketplace
- AI strategy builder (NL → rules)
- Extract heavy modules to microservices

# **13. Regulatory Considerations**

|  |
| --- |
| *Not legal advice. Consult a fintech attorney before any execution features.* |

## **13.1 India (SEBI)**

- **Investment Adviser:** Personalized paid advice triggers SEBI IA regulations. Read-only with disclaimers may exempt. Legal validation needed.
- **Research Analyst:** Public buy/sell recommendations may trigger RA registration.
- **Algo trading:** SEBI tightening rules. Algo orders may need exchange approval.
- **Data protection:** DPDP Act 2023 compliance for Indian user data.

## **13.2 United States (SEC)**

- **Investment Adviser Act:** Personalized advice for compensation requires registration. Publisher exclusion may apply for general recommendations.
- **Robo-adviser:** Automated individualized advice requires IA registration.
- **Broker-dealer:** Not holding funds = likely not required. Confirm with counsel.

## **13.3 Mitigation**

- Phase 1: Read-only. Disclaimers everywhere. Lowest risk.
- Phase 2: Engage fintech attorney. Potentially register RIA/IA.
- Phase 3: Full compliance. Budget $10K–50K for legal.

# **14. Success Metrics**

|  |  |  |  |
| --- | --- | --- | --- |
| **Metric** | **Phase 1** | **Phase 2** | **Phase 3** |
| Registered users | 50–100 | 500–1,000 | 5,000+ |
| Weekly active | 30–50 | 200–400 | 2,000+ |
| Paid subscribers | 0 (free beta) | 50–100 | 500+ |
| AI accuracy | Baseline | > 55% directional | > 60% |
| Monthly churn | < 15% | < 10% | < 7% |

## **Technical Metrics**

- API uptime: > 99.5% during market hours
- Portfolio sync: < 5 seconds
- Full analysis pipeline: < 30 seconds
- Dashboard load: < 2 seconds
- Zero safety bypasses (hard requirement)

# **15. Risks & Mitigations**

|  |  |  |  |
| --- | --- | --- | --- |
| **Risk** | **Severity** | **Mitigation** | **Contingency** |
| Yahoo Finance breaks | High | Cache, abstract data source | Switch to Alpaca historical |
| Regulatory action | High | Disclaimers, legal counsel | Disable execution, read-only |
| Broker API changes | Medium | Abstraction, version pinning | Rapid adapter update |
| Bad AI advice | High | Confidence thresholds, disclaimers | Reduce confidence, add warnings |
| Developer burnout | High | Strict MVP scope | Seek co-founder |
| Security breach | Critical | AES-256, env vars, no tokens in logs | Immediate token revocation |

# **16. Open Questions**

|  |  |  |  |
| --- | --- | --- | --- |
| **#** | **Question** | **Impact** | **Decide By** |
| 1 | Register as Investment Adviser or use publisher exclusion? | Regulatory | Before Phase 2 |
| 2 | Link both Zerodha AND Alpaca simultaneously? | Architecture | Phase 1 design |
| 3 | Hosting: India (Zerodha latency) or US (Alpaca latency)? | Infrastructure | Month 1 |
| 4 | Claude API vs OpenAI vs self-hosted LLM? | Cost, quality | Month 2 |
| 5 | Concurrent IN/US market session handling? | Architecture | Phase 1 |
| 6 | Entity: proprietorship, LLP, or incorporation? | Legal, tax | Before revenue |
| 7 | Zerodha daily token expiry: UX solution? | UX | Month 1 |

*End of Product Requirements Document*

InvestIQ v1.0 • March 2026
