# InvestIQ

AI-driven investment platform — mobile-first MVP.

- **Backend:** FastAPI (Python 3.12), Postgres 16, Redis 7, Celery
- **Mobile:** Expo SDK 52 + React Native (New Architecture)
- **Auth:** Bearer token (refresh in JSON body; expo-secure-store on device)
- **Brokers:** Alpaca (US), Zerodha (IN)
- **Notifications:** Expo Push

## Prerequisites

- **Docker** (Docker Desktop or compatible) — for the backend stack
- **Node.js 18+** and npm — for the mobile app
- **Python 3.12** (optional) — only if running the backend locally without Docker
- A simulator/emulator or the **Expo Go** app on a physical device — to run the mobile app

## Quick Start

```bash
# Backend (Postgres + Redis + API)
cp .env.example .env          # first time only
docker compose up -d
curl http://localhost:8000/health   # => {"status":"ok","environment":"development"}

# Mobile (in a second terminal)
cd mobile
npm install
npx expo start                # press i (iOS), a (Android), w (web), or scan the QR with Expo Go
```

Default local ports: **API `:8000`**, **Postgres `:5433`**, **Redis `:6380`**.

## Backend (Docker)

`docker compose` builds and runs three services (`api`, `postgres`, `redis`) wired together
on an internal network. Configuration comes from the root `.env` plus the overrides in
`docker-compose.yml` (dev RS256 JWT keys are mounted from `./keys`).

```bash
docker compose up -d                 # start everything (no-op if already running)
docker compose ps                    # status + health of each service
docker compose logs -f api           # tail API logs (Ctrl-C to stop tailing)
curl http://localhost:8000/health    # health check

# Refresh after a backend CODE change (rebuild image, recreate container)
docker compose up -d --build api

# Restart without a code change (e.g. after editing .env)
docker compose restart api

# Stop / tear down
docker compose down                  # stop and remove containers (keeps data)
docker compose down -v               # also drop Postgres/Redis volumes (fresh DB)
```

| Service  | Host port | In-network URL                                              |
|----------|-----------|------------------------------------------------------------|
| api      | `8000`    | `http://localhost:8000`                                    |
| postgres | `5433`    | `postgresql+asyncpg://investiq:investiq@postgres:5432/...` |
| redis    | `6380`    | `redis://redis:6379/0`                                     |

## Backend (local, without Docker)

Useful for fast iteration / debugging. You still need Postgres and Redis reachable (e.g. keep
`docker compose up -d postgres redis`) and a populated `.env` (DB/Redis URLs, JWT key paths).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn backend.app.main:app --reload      # serves on http://localhost:8000
```

## Mobile (Expo)

```bash
cd mobile
npm install                  # first run, or after pulling new native deps
npx expo start               # start Metro; press i / a / w, or scan the QR with Expo Go

# Boot straight into a target
npx expo start --ios
npx expo start --android
npx expo start --web
```

**Refreshing the app**

- Press **`r`** in the Metro terminal to reload (or shake the device → Reload).
- After changing/adding native deps, or if things look stale, clear the cache:
  **`npx expo start -c`**.

**Pointing the app at the backend** — `src/api/client.ts` resolves the API base URL in this order:

1. `app.json` → `extra.apiBaseUrl`
2. `EXPO_PUBLIC_API_BASE_URL` environment variable
3. fallback: `http://localhost:8000`

| Run target            | Base URL to use                                  |
|-----------------------|--------------------------------------------------|
| iOS simulator / web   | `http://localhost:8000` (default — works as-is)  |
| Android emulator      | `EXPO_PUBLIC_API_BASE_URL=http://10.0.2.2:8000`  |
| Physical device (Expo Go) | `EXPO_PUBLIC_API_BASE_URL=http://<your-LAN-IP>:8000` |

```bash
# Example: Android emulator
EXPO_PUBLIC_API_BASE_URL=http://10.0.2.2:8000 npx expo start
```

**Expo Go vs. dev build** — `expo-blur`, `react-native-svg`, and `@react-native-async-storage/async-storage`
are bundled in Expo Go for SDK 52, so the themed UI (glass/texture) renders in Expo Go. If you hit a
native edge case, build a dev client instead:

```bash
npx expo prebuild
npx expo run:ios      # or: npx expo run:android
```

## Tests & Quality Gates

**Backend** (from the repo root):

```bash
pytest                                      # run backend tests
ruff check backend && ruff format backend   # lint + format
mypy backend/app                            # type check
```

**Mobile** (from `mobile/`):

```bash
npm run type-check    # tsc --noEmit
npm run lint          # eslint
npm test              # jest (theme + UI primitive tests)
```

Pre-commit hooks (ruff, ruff-format, mypy, hygiene) run on commit — install once with
`pre-commit install`.

## Repository Layout

```
.
├── backend/          # FastAPI service
│   ├── app/          # Application package
│   │   ├── main.py   # FastAPI entrypoint (/health)
│   │   ├── config.py # Pydantic settings
│   │   └── api/      # Route modules
│   └── Dockerfile
├── mobile/           # Expo app (React Native)
│   ├── app/          # expo-router screens
│   ├── src/          # theme system, UI primitives, components, stores, hooks, api
│   ├── app.json
│   └── package.json
├── plan/             # PRD, TechSpec, implementation docs
├── docker-compose.yml
├── pyproject.toml
├── ruff.toml
├── .pre-commit-config.yaml
└── CLAUDE.md         # Agent context / project conventions
```

## Documentation

- PRD, TechSpec, and implementation overview live in `plan/`
- Supervisor jobs live in `.supervisor/jobs/`
- Agent context: see [CLAUDE.md](./CLAUDE.md)

## License

Proprietary.
