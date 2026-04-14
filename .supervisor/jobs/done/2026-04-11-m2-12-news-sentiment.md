# Supervisor Job: News + Sentiment Pipeline (GNews + Reddit + FinBERT)

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected clean, branch: `feat/m2-12-news-sentiment`
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Month 1 complete (database with instruments table; Redis for caching). GNEWS_API_KEY env var configured.

## Task
**Goal:** Build the complete sentiment analysis pipeline: GNews news fetching (batch by sector, 100 req/day free tier, RSS fallback), Reddit sentiment via PRAW (degradable, 20% weight), FinBERT local inference (ProsusAI/finbert, CPU) for sentiment scoring, and composite sentiment calculation. Combined sentiment weights: news 50%, social 20%, macro 30%. Decay: 24h half-life for news, 1h for social. API endpoint: GET /api/analysis/{symbol}/sentiment returning composite score (-1 to +1) with breakdown.

**Problem Statement:**
Sentiment analysis is 20% of the MVP recommendation composite score. Without it, recommendations lack market mood context. FinBERT provides NLP-based sentiment scoring without any API cost. GNews provides financial news on a free tier (100 req/day). Reddit provides social sentiment as a degradable signal. The decay model ensures stale sentiment does not pollute current scores. All three sources must gracefully degrade if unavailable.

## Acceptance Criteria
- [ ] Given AAPL, when sentiment analysis runs, then returns composite score (-1 to +1) with news/social/macro breakdown
- [ ] Given GNews rate limit hit, when news fetch called, then gracefully degrades to RSS feeds
- [ ] Given Reddit unavailable, when sentiment calculated, then social weight redistributed (news 60%, macro 40%)
- [ ] Given 24h old news article, when scored, then weight decayed by 50% (24h half-life)
- [ ] Given FRED economic data available, when macro sentiment computed, then maps key indicators (unemployment rate change, Fed funds rate direction, GDP growth trend) to a macro score (-1 to +1) contributing 30% of composite
- [ ] Given FRED unavailable, when macro sentiment computed, then defaults to 0 (neutral) and redistributes weight to news 70% + social 30%

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | GNews client + RSS fallback | AC #2 | 1 modify (`pyproject.toml` — add feedparser), 2 create (`backend/app/data/gnews.py`, `backend/app/data/rss.py`) | GNews API, feedparser | LAUNCHABLE |
| 2 | Reddit client (PRAW) | AC #3 | 1 modify (`pyproject.toml` — add praw), 1 create (`backend/app/data/reddit.py`) | PRAW SDK | LAUNCHABLE |
| 3 | FinBERT inference service | AC #1, #4 | 1 modify (`pyproject.toml` — add transformers, torch), 1 create (`backend/app/analysis/finbert.py`) | HuggingFace transformers, ProsusAI/finbert | LAUNCHABLE |
| 4 | Sentiment scoring engine (composite + decay + macro) | AC #1, #3, #4 | 0 modify, 1 create (`backend/app/analysis/sentiment.py`) | Exponential decay math, weight redistribution, FRED macro indicators | BLOCKED (by #1, #2, #3) |
| 5 | API endpoint + tests | All ACs | 1 modify (`main.py` or `backend/app/api/analysis.py` — add sentiment route), 3 create (`backend/tests/test_gnews.py`, `backend/tests/test_sentiment.py`, `backend/tests/test_finbert.py`) | FastAPI routing, pytest | BLOCKED (by #4) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (GNews + RSS) ──┐
Subtask 2 (Reddit/PRAW) ──┼──→ Subtask 4 (sentiment engine) ──→ Subtask 5 (API + tests)
Subtask 3 (FinBERT)     ──┘
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | `pyproject.toml` | YES (but minor — can merge) |
| Subtask 1 | Subtask 3 | `pyproject.toml` | YES (but minor — can merge) |
| Subtask 2 | Subtask 3 | `pyproject.toml` | YES (but minor — can merge) |

Note: pyproject.toml overlap is additive (different dependencies). Workers can serialize the toml edit or one worker handles all dependency additions.

### Batch Plan
- **Batch 1:** Subtask 1, 2, 3 (parallel — GNews + Reddit + FinBERT, serialize pyproject.toml edits)
- **Batch 2:** Subtask 4 (sentiment engine — depends on all three sources)
- **Batch 3:** Subtask 5 (API + tests)
- **Recommended workers:** 2 (3 possible but pyproject.toml overlap complicates)
- **Estimated batches:** 3

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | GNews API (gnews.io), feedparser for RSS fallback, rate limiting (100/day budget) |
| 2 | PRAW (Python Reddit API Wrapper), subreddit search (r/stocks, r/wallstreetbets, r/IndianStreetBets) |
| 3 | HuggingFace transformers pipeline, ProsusAI/finbert model, CPU inference optimization |
| 4 | Exponential decay (weight = 0.5^(age_hours/half_life)), weight redistribution on source failure |
| 5 | FastAPI, Pydantic response schemas, pytest with model mocking |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| FinBERT model is ~400MB download, CPU inference 1-3s per batch | MEDIUM | Download model on first run (lazy load); batch articles for inference; cache scored articles in Redis |
| GNews 100 req/day limit requires careful batching | HIGH | Batch by sector (not per-symbol); supplement with RSS; track daily usage counter in Redis |
| Reddit API access could be further restricted | LOW | Social sentiment is 20% weight; graceful degradation redistributes to news 60% + macro 40% |
| torch dependency is large (~2GB with CPU-only) | MEDIUM | Use torch CPU-only build (`torch --index-url https://download.pytorch.org/whl/cpu`); document in setup |
| Macro sentiment (30% weight) uses FRED indicators | LOW | Subtask 4 computes macro score from FRED data (Job 11's fred.py); maps unemployment/fed-rate/GDP direction to -1..+1; degrades to neutral (0) if FRED unavailable |
| FinBERT may not handle Indian financial terminology well | LOW | FinBERT trained on English financial text; Indian news in English should work; monitor accuracy |

## Configuration
- **Workers:** 2
- **Mode:** parallel
- **Estimated batches:** 3
- **Branch:** `feat/m2-12-news-sentiment`
- **Batch:** 5 (parallel with Jobs 9, 10, 11, 13; blocked by Month 1 completion)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-m2-12-news-sentiment.md
```

## Outcome
- **Status:** completed
- **Completed:** 2026-04-14T00:00:00Z
- **PR:** https://github.com/vikashruhilgit/nivara/pull/12
- **Branch:** feat/m2-12-news-sentiment
- **Files changed:** 13 (5 new modules, 3 new test files, 2 modified modules, config + pyproject.toml)
- **Heal loop ran:** false
- **Heal decision:** null
- **Heal iterations:** null
- **Summary:** All 5 subtasks implemented inline (no Task tool available in subagent context; worktree delegation not possible). GNews client with daily-budget Redis tracker + RSS fallback, Reddit PRAW wrapper with graceful degradation, FinBERT lazy-singleton scorer with Redis caching, composite sentiment engine with decay math and weight redistribution per ACs #3/#6, plus GET /api/analysis/{symbol}/sentiment route. 31 new tests, 189/189 passing, mypy clean, ruff clean.
