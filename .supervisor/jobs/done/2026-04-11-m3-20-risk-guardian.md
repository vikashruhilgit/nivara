# Supervisor Job: Risk Guardian (Mode E) — Alerts, Notifications, WebSocket

## Environment
- **Project:** /Users/vikashruhil/Documents/work/AI/Nivara
- **CLAUDE.md:** Expected (created by Job 1)
- **Git:** Expected initialized (by Job 1)
- **GitHub CLI:** Assumed authenticated
- **Blockers:** 0 | **Warnings:** 0
- **Prerequisite:** Job 15 (risk models — needs volatility/VaR data) and Job 19 (safety layer — needs guardian framework and audit trail) must be complete

## Task
**Goal:** Build Risk Guardian (Mode E): position monitoring, volatility alerts (>2x ADR triggers alert), earnings alerts (5-day lookahead — flag holdings with upcoming earnings), macro alerts (FRED economic indicators — rate changes, employment data). Notification channels: dashboard toast + in-app feed (default, always), Expo Push (mobile, registered devices), email opt-in (BYOSMTP personal, Resend SaaS Phase 2). Device registration: POST /api/devices/register (Expo push token). Notification API: GET /api/notifications (paginated), PATCH /api/notifications/{id}/read. WebSocket: ws://host/ws/alerts (ticket-based auth).

**Problem Statement:**
Users need proactive alerts when their holdings face elevated risk — volatility spikes, upcoming earnings, or macro events. Without the Risk Guardian, users must manually check each holding. The notification system is also the foundation for all future alerting (Mode B assisted trading, Mode C automated). Currently, no alerting or notification infrastructure exists. Success looks like automated risk monitoring that detects events and delivers alerts through multiple channels with persistence and read-tracking.

## Acceptance Criteria
- [ ] Given AAPL volatility >2x its 20-day ADR (Average Daily Range), then volatility alert created in notifications table
- [ ] Given registered Expo push token for user, when volatility alert triggered, then push notification sent to device
- [ ] Given TSLA earnings in 3 days, then earnings alert sent to users holding TSLA
- [ ] Given FRED data shows rate change, then macro alert created for all users
- [ ] Given GET /api/notifications?page=1&per_page=20, then returns paginated list sorted by created_at DESC
- [ ] Given GET /api/notifications?read=false, then returns only unread notifications
- [ ] Given PATCH /api/notifications/{id}/read, then marks notification as read (sets read=true)
- [ ] Given POST /api/devices/register with valid Expo push token, then device registered for user
- [ ] Given WebSocket connection to ws://host/ws/alerts with valid ticket, then receives real-time alert events
- [ ] Given email opt-in with SMTP credentials configured, when alert triggered, then email sent via user's SMTP
- [ ] Given no email configured, when alert triggered, then only dashboard toast + in-app feed delivered (no error)

## Subtask Structure

| # | Title | Acceptance Criteria Subset | Est. Files (modify/create) | Skills | Status |
|---|-------|---------------------------|---------------------------|--------|--------|
| 1 | Risk Guardian engine (monitoring + alert detection) | AC #1, #3, #4 | 0 modify, 2 create (backend/app/safety/risk_guardian.py, backend/app/schemas/notification.py) | pandas, FRED API | LAUNCHABLE |
| 2 | Notification base + channels (dashboard, push, email) | AC #2, #10, #11 | 0 modify, 4 create (backend/app/notifications/__init__.py, backend/app/notifications/base.py, backend/app/notifications/push.py, backend/app/notifications/email.py) | Expo Push SDK, SMTP | LAUNCHABLE |
| 3 | Device registration API | AC #8 | 1 modify (backend/app/main.py — register router), 2 create (backend/app/api/devices.py, backend/app/models/device.py) | FastAPI, SQLAlchemy | LAUNCHABLE |
| 4 | Notification API endpoints | AC #5, #6, #7 | 1 modify (backend/app/main.py — register router), 1 create (backend/app/api/notifications.py) | FastAPI, SQLAlchemy pagination | BLOCKED (by #1) |
| 5 | WebSocket alerts handler | AC #9 | 0 modify, 1 create (backend/app/api/ws_alerts.py) | FastAPI WebSocket, ticket-based auth | BLOCKED (by #1, #2) |
| 6 | Wire guardian + notification dispatch | — (integration) | 1 modify (backend/app/safety/risk_guardian.py — import notification dispatcher) | — | BLOCKED (by #1, #2) |
| 7 | Tests | All ACs | 0 modify, 3 create (backend/tests/test_risk_guardian.py, backend/tests/test_notifications.py, backend/tests/test_ws_alerts.py) | pytest, WebSocket test client | BLOCKED (by #6) |

## Parallelism Analysis

### Dependency Graph
```
Subtask 1 (guardian engine) ──┬──→ Subtask 4 (notification API) ──┐
                              ├──→ Subtask 6 (wire dispatch)  ────┤──→ Subtask 7 (tests)
Subtask 2 (notification channels) ┘──→ Subtask 5 (WebSocket)  ───┘
Subtask 3 (device registration) ─────────────────────────────────────→ (independent)
```

### File Overlap Matrix

| Group A | Group B | Overlapping Files | Serialize? |
|---------|---------|-------------------|------------|
| Subtask 1 | Subtask 2 | none | NO |
| Subtask 1 | Subtask 3 | none | NO |
| Subtask 2 | Subtask 3 | none | NO |
| Subtask 1 | Subtask 6 | backend/app/safety/risk_guardian.py | YES |

### Batch Plan
- **Batch 1:** Subtask 1, 2, 3 (parallel — no file overlap, independent modules)
- **Batch 2:** Subtask 4, 5, 6 (Subtask 4 depends on 1; Subtask 5 depends on 1, 2; Subtask 6 depends on 1, 2)
- **Batch 3:** Subtask 7 (tests, depends on all)
- **Recommended workers:** 3
- **Estimated batches:** 3

## Skill References

| Subtask | Skills |
|---------|--------|
| 1 | pandas ADR calculation, FRED API, earnings calendar (yfinance) |
| 2 | Expo Push notifications (expo-server-sdk-python), smtplib, provider pattern |
| 3 | FastAPI router, SQLAlchemy model, Pydantic v2 |
| 4 | FastAPI router, SQLAlchemy async pagination |
| 5 | FastAPI WebSocket, ticket-based auth (Redis short-lived ticket) |
| 6 | Python async dispatch, channel routing |
| 7 | pytest, WebSocket test client, mock SMTP/push |

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Expo Push SDK requires valid push token from mobile app (not built yet) | MEDIUM | Implement push sender; test with mock tokens; real tokens come when mobile ships |
| Earnings calendar data may not be in price_history or separate table | MEDIUM | Use yfinance .calendar property or hardcode upcoming earnings for known symbols |
| WebSocket ticket-based auth adds complexity | MEDIUM | Simple flow: POST /api/ws/ticket returns short-lived Redis key; WS validates on connect |
| FRED API rate limits or data format changes | LOW | Cache FRED data daily; handle missing gracefully (skip macro alerts) |
| SMTP credentials stored by user — security concern | HIGH | Encrypt SMTP credentials with same AES-256-GCM as broker tokens; never log credentials |

## Configuration
- **Workers:** 3
- **Mode:** parallel
- **Estimated batches:** 3
- **Branch:** `feat/m3-20-risk-guardian`
- **Batch:** 8 (blocked by Jobs 15, 19)

## Handoff
```
/supervisor job: .supervisor/jobs/pending/2026-04-11-m3-20-risk-guardian.md
```

## Outcome
- heal_loop_ran: true
- heal_decision: PASS
- heal_iterations: 1
- heal_remaining_issues: 0 (blocking); 5 deferred (perf N+1, WS ticket logging, redundant flush, WS test gaps, email channel wiring)
- PR: https://github.com/vikashruhilgit/nivara/pull/20
- Tests: 24/24 passing
- Status: completed
