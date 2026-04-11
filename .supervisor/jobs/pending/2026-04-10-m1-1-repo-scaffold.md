# Supervisor Job: PRD/TechSpec v1.3 + Repo Scaffold + CLAUDE.md + GitHub Remote

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Not yet created (this job creates it)
- **Git:** Not initialized (this job initializes it)
- **GitHub CLI:** Assumed authenticated (verify before execution)
- **Blockers:** 0 | **Warnings:** 1 (no git repo yet — this job creates it)

## Task
**Goal:** Update PRD/TechSpec from v1.2 to v1.3 (mobile-first MVP, bearer auth, Expo Push, all 25 gaps), initialize git repo with GitHub remote, scaffold backend (FastAPI) and mobile (Expo) projects, create Docker Compose, CLAUDE.md, and pre-commit hooks.

**Problem Statement:**
The developer needs a fully initialized project before any feature work can begin because the current state is raw spec documents (v1.2) with 25 identified gaps, no git repo, no code, and no CLAUDE.md. This job is Batch 0 — every other job depends on it.

## Acceptance Criteria
- [ ] Given v1.2 docs, when Job 1 completes, then v1.3 PRD + TechSpec exist reflecting: mobile app (not web), bearer auth (not cookies), Expo Push notifications, all 25 gaps addressed
- [ ] Given PRD v1.2 §2.3 lists "No mobile app" in NOT-in-MVP, when v1.3 written, then mobile app REMOVED from that list; all Next.js + Tailwind references replaced with React Native + Expo; frontend/ renamed to mobile/ in TechSpec §2; Layer 6 updated
- [ ] Given TechSpec v1.2 §1.1 specifies httpOnly cookies + CSRF, when v1.3 written, then §1.1 rewritten to bearer token pattern — refresh token in JSON body, no cookies, no CSRF, expo-secure-store for mobile storage
- [ ] Given PRD §18.1 says idempotency key is (broker_connection_id, broker_symbol), when v1.3 written, then ALL idempotency key references use (broker_connection_id, instrument_id) — the canonical form after symbol mapping
- [ ] Given TechSpec v1.2 §3 has 13 tables, when v1.3 written, then device_tokens table schema added: id (UUID PK), user_id (FK), platform (ENUM: ios|android), push_token (VARCHAR), is_active (BOOLEAN), created_at, updated_at; UNIQUE on (user_id, push_token)
- [ ] Given no git repo, when Job 1 completes, then git init + GitHub remote created via `gh repo create`
- [ ] Given no code, when Job 1 completes, then `docker compose up -d` brings Postgres 16 + Redis 7 + FastAPI (health endpoint) up; `/health` returns 200
- [ ] Given no mobile app, when Job 1 completes, then `cd mobile && npx expo start` boots Metro bundler
- [ ] Given no CLAUDE.md, when Job 1 completes, then CLAUDE.md exists with tech stack, directory structure, conventions, testing patterns, and all agent-relevant context

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | Update PRD v1.2 -> v1.3 | AC #1 (PRD portion) | 1 modify | — | LAUNCHABLE |
| 2 | Update TechSpec v1.2 -> v1.3 | AC #1 (TechSpec portion) | 1 modify | — | LAUNCHABLE |
| 3 | Git init + GitHub remote | AC #2 | 0 modify, 3 create (.gitignore, .gitattributes, README.md) | — | BLOCKED (by #1, #2) |
| 4 | Backend scaffold (FastAPI + Docker) | AC #3 | 0 modify, 8 create (pyproject.toml, backend/app/main.py, backend/app/config.py, Dockerfile, docker-compose.yml, .env.example, backend/app/__init__.py, backend/app/api/__init__.py) | — | LAUNCHABLE |
| 5 | Mobile scaffold (Expo) | AC #4 | 0 modify, 5+ create (mobile/ directory via create-expo-app) | — | LAUNCHABLE |
| 6 | CLAUDE.md + pre-commit hooks | AC #5 | 0 modify, 3 create (CLAUDE.md, .pre-commit-config.yaml, ruff.toml) | — | BLOCKED (by #4, #5) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (PRD v1.3) ──┐
Subtask 2 (TechSpec v1.3) ──┤──→ Subtask 3 (git init + remote)
Subtask 4 (backend scaffold) ──┤──→ Subtask 6 (CLAUDE.md + hooks)
Subtask 5 (mobile scaffold) ──┘──→ Subtask 6
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | none | NO |
| Subtask 4 | Subtask 5 | none | NO |
| Subtask 4 | Subtask 6 | none (CLAUDE.md reads but doesn't modify backend) | NO |

### Batch Plan
- **Batch 1:** Subtask 1, 2, 4, 5 (parallel — no overlap)
- **Batch 2:** Subtask 3, 6 (after Batch 1)
- **Recommended workers:** 3
- **Estimated batches:** 2

## Skill References

| Subtask | Skills |
|---------|--------|
| 1–2 | Product discovery, user story writing |
| 3 | — (git commands) |
| 4 | FastAPI scaffold patterns |
| 5 | Expo/React Native patterns |
| 6 | CLAUDE.md validation patterns |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| v1.3 spec changes may affect downstream jobs | HIGH | Complete spec updates before any code scaffold; all other jobs read v1.3 |
| create-expo-app version mismatch | LOW | Pin Expo SDK version in package.json |
| Docker compose port conflicts on dev machine | LOW | Use non-standard ports (5433 for PG, 6380 for Redis) |
| pyproject.toml dependency resolution with uv | MEDIUM | Use `uv lock` to verify resolution after scaffold |

## Configuration
- **Workers:** 3
- **Mode:** parallel
- **Estimated batches:** 2
- **Branch:** `feat/m1-1-repo-scaffold`
- **Batch:** 0 (prerequisite for all other jobs)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-10-m1-1-repo-scaffold.md
```
