# Supervisor Job: Mobile Dashboard Screens

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected clean
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Months 1-3 complete (foundation, data pipelines, analysis, risk models, recommendations, safety, notifications)

## Task
**Goal:** Build full mobile dashboard screens: Portfolio overview with total value and daily P&L, Risk Meter gauge widget with drill-down, Holdings list with AI rating badges, Insight feed with recommendation cards, Broker status badges, and Settings screen with base currency toggle and notification preferences.

**Problem Statement:**
The user currently has a basic mobile shell (from Month 1 Job 7) but no rich dashboard screens to visualize portfolio data, risk metrics, AI recommendations, or broker status. Without these screens, the beta launch (Job 24) has no user-facing value. This job delivers the complete mobile UI layer that ties together all backend services built in Months 1-3.

## Acceptance Criteria
- [ ] Given portfolio synced, when Portfolio tab opened, then shows total value in base currency + daily P&L + return percentage
- [ ] Given risk meter score 45, when gauge rendered, then shows yellow zone (31-60) with score "45" displayed
- [ ] Given risk meter tapped, then drill-down shows Concentration/VaR/Drawdown/Events breakdown with individual scores
- [ ] Given holding with recommendation, then shows AI rating badge (e.g., "Buy 72%") with color coding (green=buy, red=sell, gray=hold)
- [ ] Given holding in cross-currency portfolio (INR-base user holding AAPL), then shows P&L in both native currency (USD) and base currency (INR)
- [ ] Given insight feed opened, then shows chronological recommendation cards with explainer provider badge and confidence percentage
- [ ] Given Alpaca connected and synced, then broker badge shows green with "Synced" label
- [ ] Given Zerodha token expired, then broker badge shows yellow with "Re-login" action button
- [ ] Given broker not connected, then broker badge shows gray with "Connect" action button
- [ ] Given Settings screen opened, then shows base currency toggle (INR/USD), notification preferences, and broker connections management

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | Portfolio overview component (value, P&L, return) | AC #1 | 1 modify (mobile/src/app/(tabs)/portfolio.tsx), 2 create (mobile/src/components/PortfolioSummary.tsx, mobile/src/components/PnLDisplay.tsx) | React Native styling, TanStack Query | LAUNCHABLE |
| 2 | Risk Meter gauge widget + drill-down | AC #2, #3 | 0 modify, 3 create (mobile/src/components/RiskMeterGauge.tsx, mobile/src/components/RiskDrillDown.tsx, mobile/src/hooks/useRiskMeter.ts) | React Native SVG/Canvas, animated gauge | LAUNCHABLE |
| 3 | Holdings list with AI rating badges | AC #4, #5 | 1 modify (mobile/src/app/(tabs)/portfolio.tsx), 3 create (mobile/src/components/HoldingsList.tsx, mobile/src/components/HoldingRow.tsx, mobile/src/components/AIRatingBadge.tsx) | React Native FlatList, badge patterns | BLOCKED (by #1 — shares portfolio.tsx) |
| 4 | Insight feed with recommendation cards | AC #6 | 1 modify (mobile/src/app/(tabs)/insights.tsx), 3 create (mobile/src/components/InsightFeed.tsx, mobile/src/components/InsightCard.tsx, mobile/src/hooks/useRecommendations.ts) | TanStack Query, card layout | LAUNCHABLE |
| 5 | Broker status badges | AC #7, #8, #9 | 0 modify, 2 create (mobile/src/components/BrokerStatusBadge.tsx, mobile/src/hooks/useBrokerStatus.ts) | React Native badge patterns | LAUNCHABLE |
| 6 | Settings screen (currency, notifications, brokers) | AC #10 | 1 modify (mobile/src/app/(tabs)/settings.tsx), 3 create (mobile/src/components/CurrencyToggle.tsx, mobile/src/components/NotificationPreferences.tsx, mobile/src/components/BrokerConnectionsManager.tsx) | React Native settings patterns | BLOCKED (by #5 — BrokerStatusBadge reused in settings) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (Portfolio overview) ──→ Subtask 3 (Holdings list — shares portfolio.tsx)
Subtask 2 (Risk Meter) ─────────── (independent)
Subtask 4 (Insight feed) ────────── (independent)
Subtask 5 (Broker badges) ──────→ Subtask 6 (Settings — reuses badge)
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 3 | mobile/src/app/(tabs)/portfolio.tsx | YES |
| Subtask 2 | Subtask 4 | none | NO |
| Subtask 5 | Subtask 6 | none (but component dependency) | YES (logical) |
| All others | — | none | NO |

### Batch Plan
- **Batch 1:** Subtask 1, 2, 4, 5 (parallel — no file overlap)
- **Batch 2:** Subtask 3 (after Subtask 1), Subtask 6 (after Subtask 5) — parallel with each other
- **Recommended workers:** 4 (Batch 1), 2 (Batch 2)
- **Estimated batches:** 2

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | TanStack Query hooks, React Native layout |
| 2 | React Native SVG/Canvas gauge, animated components |
| 3 | React Native FlatList, badge component patterns |
| 4 | TanStack Query infinite scroll, card layout |
| 5 | React Native badge/status indicator patterns |
| 6 | React Native settings screen patterns, toggle components |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Risk Meter gauge rendering performance on low-end devices | MEDIUM | Use react-native-svg for gauge; avoid heavy animations; test on older devices |
| Portfolio.tsx becomes too large with overview + holdings | MEDIUM | Extract all logic into child components; portfolio.tsx is composition only |
| Backend API responses may not match expected shape | HIGH | Define TypeScript interfaces matching Pydantic schemas; validate at API client layer |
| Cross-currency P&L display complexity (native + base) | MEDIUM | Use shared currency formatting util; test with INR-base user holding US stocks |
| Stale data from backend not reflected in UI | LOW | TanStack Query refetchOnFocus + polling interval for active screens |

## Configuration
- **Workers:** 4
- **Mode:** parallel
- **Estimated batches:** 2
- **Branch:** `feat/m4-21-mobile-dashboard`
- **Batch:** 9 (parallel with Jobs 22, 23; blocked by Month 3)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-m4-21-mobile-dashboard.md
```
