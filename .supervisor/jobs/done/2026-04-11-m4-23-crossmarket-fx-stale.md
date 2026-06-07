# Supervisor Job: Cross-Market Benchmarks, FX Impact Attribution & Stale Data UX

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected clean
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Months 1-3 complete (FX pipeline, benchmark data via Yahoo Finance, risk models, recommendation engine, data freshness tracking)

## Task
**Goal:** Implement cross-market benchmark logic (Indian holdings vs Nifty 50, US holdings vs S&P 500, portfolio-level blended benchmark weighted by allocation %), FX impact attribution as simple text notes on cross-currency holdings, and stale data UX with freshness badges on recommendations and confidence reduction display.

**Problem Statement:**
Beta users with dual-market portfolios (India + US) have no way to compare their performance against relevant benchmarks, understand FX impact on their returns, or know when analysis data is outdated. Without cross-market benchmarks, portfolio intelligence is incomplete. Without FX attribution, INR-base users holding US stocks see misleading return numbers. Without stale data handling, users may act on outdated recommendations. These three features are essential for a trustworthy beta launch.

## Acceptance Criteria
- [ ] Given Indian holdings (e.g., RELIANCE on XNSE), when benchmark shown, then compares against Nifty 50 (^NSEI) in INR
- [ ] Given US holdings (e.g., AAPL on XNAS), when benchmark shown, then compares against S&P 500 (^GSPC) in USD
- [ ] Given portfolio with both IN + US holdings, when portfolio-level benchmark shown, then blended by allocation % (e.g., 60% IN * Nifty return + 40% US * S&P return, both converted to base currency)
- [ ] Given AAPL held by INR-base user, when P&L shown, then displays decomposition: stock return (USD) + FX impact + INR return (e.g., "AAPL +8% USD, INR weakened 3%, your INR return: +11.2%")
- [ ] Given recommendation created 45 minutes ago, when displayed, then shows "fresh" badge with normal confidence
- [ ] Given recommendation 3 hours old, when displayed, then shows "aging" badge + confidence reduced by 5%
- [ ] Given recommendation 12 hours old, when displayed, then shows yellow "stale" badge + confidence reduced by 15%
- [ ] Given recommendation 25 hours old, then suppressed (not shown in feed) with "Data too old" message if user navigates to it directly

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | Extend benchmark service (cross-market display + FX base-currency conversion) | AC #1, #2, #3 | 2 modify (backend/app/services/benchmark.py — extend Job 18's service with cross-market display helpers and FX base-currency conversion; backend/tests/test_benchmark.py — add cross-market tests), 0 create | pandas, Yahoo Finance data for ^NSEI/^GSPC | LAUNCHABLE |
| 2 | Backend stale data service (freshness calculation + confidence reduction) | AC #5, #6, #7, #8 | 1 modify (backend/app/intelligence/synthesizer.py — add staleness logic), 2 create (backend/app/intelligence/staleness.py, backend/tests/test_staleness.py) | datetime arithmetic, recommendation schema | LAUNCHABLE |
| 3 | Backend FX impact attribution (return decomposition) | AC #4 | 1 modify (backend/app/api/portfolio.py — add FX notes to position response), 1 create (backend/app/intelligence/fx_attribution.py) | FX rate math, position return decomposition | LAUNCHABLE |
| 4 | Mobile benchmark display components | AC #1, #2, #3 | 0 modify, 3 create (mobile/src/components/BenchmarkComparison.tsx, mobile/src/components/BlendedBenchmark.tsx, mobile/src/hooks/useBenchmark.ts) | React Native charts/comparisons | BLOCKED (by #1 — needs API) |
| 5 | Mobile stale data badges + suppression | AC #5, #6, #7, #8 | 1 modify (mobile/src/components/InsightCard.tsx — add badge), 2 create (mobile/src/components/FreshnessBadge.tsx, mobile/src/components/StaleDataMessage.tsx) | React Native badge patterns | BLOCKED (by #2 — needs API) |
| 6 | Mobile FX impact attribution notes | AC #4 | 1 modify (mobile/src/components/HoldingRow.tsx — add FX note), 1 create (mobile/src/components/FxImpactNote.tsx) | React Native text formatting | BLOCKED (by #3 — needs API) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (Backend benchmark) ──→ Subtask 4 (Mobile benchmark)
Subtask 2 (Backend staleness) ──→ Subtask 5 (Mobile stale badges)
Subtask 3 (Backend FX attr.)  ──→ Subtask 6 (Mobile FX notes)
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | none | NO |
| Subtask 1 | Subtask 3 | none | NO |
| Subtask 2 | Subtask 3 | none | NO |
| Subtask 4 | Subtask 5 | none | NO |
| Subtask 4 | Subtask 6 | none | NO |
| Subtask 5 | Subtask 6 | none (InsightCard.tsx vs HoldingRow.tsx — different files) | NO |

### Batch Plan
- **Batch 1:** Subtask 1, 2, 3 (parallel — all backend, no file overlap)
- **Batch 2:** Subtask 4, 5, 6 (parallel — all mobile, no file overlap)
- **Recommended workers:** 3
- **Estimated batches:** 2

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | Yahoo Finance ^NSEI/^GSPC data, weighted benchmark calculation, pandas |
| 2 | datetime/timezone handling, recommendation staleness thresholds |
| 3 | FX rate math, return decomposition (stock + FX + cross-term) |
| 4 | React Native comparison display, TanStack Query |
| 5 | React Native badge/pill components, conditional rendering |
| 6 | React Native text formatting, inline notes |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Yahoo Finance ^NSEI data availability/reliability | HIGH | Cache aggressively (24h for daily benchmark); DataProvider abstraction allows swap; fallback to last known value |
| Blended benchmark FX conversion introduces compounding complexity | MEDIUM | Phase 1: simple daily FX conversion; document that intraday FX moves are not captured |
| Stale data thresholds may be too aggressive (suppressing useful recommendations) | MEDIUM | Make thresholds configurable; log suppression events for tuning; allow user to "show anyway" in Phase 2 |
| FX impact attribution formula edge cases (e.g., position opened across multiple FX rates) | LOW | Phase 1: use position open-date FX rate vs current; Phase 2: weighted average across fills |
| InsightCard.tsx and HoldingRow.tsx may have been created in Job 21 with different structure | MEDIUM | Read existing component structure before modifying; ensure additive changes only |

## Configuration
- **Workers:** 3
- **Mode:** parallel
- **Estimated batches:** 2
- **Branch:** `feat/m4-23-crossmarket-fx-stale`
- **Batch:** 9 (parallel with Jobs 21, 22; blocked by Month 3)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-m4-23-crossmarket-fx-stale.md
```

## Outcome
- heal_loop_ran: true
- heal_decision: PASS
- heal_iterations: 1
- heal_remaining_issues: 0
- pr: https://github.com/vikashruhilgit/nivara/pull/23
- feature_branch: feat/m4-23-crossmarket-fx-stale
- subtasks_completed: 6/6 (S1-S6)
- tests: 59/59 backend pass; mobile tsc clean
