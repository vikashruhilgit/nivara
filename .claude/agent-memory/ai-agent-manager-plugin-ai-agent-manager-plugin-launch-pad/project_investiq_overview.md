---
name: InvestIQ Project Overview
description: Greenfield AI-powered investment platform — mobile-first MVP with FastAPI backend and React Native/Expo frontend, connecting to Alpaca and Zerodha brokers
type: project
---

InvestIQ is an AI-powered investment intelligence middleware platform connecting to Zerodha (India) and Alpaca (US) brokers. Greenfield project at /Users/vikashruhil/Documents/work/AI/Nivara/.

**Why:** Solo developer building institutional-grade investment intelligence accessible to retail traders. MVP is strictly read-only (no order placement).

**How to apply:** All implementation jobs should follow mobile-first patterns (bearer auth, not cookies), use the specified tech stack, and respect the read-only MVP constraint.

Key decisions (as of 2026-04-09):
- Backend: Python 3.12, uv, FastAPI, SQLAlchemy 2.x async (asyncpg), Pydantic v2, Alembic, Celery+Redis, argon2 password hashing, structlog
- Mobile: React Native + Expo (managed workflow), Expo Router, TanStack Query + Zustand, expo-secure-store
- Auth: JWT RS256 15min access + opaque 7d refresh via BEARER (not cookies — mobile pattern). No CSRF needed.
- Encryption: AES-256-GCM per-user HKDF, dual-key rotation
- Broker OAuth: expo-auth-session deep link (investiq:// scheme)
- Database: PostgreSQL 16 + Redis 7
- Deployment: Docker Compose ($0 local)
- PRD/TechSpec v1.2 exist; must be updated to v1.3 before coding (reflects mobile-first, 25 identified gaps)

Spec files:
- /Users/vikashruhil/Documents/work/AI/Nivara/InvestIQ_PRD_v1.2.md
- /Users/vikashruhil/Documents/work/AI/Nivara/InvestIQ_TechSpec_v1.2.md
