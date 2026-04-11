# Supervisor Job: Risk Meter (Deterministic Formula) + Portfolio Health Score

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected initialized (by Job 1)
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Month 2 complete (data pipelines, analysis engines). Parallel with Job 15 (risk models) — uses its own internal computations, does not import from risk.py at MVP.

## Task
**Goal:** Implement the Risk Meter (0-100 deterministic formula with 4 weighted components: Concentration 30%, Volatility/VaR 30%, Drawdown 20%, Events 20%) with color classification and drill-down API, plus a separate Portfolio Health Score (0-100 with 4 equal-weight components: diversification, fundamental strength, technical alignment, risk-adjusted return vs benchmark), updated daily.

**Problem Statement:**
Users need a single at-a-glance risk indicator for their portfolio and a health score to understand portfolio quality. Without these, the dashboard lacks its primary visual element (the risk gauge) and users cannot assess portfolio quality. Currently, no composite risk or health metrics exist. Success looks like deterministic, transparent scores that users can drill into to see exactly how each component was computed.

## Acceptance Criteria
- [ ] Given portfolio with single stock, when risk meter computed, then concentration component = 100 (HHI max for single holding)
- [ ] Given portfolio with 20 equal-weight stocks, when risk meter computed, then concentration component is low (~5)
- [ ] Given risk meter score 25, then classified as "green" (0-30)
- [ ] Given risk meter score 45, then classified as "yellow" (31-60)
- [ ] Given risk meter score 75, then classified as "red" (61-100)
- [ ] Given GET /api/portfolio/risk-meter, then returns overall score + color classification
- [ ] Given GET /api/portfolio/risk-meter/drilldown, then returns all 4 components with individual scores and weights
- [ ] Given portfolio with holdings that have earnings in next 5 days, when events component computed, then scaled proportionally
- [ ] Given portfolio health score computed, then returns 0-100 with 4 component breakdown (diversification, fundamental, technical, risk-adjusted)
- [ ] Given GET /api/portfolio/health-score, then returns overall score + 4 component scores
- [ ] Given health score computation, then updated daily (not on every request)

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | Risk Meter engine (4 components) | AC #1, #2, #3, #4, #5, #8 | 0 modify, 2 create (backend/app/analysis/risk_meter.py, backend/app/schemas/risk_meter.py) | HHI formula, numpy | LAUNCHABLE |
| 2 | Portfolio Health Score engine | AC #9, #11 | 0 modify, 2 create (backend/app/analysis/health_score.py, backend/app/schemas/health_score.py) | pandas, numpy | LAUNCHABLE |
| 3 | Risk Meter + Health Score API endpoints | AC #6, #7, #10 | 1 modify (backend/app/main.py — register routers), 2 create (backend/app/api/risk_meter.py, backend/app/api/health_score.py) | FastAPI | BLOCKED (by #1, #2) |
| 4 | Tests | All ACs | 0 modify, 2 create (backend/tests/test_risk_meter.py, backend/tests/test_health_score.py) | pytest | BLOCKED (by #3) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (risk meter) ──┬──→ Subtask 3 (API) ──→ Subtask 4 (tests)
Subtask 2 (health score) ┘
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | none | NO |
| Subtask 1 | Subtask 3 | none (but logical dep) | YES (dep) |
| Subtask 2 | Subtask 3 | none (but logical dep) | YES (dep) |

### Batch Plan
- **Batch 1:** Subtask 1, Subtask 2 (parallel — no file overlap)
- **Batch 2:** Subtask 3 (depends on 1, 2)
- **Batch 3:** Subtask 4 (depends on 3)
- **Recommended workers:** 2
- **Estimated batches:** 3

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | HHI (Herfindahl-Hirschman Index), VaR normalization, drawdown from peak |
| 2 | Diversification metrics, benchmark comparison, Sharpe-like ratios |
| 3 | FastAPI router, Pydantic v2 response models |
| 4 | pytest, httpx AsyncClient |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Events component requires earnings calendar data (not yet built) | MEDIUM | Use a simple stub/placeholder; accept empty events list as 0 score |
| VaR normalization range unclear for volatility component | LOW | Define explicit mapping: 0% VaR = 0 score, >= 5% VaR = 100 score |
| Health score benchmark data may not be available | MEDIUM | Use Nifty/S&P benchmark returns from data pipelines (Month 2); fallback to 0 if unavailable |
| Determinism: floating point rounding across platforms | LOW | Round to 1 decimal place for display; use consistent numpy dtype |

## Configuration
- **Workers:** 2
- **Mode:** parallel
- **Estimated batches:** 3
- **Branch:** `feat/m3-16-risk-meter-health`
- **Batch:** 7 (parallel with Jobs 15, 17, 18, 19)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-m3-16-risk-meter-health-score.md
```
