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

Also implement AIAnalysisProvider abstraction with shadow mode integration. When `AI_ANALYSIS_ENABLED=true`, `POST /api/recommendations/generate` triggers an async Celery task that runs AI analysis, validates output, sanitizes input, and logs results to `ai_analysis_log`. In shadow mode (Phase 1), the AI score is logged but NOT blended. In live mode (Phase 2+), the AI score is blended with weight redistribution (cap 0.30 via `MAX_AI_WEIGHT` code constant).

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

### MODE 4 (AI-Enhanced Analysis) Acceptance Criteria
- [ ] Given `AI_ANALYSIS_ENABLED=true` and `AI_ANALYSIS_SHADOW_MODE=true`, when POST /api/recommendations/generate, then AI analysis runs as async Celery task, result logged to `ai_analysis_log` with `shadow_mode=true`, recommendation uses ONLY traditional score
- [ ] Given `DEPLOYMENT_ENV=production` and `AI_ANALYSIS_SHADOW_MODE=false`, when no legal review flag set, then live mode hard-blocked (AI_ANALYSIS_SHADOW_MODE forced to true)
- [ ] Given AI analysis returns malformed output (missing fields, wrong types), when parsed, then Pydantic validation catches it, `status=error` logged to `ai_analysis_log`
- [ ] Given AI score with `outlook=1.5` or `risks=-0.2`, when validated, then values clamped to 0.0-1.0 range
- [ ] Given `AI_ANALYSIS_WEIGHT=0.35` in env var, when weight loaded, then capped to `MAX_AI_WEIGHT=0.30` (code constant enforcement)
- [ ] Given AI analysis failure (timeout, error, refused), when recommendation generated, then AI excluded, weight redistributed to deterministic components proportionally
- [ ] Given `ai_analysis_log` write fails (DB error), when AI result available, then warning logged, AI result discarded (not retried), recommendation proceeds with traditional score only

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | ExplainerProvider abstraction + TemplateExplainer | AC #3, #4, #9 | 0 modify, 3 create (backend/app/intelligence/explainers/__init__.py, backend/app/intelligence/explainers/base.py, backend/app/intelligence/explainers/template.py) | Python ABC | LAUNCHABLE |
| 2 | Recommendation synthesizer | AC #1, #2, #5, #6, #7, #8, #10 | 0 modify, 3 create (backend/app/intelligence/__init__.py, backend/app/intelligence/synthesizer.py, backend/app/schemas/recommendation.py) | numpy, weighted scoring | LAUNCHABLE |
| 3 | AIAnalysisProvider abstraction + ClaudeCliAnalyzer + ApiAnalyzer | MODE 4 AC #1, #3, #4 | 0 modify, 4 create (backend/app/intelligence/ai_analysis/__init__.py, backend/app/intelligence/ai_analysis/base.py, backend/app/intelligence/ai_analysis/claude_cli.py, backend/app/intelligence/ai_analysis/api.py) | Python ABC, subprocess, Anthropic SDK | LAUNCHABLE |
| 4 | Shadow mode integration + ai_analysis_log writing | MODE 4 AC #1, #2, #7 | 1 modify (backend/app/tasks/ — add ai_analysis task), 1 create (backend/app/intelligence/ai_analysis/shadow.py) | Celery async tasks, SQLAlchemy | BLOCKED (by #3) |
| 5 | Output validation + range clamping | MODE 4 AC #3, #4 | 1 modify (backend/app/intelligence/ai_analysis/base.py — add validation), 1 create (backend/app/schemas/ai_analysis.py) | Pydantic v2, clamping | BLOCKED (by #3) |
| 6 | Input sanitization | MODE 4 (implicit) | 0 modify, 1 create (backend/app/intelligence/ai_analysis/sanitizer.py) | Regex, token counting | LAUNCHABLE |
| 7 | Wire synthesizer + explainer | — (integration) | 1 modify (backend/app/intelligence/synthesizer.py — import explainer + AI hook) | — | BLOCKED (by #1, #2, #4, #5) |
| 8 | Recommendations API endpoints | AC #11, #12, MODE 4 AC #1, #5 | 1 modify (backend/app/main.py — register router), 1 create (backend/app/api/recommendations.py) | FastAPI | BLOCKED (by #7) |
| 9 | Tests | All ACs (incl. MODE 4) | 0 modify, 4 create (backend/tests/test_synthesizer.py, backend/tests/test_explainers.py, backend/tests/test_ai_analysis.py, backend/tests/test_recommendations_api.py) | pytest, time mocking, subprocess mocking | BLOCKED (by #8) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (explainer) ──┐
Subtask 2 (synthesizer) ─┤
Subtask 3 (AI provider) ─┤──→ Subtask 4 (shadow integration) ─┐
Subtask 6 (sanitizer)   ─┘──→ Subtask 5 (output validation)  ─┤──→ Subtask 7 (wire) ─→ Subtask 8 (API) ─→ Subtask 9 (tests)
                                                               ┘
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | none | NO |
| Subtask 3 | Subtask 6 | none | NO |
| Subtask 4 | Subtask 5 | backend/app/intelligence/ai_analysis/base.py | YES |
| Subtask 2 | Subtask 7 | backend/app/intelligence/synthesizer.py | YES |

### Batch Plan
- **Batch 1:** Subtask 1, 2, 3, 6 (parallel — no file overlap)
- **Batch 2:** Subtask 4, 5 (serialized on base.py — run 5 first, then 4)
- **Batch 3:** Subtask 7 (wires explainer + synthesizer + AI)
- **Batch 4:** Subtask 8 (API)
- **Batch 5:** Subtask 9 (tests)
- **Recommended workers:** 3
- **Estimated batches:** 5

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
