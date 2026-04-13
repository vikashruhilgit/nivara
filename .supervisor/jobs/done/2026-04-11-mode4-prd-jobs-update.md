# Supervisor Job: MODE 4 (AI-Enhanced Analysis) — Spec & Jobs Update

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected clean
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** None — this is a Batch 0 documentation job that runs alongside Job 1 (repo scaffold), before any coding begins.

## Task
**Goal:** Update InvestIQ PRD v1.2, TechSpec v1.2, implementation.md, and 5 existing Supervisor job briefs to incorporate MODE 4: AI-Enhanced Analysis with shadow mode (Phase 1) and live mode (Phase 2+). This is a documentation-only job — no code is written. All spec files must be updated before coding begins so that implementation jobs have the correct specifications.

**Problem Statement:**
A red team review identified 5 FATAL issues with an earlier AI analysis design. The revised design introduces a phased approach: Phase 1 (MVP) runs AI analysis in shadow mode (scores computed and logged but NOT blended into recommendations), and Phase 2+ (after legal review + 3 months shadow data) enables live mode with configurable weight (capped at 0.30). Without updating the specs and job briefs first, implementation jobs will build against outdated specifications that lack AI analysis provider abstraction, shadow mode logging, input sanitization, and safety mitigations.

## Acceptance Criteria

### PRD Updates
- [ ] Given PRD section 1.1 (Key Differentiators), when "Deterministic-first AI" bullet read, then says: "Deterministic-first AI: All MVP analysis is reproducible math/rules. Phase 2+ adds optional AI-enhanced scoring (capped at 30%, audited, user opt-in) after legal review."
- [ ] Given PRD section 2.3 (NOT in MVP), when read, then includes row: "AI-Enhanced Analysis (live mode) | Phase 2+ | Legal review + 3 months shadow data"
- [ ] Given PRD section 11 header, when read, then updated determinism statement includes Phase 2+ caveat
- [ ] Given PRD section 12 header, when read, then updated LLM policy includes Phase 2+ caveat
- [ ] Given PRD section 13, when read, then includes Mode F: AI-Enhanced Analysis with shadow/live description
- [ ] Given PRD section 11.5 (Recommendation Synthesis), when read, then Phase 2+ column shows AI Analysis at configurable weight (max 30%) with weight redistribution formula
- [ ] Given PRD section 22 (Roadmap), when read, then Month 3 includes "AI Analysis shadow mode (log-only)" and Phase 2 includes "AI Analysis live mode (after legal review)"
- [ ] Given PRD section 23 (Regulatory), when read, then includes note about legal review required before AI score blending
- [ ] Given PRD section 25 (Risks), when read, then includes: prompt injection, model drift, weight misconfiguration
- [ ] Given PRD section 26 (Open Questions), when read, then includes: "Legal review for AI score blending — when to engage attorney?"

### TechSpec Updates
- [ ] Given TechSpec, when read, then includes new section for AI Analysis Provider Abstraction (AIAnalysisProvider interface, ClaudeCliAnalyzer, ApiAnalyzer, AIAnalysisScore schema)
- [ ] Given TechSpec, when read, then includes shadow mode specification (async Celery task, triggers on POST /api/recommendations/generate only, logs to ai_analysis_log, NOT blended)
- [ ] Given TechSpec, when read, then includes input sanitization specification (regex blocklist, max token limit, content classification)
- [ ] Given TechSpec section 3 (Schema), when read, then includes ai_analysis_log table with all columns (id, user_id, instrument_id, provider, ai_score JSONB, traditional_score, blended_score, model_version, prompt_hash, status, input_tokens, output_tokens, latency_ms, shadow_mode, created_at)
- [ ] Given TechSpec section 8.4 (Env Vars), when read, then includes all AI analysis env vars (AI_ANALYSIS_ENABLED, AI_ANALYSIS_PROVIDER, AI_ANALYSIS_SHADOW_MODE, AI_ANALYSIS_WEIGHT, AI_ANALYSIS_WEIGHT_CAP, AI_ANALYSIS_TIMEOUT, AI_ANALYSIS_MAX_DOCUMENT_TOKENS, AI_ANALYSIS_RATE_LIMIT, ANTHROPIC_API_KEY)

### Job 17 (Recommendation Engine) Updates
- [ ] Given Job 17, when read, then includes 4 new subtasks: AI Analysis Provider abstraction, shadow mode integration, output validation, input sanitization
- [ ] Given Job 17 acceptance criteria, when read, then includes: "Given AI_ANALYSIS_ENABLED=true and shadow mode, when POST /api/recommendations/generate, then AI score computed async and logged to ai_analysis_log but NOT blended into recommendation"
- [ ] Given Job 17 acceptance criteria, when read, then includes: "Given DEPLOYMENT_ENV=production and AI_ANALYSIS_SHADOW_MODE=false, when no legal review flag set, then live mode hard-blocked"
- [ ] Given Job 17 acceptance criteria, when read, then includes: "Given AI analysis returns malformed output, when parsed, then Pydantic validation catches it and status=error logged"
- [ ] Given Job 17 acceptance criteria, when read, then includes: "Given AI score outlook=1.5, when validated, then clamped to 1.0 (range enforcement)"
- [ ] Given Job 17 acceptance criteria, when read, then includes: "Given AI_ANALYSIS_WEIGHT=0.35, when validated, then capped to MAX_AI_WEIGHT=0.30 (code constant enforcement)"
- [ ] Given Job 17 acceptance criteria, when read, then includes: "Given AI analysis failure (timeout, error, refused), when recommendation generated, then AI excluded and weight redistributed to deterministic components"
- [ ] Given Job 17 acceptance criteria, when read, then includes: "Given ai_analysis_log write fails, when AI result available, then warning logged, AI result discarded (not retried)"

### Job 2 (Database) Updates
- [ ] Given Job 2, when read, then ai_analysis_log table included in initial migration list
- [ ] Given Job 2 acceptance criteria, when read, then table count updated from 14 to 15

### Job 14 (Celery Scheduler) Updates
- [ ] Given Job 14, when read, then notes that POST /api/recommendations/generate optionally triggers async AI analysis Celery task when AI_ANALYSIS_ENABLED=true

### Job 19 (Safety Layer) Updates
- [ ] Given Job 19, when read, then notes that safety validation applies to traditional_score only; blended_score in ai_analysis_log is informational (what-if) in shadow mode

### Job 21 (Mobile Dashboard) Updates
- [ ] Given Job 21, when read, then notes dev-only AI comparison view (traditional vs AI score side-by-side) — deferred or stub for Phase 2

### implementation.md Updates
- [ ] Given implementation.md, when read, then includes MODE 4 section with shadow/live phased design, flag system, provider abstraction, weight redistribution formula, and safety mitigations summary

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | Update PRD v1.2 | AC #1-10 (PRD) | 1 modify (`InvestIQ_PRD_v1.2.md`) | Technical writing, PRD structure | LAUNCHABLE |
| 2 | Update TechSpec v1.2 | AC #11-15 (TechSpec) | 1 modify (`InvestIQ_TechSpec_v1.2.md`) | Technical writing, schema design | LAUNCHABLE |
| 3 | Update implementation.md | AC #28 | 1 modify (`implementation.md`) | Technical writing, architecture diagrams | LAUNCHABLE |
| 4 | Update Job 17 (Recommendation Engine) | AC #16-23 | 1 modify (`.supervisor/jobs/pending/2026-04-11-m3-17-recommendation-engine.md`) | Supervisor brief format | BLOCKED (by #1, #2 — needs final section numbers and schema from specs) |
| 5 | Update Job 2 (Database) | AC #24-25 | 1 modify (`.supervisor/jobs/pending/2026-04-10-m1-2-database.md`) | Supervisor brief format | BLOCKED (by #2 — needs final table schema from TechSpec) |
| 6 | Update Jobs 14, 19, 21 | AC #26-27, #28 (remaining jobs) | 3 modify (`.supervisor/jobs/pending/2026-04-11-m2-14-celery-scheduler.md`, `.supervisor/jobs/pending/2026-04-11-m3-19-safety-layer.md`, `.supervisor/jobs/pending/2026-04-11-m4-21-mobile-dashboard.md`) | Supervisor brief format | BLOCKED (by #1 — needs Mode F definition from PRD) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (PRD) ──────────┬──→ Subtask 4 (Job 17) ──→ done
Subtask 2 (TechSpec) ─────┤──→ Subtask 5 (Job 2)  ──→ done
Subtask 3 (implementation) │──→ done (independent)
                           └──→ Subtask 6 (Jobs 14, 19, 21) ──→ done
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | none | NO |
| Subtask 1 | Subtask 3 | none | NO |
| Subtask 2 | Subtask 3 | none | NO |
| Subtask 4 | Subtask 5 | none | NO |
| Subtask 4 | Subtask 6 | none | NO |
| Subtask 5 | Subtask 6 | none | NO |

### Batch Plan
- **Batch 1:** Subtask 1 (PRD), Subtask 2 (TechSpec), Subtask 3 (implementation.md) — parallel, no file overlap
- **Batch 2:** Subtask 4 (Job 17), Subtask 5 (Job 2), Subtask 6 (Jobs 14/19/21) — parallel, no file overlap, depends on specs from Batch 1
- **Recommended workers:** 3
- **Estimated batches:** 2

## Detailed Update Specifications

### Subtask 1: PRD Updates

**Section 1.1 — Key Differentiators:**
Change the "Deterministic-first AI" bullet from:
> "Deterministic-first AI: All analysis is reproducible math/rules. LLM explanations are optional."

To:
> "Deterministic-first AI: All MVP analysis is reproducible math/rules. Phase 2+ adds optional AI-enhanced scoring (capped at 30%, audited, user opt-in) after legal review."

**Section 2.3 — NOT in MVP table:**
Add row:
| AI-Enhanced Analysis (live mode) | Phase 2+ | Legal review + 3 months shadow data |

**Section 11 header:**
Change from:
> "All analysis is deterministic. Given same inputs, same outputs. LLMs never in the decision loop."

To:
> "All MVP analysis is deterministic. Given same inputs, same outputs. Phase 2+ adds optional AI-enhanced scoring (capped at 30%, fully audited, user opt-in) after legal review and 3 months of shadow-mode validation."

**Section 11.5 — Recommendation Synthesis table:**
Add AI Analysis row to Phase 2+ column. Update existing Phase 2+ weights to show redistribution:

| Signal | MVP | Phase 2+ (no AI) | Phase 2+ (AI at 20%) |
|--------|-----|-------------------|----------------------|
| Technical | 40% | 30% | 32% (40% x 0.80) |
| Fundamental | 25% | 20% | 20% (25% x 0.80) |
| Sentiment | 20% | 15% | 16% (20% x 0.80) |
| Risk | 15% | 15% | 12% (15% x 0.80) |
| Predictive | N/A | 20% | N/A (mutually exclusive with AI) |
| AI Analysis | N/A | N/A | 20% (max 30%) |

**Section 12 header:**
Change from:
> "LLMs never influence decisions. They only generate explanations of decisions already made deterministically."

To:
> "In MVP, LLMs only generate explanations of decisions already made deterministically. Phase 2+ optionally blends AI-enhanced analysis scores (capped at 30%, fully audited, user opt-in) into recommendations after legal review."

**Section 13 — Add Mode F after Mode E:**

> ### 13.6 Mode F: AI-Enhanced Analysis [Phase 1: Shadow, Phase 2+: Live]
>
> **Shadow mode (Phase 1/MVP):** AI analysis runs asynchronously during recommendation generation. Claude analyzes earnings calls, 10-K filings, and management guidance to produce an AIAnalysisScore (outlook 0-1, risks 0-1, reasoning, model version). Score is logged to ai_analysis_log table alongside traditional_score and hypothetical blended_score, but is NOT blended into the recommendation. Recommendation uses ONLY deterministic scoring.
>
> **Live mode (Phase 2+):** Same as shadow, but AI score IS blended: `(1 - AI_weight) x traditional + AI_weight x AI_score`. Hard-blocked if `DEPLOYMENT_ENV=production` AND no legal review flag. Weight cap: 0.30 max enforced in code constant (`MAX_AI_WEIGHT`), not just env var. Requires 3 months of shadow data + legal review.
>
> Two providers: ClaudeCliAnalyzer (local/dev only, subprocess, $0) and ApiAnalyzer (Anthropic SDK, BYOK, user pays).

**Section 22 — Roadmap:**
In Month 3 section, add:
> - AI Analysis shadow mode (async, log-only, not blended into recommendations)

In Phase 2 section, add:
> - AI-Enhanced Analysis live mode (after legal review + 3 months shadow data)

**Section 23 — Regulatory:**
Add bullet:
> - **AI Score Blending:** Legal review required before enabling live mode (AI scores blended into recommendations). Shadow mode (log-only) does not require legal review.

**Section 25 — Risks table:**
Add 3 rows:
| Prompt injection in financial documents | High | Input sanitization (regex blocklist, max token limit, content classification pre-check) | Disable AI analysis; fall back to deterministic-only |
| AI model drift (score quality degrades over time) | Medium | Model version tracking per score, shadow mode comparison against traditional | Revert to shadow mode; retrain/update prompts |
| Weight misconfiguration (AI weight too high) | High | Hard cap 0.30 in code constant (MAX_AI_WEIGHT), audit log on weight changes | Automatic revert to 0.0 if anomaly detected |

**Section 26 — Open Questions table:**
Add row:
| 8 | Legal review for AI score blending — when to engage fintech attorney? | Regulatory | Before Phase 2 live mode |

---

### Subtask 2: TechSpec Updates

**New Section (after section 4, Explainer Provider Abstraction):**

> ## 4b. AI Analysis Provider Abstraction
>
> Interface: AIAnalysisProvider.analyze(instrument, documents) -> AIAnalysisScore. Provider name stored in audit.
>
> ### AIAnalysisScore Schema (Pydantic)
> ```
> outlook: float       # 0.0-1.0, clamped
> risks: float         # 0.0-1.0, clamped
> reasoning: str
> model_version: str
> latency_ms: int
> status: str          # success | error | refused | timeout
> ```
>
> ### 4b.1 ClaudeCliAnalyzer (Local Only)
> subprocess: `claude -p <prompt> --output-format json`. Guarded by AI_ANALYSIS_ENABLED=true AND DEPLOYMENT_ENV=local. Security: timeout configurable (default 10s), max document tokens (default 4000), PII/token redaction, input sanitization (regex blocklist for known injection patterns). Audit: logs prompt_hash (SHA-256), model_version, latency_ms, input/output token counts.
>
> ### 4b.2 ApiAnalyzer (BYOK)
> Anthropic SDK. User provides ANTHROPIC_API_KEY. Works in any DEPLOYMENT_ENV. Rate limited (default 10 calls/hour). Same security and audit as CLI.
>
> ### 4b.3 Shadow Mode (Phase 1)
> AI analysis triggers ONLY on `POST /api/recommendations/generate`, NOT on GET. Runs as async Celery task (does not block recommendation response). Result logged to `ai_analysis_log` table with traditional_score and hypothetical blended_score. Recommendation uses ONLY traditional deterministic score.
>
> ### 4b.4 Live Mode (Phase 2+)
> Score IS blended: `(1 - AI_weight) x traditional + AI_weight x AI_score`. Hard-blocked if `DEPLOYMENT_ENV=production` AND no legal review flag set. Weight cap: 0.30 enforced as code constant `MAX_AI_WEIGHT` (not just env var). Requires 3 months shadow data.
>
> ### 4b.5 Input Sanitization
> - Strip known injection patterns via regex blocklist (e.g., "ignore previous instructions", "system prompt")
> - Max token limit per document: AI_ANALYSIS_MAX_DOCUMENT_TOKENS (default 4000)
> - Content classification pre-check (reject non-financial content)
>
> ### 4b.6 Output Validation
> - Pydantic schema enforcement (AIAnalysisScore)
> - Range clamping: outlook and risks clamped to 0.0-1.0
> - Refusal detection: check for refusal patterns in reasoning field
> - Type checking: all fields validated before use
>
> ### 4b.7 Fallback
> Any AI failure (timeout, error, refused, malformed output) -> AI excluded from scoring. Weight redistributed to deterministic components. Warning logged. In shadow mode: status field records failure type.
>
> ### 4b.8 Safety Mitigations Summary
> 1. Output validation (Pydantic, range clamp, refusal detection)
> 2. Input sanitization (regex blocklist, token limit, classification)
> 3. Weight enforcement (MAX_AI_WEIGHT=0.30 code constant, audit on changes)
> 4. Fallback (any failure -> deterministic only, weight redistributed)
> 5. Model version tracking (recorded per score in ai_analysis_log)
> 6. Log write failure (warning logged, AI result discarded, not retried)

**Section 3 — Schema (add after section 3.13 audit_log):**

> ### 3.14 ai_analysis_log
>
> | Column | Type | Null | Notes |
> |--------|------|------|-------|
> | id | BIGSERIAL | NO | PK |
> | user_id | UUID | NO | FK to users |
> | instrument_id | UUID | NO | FK to instruments |
> | provider | ENUM(claude_cli, api) | NO | Which AI provider used |
> | ai_score | JSONB | YES | AIAnalysisScore JSON (null on error) |
> | traditional_score | DECIMAL | NO | The deterministic composite score |
> | blended_score | DECIMAL | YES | Hypothetical: what blended score would have been |
> | model_version | VARCHAR | YES | e.g., "claude-sonnet-4-20250514" |
> | prompt_hash | VARCHAR | NO | SHA-256 of the prompt sent |
> | status | ENUM(success, error, refused, timeout) | NO | Outcome |
> | input_tokens | INT | YES | Tokens in prompt |
> | output_tokens | INT | YES | Tokens in response |
> | latency_ms | INT | YES | End-to-end AI call time |
> | shadow_mode | BOOLEAN | NO | true = log-only, false = blended (Phase 2+) |
> | created_at | TIMESTAMPTZ | NO | DEFAULT NOW() |
>
> Index on (user_id, created_at DESC). Index on (instrument_id, created_at DESC). Index on (status).

**Section 8.4 — Env Vars (append):**

> ```
> # AI Analysis (MODE 4)
> AI_ANALYSIS_ENABLED=false
> AI_ANALYSIS_PROVIDER=claude_cli       # claude_cli | api
> AI_ANALYSIS_SHADOW_MODE=true          # true=log only, false=blend (Phase 2+)
> AI_ANALYSIS_WEIGHT=0.20               # default weight when blending
> AI_ANALYSIS_WEIGHT_CAP=0.30           # hard cap (also enforced as code constant)
> AI_ANALYSIS_TIMEOUT=10                # seconds
> AI_ANALYSIS_MAX_DOCUMENT_TOKENS=4000  # max tokens per document in prompt
> AI_ANALYSIS_RATE_LIMIT=10             # max AI analysis calls per hour (API provider)
> ANTHROPIC_API_KEY=                    # for API provider (BYOK)
> ```

---

### Subtask 3: implementation.md Updates

Add new section after "Operating Modes (MVP)" table:

> ## MODE 4: AI-Enhanced Analysis (Shadow + Live)
>
> ```
> Phase 1 (MVP): SHADOW MODE — AI scores computed + logged, NOT blended
> Phase 2+ (after legal review): LIVE MODE — AI scores blended at configurable weight
> ```
>
> ### Design
>
> ```
>                     POST /api/recommendations/generate
>                                   |
>                     ┌─────────────┴─────────────┐
>                     v                           v
>              Traditional Scoring          AI Analysis (async)
>              (deterministic, sync)        (Celery task, if enabled)
>              tech 40% + fund 25%               |
>              + sent 20% + risk 15%             v
>                     |                   AIAnalysisProvider
>                     |                   .analyze(instrument, docs)
>                     |                        |
>                     |              ┌─────────┴─────────┐
>                     |              v                   v
>                     |      ClaudeCliAnalyzer     ApiAnalyzer
>                     |      (local, subprocess)   (Anthropic SDK)
>                     |              |                   |
>                     |              └─────────┬─────────┘
>                     |                        v
>                     |                  AIAnalysisScore
>                     |                  {outlook, risks,
>                     |                   reasoning, model_version,
>                     |                   latency_ms, status}
>                     |                        |
>                     v                        v
>              ┌──────────────┐     ┌──────────────────────┐
>              │ Recommendation│     │  ai_analysis_log     │
>              │ (traditional │     │  (shadow: log only)  │
>              │  score ONLY)  │     │  (live: also blend)  │
>              └──────────────┘     └──────────────────────┘
> ```
>
> ### Flag System
>
> | Flag | Default | Effect |
> |------|---------|--------|
> | AI_ANALYSIS_ENABLED | false | Master switch. If false, no AI analysis runs. |
> | AI_ANALYSIS_SHADOW_MODE | true | true = log only. false = blend into score (Phase 2+). |
> | AI_ANALYSIS_PROVIDER | claude_cli | claude_cli (local, $0) or api (BYOK, user pays). |
> | AI_ANALYSIS_WEIGHT | 0.20 | Weight given to AI score when blending. |
> | AI_ANALYSIS_WEIGHT_CAP | 0.30 | Hard cap. Also enforced as MAX_AI_WEIGHT code constant. |
>
> ### Weight Redistribution (Live Mode)
>
> ```
> Without AI (default):          With AI (AI_ANALYSIS_WEIGHT=0.20):
>   Technical:    40%              Technical:    32%  (40% x 0.80)
>   Fundamental:  25%              Fundamental:  20%  (25% x 0.80)
>   Sentiment:    20%              Sentiment:    16%  (20% x 0.80)
>   Risk:         15%              Risk:         12%  (15% x 0.80)
>   AI:            0%              AI Analysis:  20%
> ```
>
> ### Safety Mitigations (from red team review)
>
> 1. **Output validation:** Pydantic schema, range clamp 0.0-1.0, refusal detection
> 2. **Input sanitization:** Regex blocklist, max token limit, content classification
> 3. **Weight enforcement:** MAX_AI_WEIGHT=0.30 code constant, audit log on changes
> 4. **Fallback:** Any AI failure -> deterministic only, weight redistributed
> 5. **Model version tracking:** Recorded per score in ai_analysis_log
> 6. **Log write failure:** Warning logged, AI result discarded, not retried

Also update the Operating Modes table to add:
| **F** | AI-Enhanced Analysis | Shadow: AI scores logged but not blended. Live (Phase 2+): blended at max 30% weight. | Shadow: Yes, Live: Phase 2+ |

Also update the "Key Design Principles" item #2 to match the updated determinism statement:
> 2. **Deterministic-first AI** -- All MVP analysis is reproducible math/rules. Phase 2+ adds optional AI-enhanced scoring (capped at 30%, audited, user opt-in) after legal review.

---

### Subtask 4: Job 17 (Recommendation Engine) Updates

**Add to Task/Goal section:**
> Also implement AIAnalysisProvider abstraction with shadow mode integration. When AI_ANALYSIS_ENABLED=true, POST /api/recommendations/generate triggers an async Celery task that runs AI analysis, validates output, sanitizes input, and logs results to ai_analysis_log. In shadow mode (Phase 1), the AI score is logged but NOT blended. In live mode (Phase 2+), the AI score is blended with weight redistribution.

**Add 7 new acceptance criteria:**
- [ ] Given AI_ANALYSIS_ENABLED=true and AI_ANALYSIS_SHADOW_MODE=true, when POST /api/recommendations/generate, then AI analysis runs as async Celery task, result logged to ai_analysis_log with shadow_mode=true, recommendation uses ONLY traditional score
- [ ] Given DEPLOYMENT_ENV=production and AI_ANALYSIS_SHADOW_MODE=false, when no legal review flag set, then live mode hard-blocked (AI_ANALYSIS_SHADOW_MODE forced to true)
- [ ] Given AI analysis returns malformed output (missing fields, wrong types), when parsed, then Pydantic validation catches it, status=error logged to ai_analysis_log
- [ ] Given AI score with outlook=1.5 or risks=-0.2, when validated, then values clamped to 0.0-1.0 range
- [ ] Given AI_ANALYSIS_WEIGHT=0.35 in env var, when weight loaded, then capped to MAX_AI_WEIGHT=0.30 (code constant enforcement)
- [ ] Given AI analysis failure (timeout, error, refused), when recommendation generated, then AI excluded, weight redistributed to deterministic components proportionally
- [ ] Given ai_analysis_log write fails (DB error), when AI result available, then warning logged, AI result discarded (not retried), recommendation proceeds with traditional score only

**Add 4 new subtasks (inserted after existing Subtask 2, renumbering subsequent):**

| 3 | AIAnalysisProvider abstraction + ClaudeCliAnalyzer + ApiAnalyzer | New ACs #1, #3, #4 | 0 modify, 4 create (backend/app/intelligence/ai_analysis/__init__.py, backend/app/intelligence/ai_analysis/base.py, backend/app/intelligence/ai_analysis/claude_cli.py, backend/app/intelligence/ai_analysis/api.py) | Python ABC, subprocess, Anthropic SDK | LAUNCHABLE (parallel with Subtask 1, 2) |
| 4 | Shadow mode integration + ai_analysis_log writing | New ACs #1, #2, #7 | 1 modify (backend/app/tasks/ — add ai_analysis task), 1 create (backend/app/intelligence/ai_analysis/shadow.py) | Celery async tasks, SQLAlchemy | BLOCKED (by #3) |
| 5 | Output validation + range clamping | New ACs #3, #4 | 1 modify (backend/app/intelligence/ai_analysis/base.py — add validation), 1 create (backend/app/schemas/ai_analysis.py) | Pydantic v2, clamping | BLOCKED (by #3) |
| 6 | Input sanitization | New AC implicit | 0 modify, 1 create (backend/app/intelligence/ai_analysis/sanitizer.py) | Regex, token counting | LAUNCHABLE (parallel with Subtask 3) |

**Update dependency graph and batch plan** to accommodate new subtasks. Original Subtask 3 (wire) becomes Subtask 7, Subtask 4 (API) becomes Subtask 8, Subtask 5 (tests) becomes Subtask 9. Add AI analysis tests to Subtask 9.

---

### Subtask 5: Job 2 (Database) Updates

**Update acceptance criteria #1:**
Change "all 14 tables created" to "all 15 tables created" and add `ai_analysis_log` to the list.

**Add to seed script note (if applicable):**
No seed data needed for ai_analysis_log (populated at runtime).

**Add ai_analysis_log to subtask 2 (SQLAlchemy models):**
Add `backend/app/models/ai_analysis_log.py` to the list of files to create.

---

### Subtask 6: Jobs 14, 19, 21 Updates

**Job 14 (Celery Scheduler):**
Add note to Task section:
> Note: When AI_ANALYSIS_ENABLED=true, the POST /api/recommendations/generate endpoint (triggered by the recommendation generation task) will dispatch an async AI analysis Celery task. This task runs independently of the scheduler — it is triggered on-demand by the recommendation endpoint, not by a scheduled job. No scheduler changes required, but the Celery worker must be configured to handle the `ai_analysis` task queue.

**Job 19 (Safety Layer):**
Add note to Task section:
> Note: Safety validation (loss limits, position sizing, drawdown) applies to the traditional_score only. The blended_score stored in ai_analysis_log is informational in shadow mode — it represents what the score would have been if AI were blended. Safety does not validate blended_score. In Phase 2+ live mode, safety will validate the final blended recommendation score.

**Job 21 (Mobile Dashboard):**
Add note to Task section:
> Note: A dev-only AI comparison view (showing traditional_score vs ai_score side-by-side from ai_analysis_log) is deferred to Phase 2 or can be added as a debug screen behind a developer flag. No UI changes in MVP beyond what is already specified.

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 (PRD) | Technical writing, PRD section numbering, risk/regulatory documentation |
| 2 (TechSpec) | Schema design, env var documentation, provider abstraction patterns |
| 3 (implementation.md) | ASCII architecture diagrams, concise technical summaries |
| 4 (Job 17) | Supervisor brief format, subtask decomposition, dependency analysis |
| 5 (Job 2) | Supervisor brief format, schema updates |
| 6 (Jobs 14/19/21) | Supervisor brief format, cross-job impact notes |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Section numbering drift if PRD/TechSpec have been updated since read | MEDIUM | Read file at edit time; use content matching, not just line numbers |
| Job brief format inconsistency after updates | LOW | Follow exact format of existing briefs; validate structure after edit |
| Acceptance criteria count becomes unwieldy in Job 17 | LOW | Group related criteria; keep original ACs intact, append new ones in separate section |
| Phase 2+ weight redistribution conflicts with existing "Predictive" signal in 11.5 | MEDIUM | Note that Predictive and AI Analysis are mutually exclusive Phase 2+ options; user configures one or the other |

## Configuration
- **Workers:** 3
- **Mode:** parallel
- **Estimated batches:** 2
- **Branch:** `feat/mode4-spec-update`
- **Batch:** 0 (parallel with Job 1 repo scaffold — documentation must be updated before any coding begins)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-mode4-prd-jobs-update.md
```
