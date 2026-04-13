# InvestIQ

AI-driven investment platform — mobile-first MVP.

- **Backend:** FastAPI (Python 3.11), Postgres 16, Redis 7, Celery
- **Mobile:** Expo SDK 52 + React Native (New Architecture)
- **Auth:** Bearer token (refresh in JSON body; expo-secure-store on device)
- **Brokers:** Alpaca (US), Zerodha (IN)
- **Notifications:** Expo Push

## Quick Start

### Backend (Docker)

```bash
cp .env.example .env
docker compose up -d
curl http://localhost:8000/health   # => {"status":"ok","environment":"development"}
```

### Mobile (Expo)

```bash
cd mobile
npm install
npx expo start
```

### Backend (local, without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn backend.app.main:app --reload
```

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
