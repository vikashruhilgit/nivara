# Supervisor Job: Mobile App MVP Shell

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected initialized (by Job 1)
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Job 3 (auth) must be complete (auth endpoints for sign-in/sign-up, bearer token flow)

## Task
**Goal:** Build the Expo Router mobile app shell with tab navigation (Portfolio, Insights, Settings), sign-in/sign-up screens integrating with FastAPI auth (bearer tokens), broker connect screen using expo-auth-session with investiq:// deep link scheme for Alpaca OAuth, portfolio screen calling /api/portfolio/summary + /api/portfolio/positions, API client with axios + auto-refresh interceptor, auth store (Zustand) + expo-secure-store for refresh token, and TanStack Query for server state.

**Problem Statement:**
The user has no way to interact with the platform. The mobile app is the primary interface for InvestIQ. Without this shell, auth flow cannot be tested end-to-end, broker connection cannot be initiated, and portfolio data cannot be displayed. This provides the foundation for all future mobile screens.

## Acceptance Criteria
- [ ] Given app launch (no auth), when user opens app, then sees sign-in screen (not tabs)
- [ ] Given valid credentials, when sign in tapped, then navigates to Portfolio tab
- [ ] Given app restart, when valid refresh token exists in expo-secure-store, then auto-refreshes access token and lands on Portfolio tab
- [ ] Given broker not connected, when "Connect Alpaca" tapped on Settings, then expo-auth-session opens Alpaca OAuth flow with investiq:// redirect
- [ ] Given portfolio synced, when Portfolio tab opened, then shows positions list from /api/portfolio/positions
- [ ] Given expired access token, when API call made, then axios interceptor auto-refreshes and retries the original request
- [ ] Given tab bar, then shows Portfolio, Insights, Settings tabs with appropriate icons

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | API client (axios + auto-refresh interceptor) | AC #6 | 0 modify, 2 create (mobile/src/api/client.ts, mobile/src/api/index.ts) | — | LAUNCHABLE |
| 2 | Auth store (Zustand + expo-secure-store) | AC #3 | 2 modify (package.json — add deps), 2 create (mobile/src/store/auth.ts, mobile/src/store/index.ts) | — | LAUNCHABLE |
| 3 | Auth screens (sign-in, sign-up) | AC #1, #2 | 0 modify, 3 create (mobile/src/app/(auth)/sign-in.tsx, mobile/src/app/(auth)/sign-up.tsx, mobile/src/app/(auth)/_layout.tsx) | — | BLOCKED (by #1, #2) |
| 4 | Tab layout + screens (Portfolio, Insights, Settings) | AC #5, #7 | 0 modify, 5 create (mobile/src/app/(tabs)/_layout.tsx, mobile/src/app/(tabs)/portfolio.tsx, mobile/src/app/(tabs)/insights.tsx, mobile/src/app/(tabs)/settings.tsx, mobile/src/app/_layout.tsx) | — | BLOCKED (by #2) |
| 5 | Broker connect screen (expo-auth-session) | AC #4 | 1 modify (package.json — add expo-auth-session), 1 create (mobile/src/components/BrokerConnect.tsx) | — | BLOCKED (by #1, #2) |
| 6 | Portfolio data hooks (TanStack Query) | AC #5 | 1 modify (package.json — add tanstack/react-query), 2 create (mobile/src/hooks/usePortfolio.ts, mobile/src/hooks/index.ts) | — | BLOCKED (by #1) |
| 7 | Auth guard (redirect unauthenticated) | AC #1, #3 | 0 modify, 1 create (mobile/src/components/AuthGuard.tsx) | — | BLOCKED (by #2) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (API client) ──┬──→ Subtask 3 (auth screens)
Subtask 2 (auth store) ──┤──→ Subtask 4 (tab layout)
                          ├──→ Subtask 5 (broker connect)
Subtask 1 ────────────────┤──→ Subtask 6 (portfolio hooks)
Subtask 2 ────────────────┘──→ Subtask 7 (auth guard)
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | none | NO |
| Subtask 3 | Subtask 4 | mobile/src/app/_layout.tsx (potential) | YES — serialize via single worker |
| Subtask 5 | Subtask 6 | none | NO |

### Batch Plan
- **Batch 1:** Subtask 1, 2 (parallel — no overlap)
- **Batch 2:** Subtask 3, 4, 5, 6, 7 (sequential due to _layout.tsx overlap between 3 and 4; but 5, 6, 7 can parallel)
- **Recommended workers:** 2
- **Estimated batches:** 3

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | axios interceptor patterns |
| 2 | Zustand store, expo-secure-store |
| 3 | Expo Router auth flow patterns |
| 4 | Expo Router tabs |
| 5 | expo-auth-session OAuth patterns |
| 6 | TanStack Query (React Query) |
| 7 | React Navigation auth guard pattern |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| expo-auth-session deep link (investiq://) may not work on all simulators | MEDIUM | Test on physical device; use Expo development build (not Expo Go) for deep links |
| Axios interceptor token refresh race condition (multiple concurrent 401s) | HIGH | Queue failed requests, refresh once, replay all queued requests |
| Expo Router layout structure must be exactly right | MEDIUM | Follow Expo Router v3 file-based routing conventions; test navigation flow manually |
| TanStack Query cache invalidation after auth change | LOW | Clear query cache on logout/login via queryClient.clear() |

## Configuration
- **Workers:** 2
- **Mode:** parallel
- **Estimated batches:** 3
- **Branch:** `feat/m1-7-mobile-shell`
- **Batch:** 2 (parallel with Jobs 4, 5, 6; blocked by Job 3)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-10-m1-7-mobile-shell.md
```
