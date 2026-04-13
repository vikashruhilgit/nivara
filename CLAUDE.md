# CLAUDE.md — InvestIQ Agent Context

> This file is the canonical agent / LLM context for the InvestIQ repo. Keep it in
> sync with the actual code — stale patterns here cause agent mistakes downstream.

## Project Overview

InvestIQ is an AI-driven investment platform. The MVP is **mobile-first** (Expo +
React Native). Users connect a broker account (Alpaca US, Zerodha IN), receive
AI-generated recommendations, and execute trades from their phone.

- PRD, TechSpec, and implementation overview live in `plan/` (currently v1.2;
  v1.3 update deferred to a follow-up job).
- Auth model is **bearer token** (access + refresh). Refresh token returns in the
  JSON body; mobile stores it in `expo-secure-store`. No cookies, no CSRF.
- Idempotency key for broker orders is `(broker_connection_id, instrument_id)` —
  canonical form, post symbol-mapping.

## Tech Stack

### Backend (`backend/`)
- **Language:** Python 3.11
- **Framework:** FastAPI (async)
- **ORM:** SQLAlchemy 2.0 (async) + Alembic migrations
- **DB:** Postgres 16
- **Cache / queues:** Redis 7 (doubles as Celery broker)
- **Task queue:** Celery 5
- **Settings:** pydantic-settings (`backend/app/config.py`)
- **HTTP client:** httpx
- **Auth:** python-jose (JWT) + passlib (bcrypt)
- **Tooling:** uv (resolution), ruff (lint+format), mypy --strict, pytest +
  pytest-asyncio

### Mobile (`mobile/`)
- **Framework:** Expo SDK 52 with **New Architecture enabled**
- **Routing:** expo-router v4 (file-based; `app/` directory)
- **Secure storage:** expo-secure-store (bearer tokens)
- **Push:** expo-notifications (Expo Push Service)
- **Language:** TypeScript (strict)

### Infrastructure
- **Local dev:** `docker compose up -d` brings up postgres (host :5433), redis
  (host :6380), and api (host :8000).
- **Health:** `GET /health` → `{"status":"ok","environment":"..."}`

## Directory Layout

```
Nivara/                          # repo root
├── backend/
│   ├── Dockerfile
│   └── app/
│       ├── __init__.py
│       ├── main.py              # FastAPI entry — /health
│       ├── config.py            # Settings (pydantic-settings)
│       └── api/                 # Route modules (add here)
├── mobile/
│   ├── app/                     # expo-router screens
│   │   ├── _layout.tsx
│   │   └── index.tsx
│   ├── app.json
│   ├── package.json
│   ├── tsconfig.json
│   └── babel.config.js
├── plan/                        # PRD / TechSpec / implementation docs
├── .supervisor/                 # Supervisor state & jobs (gitignored)
├── docker-compose.yml
├── pyproject.toml
├── ruff.toml
├── .pre-commit-config.yaml
├── .env.example
└── CLAUDE.md                    # this file
```

## Conventions

### Python
- **Imports:** absolute from `backend.app...`; stdlib → third-party → local
  (ruff I handles order).
- **Types:** `from __future__ import annotations` NOT needed (Py 3.11); prefer
  PEP 604 unions (`str | None`). `mypy --strict` must pass.
- **Async-first:** all I/O (DB, HTTP, Redis) is async. Do not mix `requests`
  with `httpx.AsyncClient`.
- **Settings access:** always via `get_settings()` (cached) — don't read env
  vars directly.
- **Errors:** raise `HTTPException` for API-facing errors; log with `logger.exception`
  for unexpected ones. Never log secrets or raw tokens.

### TypeScript / Expo
- **Routing:** file-based under `mobile/app/`. Use `Stack`, `Tabs` from
  expo-router.
- **Styles:** `StyleSheet.create(...)` objects colocated with the component.
- **Tokens:** read/write via `expo-secure-store` (`SecureStore.setItemAsync`,
  `getItemAsync`). Never `AsyncStorage` for auth material.
- **Type strictness:** `tsconfig.json` has `strict: true`; fix errors, don't
  suppress.

### Git & Commits
- **Branch naming:** `feat/*`, `fix/*`, `chore/*`, `refactor/*`.
- **Commits:** Conventional Commits (`feat(scope): ...`, `fix(scope): ...`).
- **Task linking:** end body with `Closes <job-id>` when closing a Supervisor job.
- **Pre-commit:** `.pre-commit-config.yaml` runs ruff, ruff-format, mypy, and
  hygiene hooks. Install once: `pre-commit install`.

## Testing

- **Backend:** `pytest` from repo root. Tests live in `backend/tests/` (to be
  added with first feature). Async tests work out of the box (`asyncio_mode = auto`).
- **Coverage target:** ≥80% for new code.
- **Mobile:** Jest + React Native Testing Library (to be configured with first
  screen beyond the scaffold).

## Common Commands

```bash
# Backend
docker compose up -d                        # boot pg + redis + api
docker compose logs -f api                  # tail API logs
curl http://localhost:8000/health           # health check
pytest                                      # run backend tests
ruff check backend && ruff format backend   # lint + format
mypy backend/app                            # type check

# Mobile
cd mobile && npm install
npx expo start                              # Metro bundler
npx expo start --ios                        # iOS simulator
npx expo start --android                    # Android emulator

# Pre-commit
pre-commit install                          # one-time
pre-commit run --all-files                  # manual full run
```

## Agent Guidance

When working in this repo:

1. **Read before writing.** The actual code is the source of truth; this file
   reflects current patterns but may lag.
2. **Prefer surgical edits.** Don't restructure modules unless the job calls
   for it.
3. **Keep settings in `config.py`.** New env vars go in `Settings`, then in
   `.env.example`, then in `docker-compose.yml` if needed at container boot.
4. **Auth = bearer tokens only.** Do not reintroduce cookie/CSRF patterns —
   TechSpec v1.3 is explicit on this.
5. **Idempotency key:** always `(broker_connection_id, instrument_id)`. Never
   use `broker_symbol` as part of the key after symbol mapping.
6. **Mobile storage:** auth material only in `expo-secure-store`.
7. **When in doubt, check `plan/`** for the current PRD / TechSpec.

## Status

- **M1.1 (repo scaffold):** this job — creates backend + mobile scaffold,
  Docker Compose, CLAUDE.md, pre-commit hooks, gitignore/attributes.
- **Deferred from M1.1:** PRD/TechSpec v1.2 → v1.3 rewrite (moved to a
  follow-up doc job to keep M1.1 scope on the scaffold).
- **Next:** M1.2 (database schema, Alembic baseline).
