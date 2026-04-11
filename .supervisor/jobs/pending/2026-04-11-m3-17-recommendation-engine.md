# Supervisor Job: Recommendation Engine + ExplainerProvider Abstraction

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected initialized (by Job 1)
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Month 2 complete (technical, fundamental, sentiment analysis engines operational)

## Task
**Goal:** Build the recommendation synthesizer with weighted composite scoring (Technical 40%, Fundamental 25%, Sentiment 20%, Risk 15%), outputting Action (strong_buy/buy/hold/sell/strong_sell), Confidence (0-100%), Risk-Adjusted Rating, and Explanation. Implement TemplateExplainer as the default (<10ms, deterministic), ExplainerProvider abstraction (base.py) for future ClaudeCliExplainer and ApiExplainer, fallback chain (any failure -> TemplateExplainer), stale data confidence penalties, and audit logging of explainer_used. Expose via GET /api/recommendations and POST /api/recommendations/generate.

**Problem Statement:**
The platform's core value proposition is AI-driven investment recommendations. Without the synthesizer, individual analysis scores (technical, fundamental, sentiment, risk) exist in isolation with no actionable output. Users need a single recommendation with confidence and explanation. Currently, analysis engines produce scores but nothing combines them into recommendations. Success looks like deterministic, reproducible recommendations with transparent explanations that degrade gracefully when data is stale.

## Acceptance Criteria
- [ ] Given all 4 analysis scores for AAPL, when synthesized, then returns action (strong_buy/buy/hold/sell/strong_sell) + confidence (0-100%) + risk-adjusted rating + explanation
- [ ] Given composite score > 0.6, then action = strong_buy; 0.3-0.6 = buy; -0.3 to 0.3 = hold; -0.6 to -0.3 = sell; < -0.6 = strong_sell
- [ ] Given TemplateExplainer, when explain() called, then returns deterministic text in <10ms
- [ ] Given ExplainerProvider base class, then defines abstract explain(recommendation) -> str interface with provider_name property
- [ ] Given fresh data (<1h), when recommendation generated, then confidence at full computed value
- [ ] Given aging data (1-4h), when recommendation generated, then confidence reduced by 5%
- [ ] Given stale data (4-24h), when recommendation generated, then confidence reduced by 15%
- [ ] Given very stale data (>24h), then recommendation suppressed (not generated, returns stale status)
- [ ] Given explainer failure (any provider), then falls back to TemplateExplainer (never blocks recommendation)
- [ ] Given recommendation generated, then audit log records explainer_used (template|claude_cli|api)
- [ ] Given GET /api/recommendations, then returns list of current recommendations for user's portfolio
- [ ] Given POST /api/recommendations/generate, then triggers fresh recommendation generation

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | ExplainerProvider abstraction + TemplateExplainer | AC #3, #4, #9 | 0 modify, 3 create (backend/app/intelligence/explainers/__init__.py, backend/app/intelligence/explainers/base.py, backend/app/intelligence/explainers/template.py) | Python ABC | LAUNCHABLE |
| 2 | Recommendation synthesizer | AC #1, #2, #5, #6, #7, #8, #10 | 0 modify, 3 create (backend/app/intelligence/__init__.py, backend/app/intelligence/synthesizer.py, backend/app/schemas/recommendation.py) | numpy, weighted scoring | LAUNCHABLE |
| 3 | Wire synthesizer + explainer | — (integration) | 1 modify (backend/app/intelligence/synthesizer.py — import explainer) | — | BLOCKED (by #1, #2) |
| 4 | Recommendations API endpoints | AC #11, #12 | 1 modify (backend/app/main.py — register router), 1 create (backend/app/api/recommendations.py) | FastAPI | BLOCKED (by #3) |
| 5 | Tests | All ACs | 0 modify, 3 create (backend/tests/test_synthesizer.py, backend/tests/test_explainers.py, backend/tests/test_recommendations_api.py) | pytest, time mocking | BLOCKED (by #4) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (explainer) ──┬──→ Subtask 3 (wire) ──→ Subtask 4 (API) ──→ Subtask 5 (tests)
Subtask 2 (synthesizer) ┘
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | none | NO |
| Subtask 2 | Subtask 3 | backend/app/intelligence/synthesizer.py | YES |

### Batch Plan
- **Batch 1:** Subtask 1, Subtask 2 (parallel — no file overlap)
- **Batch 2:** Subtask 3 (wires 1 + 2 together)
- **Batch 3:** Subtask 4 (API)
- **Batch 4:** Subtask 5 (tests)
- **Recommended workers:** 2
- **Estimated batches:** 4

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | Python ABC, provider pattern |
| 2 | Weighted composite scoring, stale data handling, datetime arithmetic |
| 3 | Python imports, dependency injection |
| 4 | FastAPI router, Pydantic v2, JWT auth dependency |
| 5 | pytest, freezegun/time mocking, httpx AsyncClient |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Analysis engine APIs not standardized from Month 2 | MEDIUM | Define clear interface (get_technical_score, etc.); adapt to actual API shape |
| Stale data detection requires knowing when each analysis was last computed | MEDIUM | Store computed_at timestamp with each analysis score; compare against current time |
| Action thresholds may need tuning | LOW | Make thresholds configurable via constants; document in CLAUDE.md |
| Audit log table may not exist yet | LOW | Use existing audit_log table from schema; create if needed |

## Configuration
- **Workers:** 2
- **Mode:** parallel
- **Estimated batches:** 4
- **Branch:** `feat/m3-17-recommendation-engine`
- **Batch:** 7 (parallel with Jobs 15, 16, 18, 19)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-m3-17-recommendation-engine.md
```
