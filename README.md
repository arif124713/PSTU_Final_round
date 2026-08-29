# MoneyMove

A closed-ecosystem digital money movement platform — send, request, schedule, and split money between users, with an AI chat assistant, fraud-prevention guardrails, and human + AI-backed support. Built as a full-stack FastAPI + React application backed by MySQL and Redis.

> Every new user starts with a simulated **৳100,000** balance. No real bank integration, no real payment rails — all money stays inside the platform.

---

## Table of Contents

- [Feature Overview](#feature-overview)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Database Schema](#database-schema)
- [API Reference](#api-reference)
- [Redis Key Design](#redis-key-design)
- [Security & Fraud Prevention](#security--fraud-prevention)
- [AI Assistant](#ai-assistant)
- [Background Jobs (Celery)](#background-jobs-celery)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Design Notes & Deviations from Spec](#design-notes--deviations-from-spec)

---

## Feature Overview

### Identity & Auth
- Mobile-number + OTP registration flow (`send-otp` → `verify-otp` → `register`), OTP demo code fixed at `1234`
- One national ID (NID) hash per account — duplicate NID registration is rejected
- Password (bcrypt) for login, a **separate** 6-digit transaction PIN (bcrypt) for money movement
- JWT access/refresh tokens; PIN lockout after 3 failed attempts (15-minute lock, Redis-backed)
- QR code generated on signup for peer-to-peer discovery

### Core Money Movement
- **Send money** — full atomic transfer (`SELECT FOR UPDATE` row locking, debit + credit + transaction insert as one commit), idempotency-key protected against double-submits
- **Receiver validation** — pre-flight lookup by mobile number, user ID, or name before every transfer
- **Money requests** — ask another user to pay you, with accept/decline and a 48-hour expiry
- **Transaction history** — paginated, filterable by direction/status/date range, with monthly sent/received summaries
- **Transaction detail** — per-transaction view with a 7-day dispute window

### Scheduled Payments
- One-time or recurring (weekly / monthly / yearly) payment reminders — rent, subscriptions, recurring bills
- **The system never auto-pays.** It only reminds; the user still taps "Pay Now" and enters their PIN every cycle
- `day_of_month` capped at 1–28 so monthly/yearly schedules survive February safely
- Missed cycles are logged and the schedule advances — past payments are never retroactively executed
- Pause/resume, edit label/amount/reminder window, full per-cycle history log
- Reminders sent daily at 08:00 (Asia/Dhaka) via Celery Beat, deduplicated per cycle in Redis

### Group Payments & Auto-Settling Debts
- Split a bill equally among up to 20 members — creator collects each member's share
- A member can **agree and pay immediately** (if they have balance) or **agree now, pay later**: agreeing is binding consent *and* pre-authorization for future auto-deduction
- **Auto-deduction engine**: the moment a member with an outstanding debt receives *any* incoming money, their debt is automatically, partially or fully, settled FIFO (oldest debt first) — no PIN needed on the auto-deduction itself, since consent was captured at agreement time
- Creator can remind a debtor (rate-limited to one reminder per 24h), forgive an individual debt, or cancel the whole group with atomic refunds to everyone who already paid
- Groups auto-expire after 72 hours if members haven't responded
- `GET /debts/my-debts` and `GET /debts/owed-to-me` give a cross-group view of everything owed and everything you're owed

### AI Assistant (Chat-Driven Banking)
- Natural-language chat backed by the DeepSeek API using OpenAI-style function/tool calling
- Can validate receivers, check balance, view transaction history & spending summaries, view pending requests
- Can **stage a transfer** conversationally — but the PIN is never typed into the chat. The agent stages a draft and the frontend opens a native secure PIN pad that talks directly to the backend, bypassing the LLM entirely
- Can **create and list scheduled payments** directly from chat (e.g. *"pay my landlord ৳8,000 every month on the 1st, remind me 3 days before"*) — safe to execute without a PIN since scheduling only sets up a reminder and never moves money
- System prompt enforces strict rules: never ask for or echo a PIN, never show a full mobile number, always confirm large transfers explicitly

### Support
- **RAG chatbot**: admin-uploaded PDFs are parsed (PyMuPDF) and indexed with a TF-IDF retriever; user questions are answered strictly from retrieved context, with automatic escalation-to-human suggestions on low-confidence answers
- **Human ticket system**: file a dispute against a transaction (with a 7-day window), open general tickets, thread messages with support staff, category-based routing

### Notifications
- In-app notification feed for every money-in/out event, request activity, scheduled-payment reminders, group-payment activity, debt settlements, account freezes, and support updates
- Unread-count surfaced on the dashboard

### Admin
- User management: search, view detail, freeze/unfreeze accounts with a reason
- Transaction oversight: browse all transactions, dedicated flagged-transaction queue (velocity / unusual-amount triggers)
- Support ticket queue: assign, message, resolve
- Immutable, append-only audit log (every security-relevant event — logins, transfers, PIN failures, freezes, reversals — insert-only, never updated or deleted)
- RAG knowledge base management: upload/list/delete support PDFs

### Fraud & Safety Guardrails
See [Security & Fraud Prevention](#security--fraud-prevention) below — cooldowns, daily limits, velocity checks, unusual-amount confirmation, and PIN lockout all apply uniformly across direct transfers, request fulfillment, scheduled pay-now, and group-payment agreements, because they all funnel through the same atomic transfer primitive.

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | React 19 (Vite 8) | TypeScript, React Router 7, TanStack Query, Zustand (persisted auth store), Tailwind CSS 4, Axios |
| Backend | FastAPI (Python) | Fully async request path |
| Database | MySQL 8.x (InnoDB) | Async access via SQLAlchemy 2.x + `aiomysql` |
| Migrations | Alembic | Versioned schema migrations |
| Cache / State | Redis | Rate limits, cooldowns, OTP/PIN state, idempotency keys, reminder/notification throttles, Celery broker & result backend |
| Background Jobs | Celery + Redis broker | Scheduled-payment reminders, group-payment expiry sweep |
| LLM | DeepSeek API (OpenAI-compatible) | Chat agent tool-calling + RAG answer generation |
| Support Retrieval | scikit-learn TF-IDF + PyMuPDF | Local, dependency-light document retrieval (see [Design Notes](#design-notes--deviations-from-spec)) |
| Auth | JWT (`python-jose`) | Access + refresh tokens |
| Password / PIN Hashing | `bcrypt` | Direct bcrypt API (not passlib — see Design Notes) |
| Charts | Matplotlib (Agg backend) | Server-rendered spending-summary charts for the agent |
| HTTP Client | `httpx` | Async external API calls (DeepSeek) |

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                      React Frontend (Vite)                    │
│   Dashboard · Send · Scheduled · Groups · Debts · History ·   │
│   Agent Chat · Login/Register              (port 5173)        │
└───────────────────────────┬───────────────────────────────────┘
                             │ REST (/api/v1/*), proxied to backend in dev
┌───────────────────────────▼───────────────────────────────────┐
│                        FastAPI Backend                        │
│                                                                 │
│  Routers → Services → SQLAlchemy models → MySQL                │
│  (auth, transactions, requests, scheduled, group-payments,     │
│   debts, notifications, support, admin, agent, dashboard)      │
│                                                                 │
│  Cross-cutting: Redis-backed fraud/rate-limit checks,           │
│  bcrypt PIN/password hashing, JWT auth dependency,              │
│  append-only audit logging on every sensitive action            │
└──────────┬───────────────────────────────┬────────────────────┘
           │                               │
┌──────────▼──────────┐         ┌──────────▼──────────────────┐
│        Redis         │         │           MySQL              │
│ • OTP / PIN attempts  │         │ users · transactions ·       │
│ • Cooldowns & limits   │         │ money_requests · scheduled_  │
│ • Idempotency keys     │         │ payments(+logs) · group_     │
│ • Reminder/throttle    │         │ payments/members · member_   │
│   dedup keys            │         │ debts · debt_payments ·      │
│ • Celery broker/backend │         │ notifications · support_     │
└────────────────────────┘         │ tickets(+messages) · audit_  │
                                    │ log · saved_beneficiaries    │
                                    └───────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────────┐
│                        Celery Beat + Worker                      │
│  • 08:00 Asia/Dhaka daily — scheduled-payment reminder scan       │
│  • Every 30 min — group-payment 72h expiry sweep                 │
│  (both are also exposed as admin-triggerable endpoints so the    │
│   app is fully testable without a running Celery worker)         │
└────────────────────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────────┐
│                          AI / Support Layer                       │
│  DeepSeek API  ←→  Agent tool-calling loop (in-process, FastAPI)  │
│  TF-IDF retriever over admin-uploaded, PyMuPDF-parsed support PDFs │
└────────────────────────────────────────────────────────────────┘
```

### Key architectural decisions

- **One atomic transfer primitive, reused everywhere.** `transfer_service.send_money()` performs the pessimistic-locked debit/credit/insert and every fraud/rate-limit check. Direct sends, request fulfillment, scheduled-payment "Pay Now", and group-payment "Agree & Pay" all call into it — so safety rules never need to be re-implemented per feature.
- **PIN never touches the LLM.** The agent can *stage* a transfer, but the PIN is collected by a native frontend modal and submitted straight to `/transactions/confirm`, bypassing the chat/LLM context entirely.
- **Auto-deduction is a `BackgroundTask`, not a request-blocking step.** After any transfer or request-acceptance credits a receiver, `settle_pending_debts` runs off the request path, walks the receiver's outstanding group-payment debts FIFO, and settles what it can from their current balance — including a bounded recursive cascade (with a visited-set guard) if that payoff itself funds another person's debt.
- **Everything the Celery scheduler does is also a plain endpoint.** The reminder scan and the group-expiry sweep are exposed as `_run-reminders` / `_run-expiry` admin endpoints, so the whole system is testable end-to-end without standing up a Celery worker.
- **Audit log is insert-only.** Every security-relevant action (logins, PIN failures, freezes, transfers, cancellations, debt settlements) writes an immutable `audit_log` row — never updated, never deleted.

---

## Project Structure

```
backend/
├── alembic/                     # DB migrations
│   └── versions/
├── app/
│   ├── core/security.py         # JWT, bcrypt hashing/verification
│   ├── models/                  # SQLAlchemy ORM models
│   ├── schemas/                 # Pydantic request/response schemas
│   ├── routers/                 # FastAPI route handlers (thin — delegate to services)
│   ├── services/                # Business logic
│   ├── tasks/                   # Celery task wrappers around service functions
│   ├── middleware/               # Rate limiting
│   ├── celery_app.py            # Celery app + Beat schedule
│   ├── config.py                # Pydantic-settings (.env driven)
│   ├── database.py              # Async SQLAlchemy engine/session
│   ├── dependencies.py          # Auth dependencies (get_current_user, require_admin)
│   ├── redis_client.py
│   └── main.py                  # FastAPI app assembly, router registration
└── requirements.txt

frontend/
├── src/
│   ├── pages/                   # Dashboard, SendMoney, Scheduled, GroupPayments,
│   │                             # Debts, History, AgentChat, Login, Register
│   ├── components/               # PinPad, shared UI kit, glass-morphism primitives
│   ├── store/authStore.ts        # Zustand store, persisted to localStorage
│   ├── lib/api.ts                # Axios instance + auth-header interceptor
│   └── App.tsx                   # Routes
└── package.json
```

---

## Database Schema

All tables use InnoDB with `utf8mb4`. Grouped by domain:

**Identity**
`users` · `otp_store` · `login_sessions` · `saved_beneficiaries`

**Core money movement**
`transactions` · `money_requests` · `transaction_drafts` (agent-staged transfers awaiting PIN) · `split_bills` / `split_bill_participants` *(model present, superseded by Group Payments — see Design Notes)*

**Scheduled payments**
`scheduled_payments` · `scheduled_payment_logs` (immutable per-cycle log: `reminder_sent` / `paid` / `missed` / `skipped`)

**Group payments & debts**
`group_payments` · `group_payment_members` · `member_debts` · `debt_payments` (immutable auto-deduction installment log)

**Support & notifications**
`support_tickets` · `ticket_messages` · `rag_documents` · `notifications`

**Audit**
`audit_log` — append-only, insert-only

Full column-level DDL lives in the Alembic migrations (`backend/alembic/versions/`) and the original design docs (`backend_spec.md`, `spec-new-features.md`).

---

## API Reference

All routes are prefixed `/api/v1`. Interactive OpenAPI docs are available at `/docs` when the backend is running.

| Domain | Base path | Highlights |
|---|---|---|
| Auth | `/auth` | `send-otp`, `verify-otp`, `register`, `login`, `logout` |
| Users | `/users` | `me`, `search` |
| Transactions | `/transactions` | `validate-receiver`, `send`, `confirm` (drafts), `history`, `{reference_id}` |
| Requests | `/requests` | `create`, list, `{id}/accept`, `{id}/decline` |
| Scheduled Payments | `/scheduled` | `create`, list, `{id}` (get/edit/delete), `{id}/pause`, `{id}/resume`, `{id}/pay-now`, `{id}/history` |
| Group Payments | `/group-payments` | `create`, list, `{id}`, `{id}/respond` (agree/decline), `{id}/members`, `{id}/members/{member_id}/remind`, `{id}/members/{member_id}/cancel-debt`, `{id}/cancel` |
| Debts | `/debts` | `my-debts`, `owed-to-me`, `{debt_id}/history` |
| Notifications | `/notifications` | list, `mark-read` |
| Support | `/support` | `dispute`, `tickets`, `tickets/{id}/messages`, `chat` (RAG) |
| Agent | `/agent` | `chat`, `history/{session_id}` |
| Dashboard | `/dashboard` | Aggregated home-screen summary |
| Admin | `/admin` | User management/freeze, transaction & flagged-transaction views, ticket queue, audit log, RAG doc management |

---

## Redis Key Design

| Key pattern | Purpose | TTL |
|---|---|---|
| `idem:{user_id}:{key}` | Idempotency cache for `/transactions/send` | 24h |
| `cooldown:{sender_id}:{receiver_id}` | 10-minute cooldown between the same sender/receiver pair | 10 min |
| `daily_sent:{user_id}:{date}` | Running daily transfer total (paisa) | until midnight |
| `velocity:{user_id}` | Rolling transfer count for fraud flagging | 10 min |
| `first_large:{user_id}` | Tracks whether extra confirmation was already given for a large transfer | 7 days |
| `pin:attempts:{user_id}` / `pin:locked:{user_id}` | PIN lockout counter / lock | 15 min |
| `group:idem:{creator_id}:{key}` | Idempotency for group-payment creation | 24h |
| `group:reminder:{group_id}:{member_id}` | Creator's debt-reminder throttle | 24h |
| `sched:reminded:{schedule_id}:{date}` | Dedupes the daily reminder scan per cycle | 23h |

---

## Security & Fraud Prevention

| Rule | Enforcement | Applies to |
|---|---|---|
| Can't send to self | API validation | All transfers |
| Can't exceed balance | `SELECT FOR UPDATE` row lock + guarded `UPDATE ... WHERE balance >= amount` | All transfers, incl. auto-deduction |
| Sender/receiver must be active & unfrozen | Pre-check | All transfers |
| PIN verification | bcrypt, server-side only | Direct send, request accept, scheduled pay-now, group agree |
| PIN lockout | 3 attempts → 15-minute lock | Every PIN check |
| 10-minute cooldown (same pair) | Redis TTL key | All transfers |
| Daily transfer limit | Redis counter, resets at midnight | All transfers |
| Per-transaction max | Config constant (default ৳25,000) | All transfers |
| Velocity check | Rolling 10-minute counter, flags (doesn't block) after 5 transfers | All transfers |
| Unusual-amount confirmation | First transfer over ৳10,000 requires explicit `extra_confirmed` | All transfers |
| Idempotency | Client-generated key, 24h cache | `/transactions/send` |
| Account freeze | Admin action, blocks all outgoing/incoming activity | Global |
| Auto-deduction consent | Captured once at group-payment "Agree", scoped to that exact debt — never open-ended | Group-payment debts only |
| Auto-deduction never bypasses a frozen account | Debtor frozen → deduction blocked and retried on their next event; creditor frozen → that specific debt is skipped, others proceed | Debt settlement |

The AI agent adds another layer on top: it must call `validate_receiver` before any transfer, must never request or echo a PIN, must mask mobile numbers to last-4-digits, and must explicitly confirm any transfer over ৳10,000 with the user before staging it.

---

## AI Assistant

The chat agent (`backend/app/services/agent_service.py`) is an OpenAI-style tool-calling loop against the DeepSeek chat-completions endpoint (not a standalone MCP server — see Design Notes). Per-session history is kept in FastAPI process memory only.

**Read tools:** `validate_receiver`, `get_balance`, `get_transaction_history`, `get_spending_summary` (renders a matplotlib chart), `get_pending_requests`, `get_scheduled_payments`

**Write tools:**
- `initiate_transfer` — stages a `transaction_drafts` row and returns a `pending_pin` action; the frontend then renders a native PIN pad that posts directly to `/transactions/confirm`. The PIN never appears in the chat or the LLM prompt.
- `request_money` — creates a money request directly (no PIN needed to *ask* for money).
- `create_scheduled_payment` — creates an active schedule directly (no PIN needed — scheduling only sets up a reminder; the actual payment still requires "Pay Now" + PIN in the app later).

The system prompt is regenerated per turn with the user's identity, live balance, and the current date (so the model can resolve relative language like "next Friday" or "every 1st of the month" into concrete schedule fields).

---

## Background Jobs (Celery)

```
celery -A app.celery_app.celery_app worker --beat --loglevel=info
```

| Job | Schedule | What it does |
|---|---|---|
| `check_scheduled_reminders` | Daily 08:00 Asia/Dhaka | Scans active schedules in their reminder window, sends at-most-one reminder per cycle (Redis-deduped), marks overdue cycles `missed` and advances them |
| `expire_group_payments` | Every 30 minutes | Marks unresponded member invites `expired` after 72h; marks the whole group `expired` if nobody ever agreed |

Both are also exposed as `POST /scheduled/_run-reminders` and `POST /group-payments/_run-expiry` (admin-only), so the reminder/expiry logic can be exercised without a running Celery worker.

---

## Getting Started

### Prerequisites
- Python 3.11+ (a virtualenv is expected at `venv/` alongside `backend/`)
- Node.js + npm
- MySQL 8.x running locally
- Redis running locally

### Backend

```bash
cd backend
python -m venv ../venv        # if not already created
../venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source ../venv/bin/activate && pip install -r requirements.txt  # macOS/Linux

cp .env.example .env          # fill in SECRET_KEY, DATABASE_URL, DEEPSEEK_API_KEY, etc.

# Create the database, then run migrations:
python -m alembic upgrade head

# Start the API:
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API docs: `http://127.0.0.1:8000/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App: `http://localhost:5173` — the Vite dev server proxies `/api` to `http://localhost:8000`.

### Background worker (optional for local testing)

```bash
cd backend
../venv/Scripts/python.exe -m celery -A app.celery_app.celery_app worker --beat --loglevel=info
```

Not required to exercise scheduled-payment or group-payment expiry logic locally — use the `_run-reminders` / `_run-expiry` admin endpoints instead.

---

## Environment Variables

See `backend/.env.example` for the full list. Key ones:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | JWT signing secret |
| `DATABASE_URL` | `mysql+aiomysql://user:pass@host:3306/money_app` |
| `REDIS_URL` | Redis connection for fraud/rate-limit state |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | LLM provider for the chat agent and RAG answers |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Separate Redis DBs for Celery |
| `MAX_SINGLE_TRANSFER_BDT`, `DAILY_TRANSFER_LIMIT_BDT`, `COOLDOWN_SECONDS`, `PIN_MAX_ATTEMPTS`, `PIN_LOCK_SECONDS`, `VELOCITY_MAX_TRANSFERS`, `VELOCITY_WINDOW_SECONDS`, `UNUSUAL_AMOUNT_THRESHOLD` | Fraud/safety rule tuning |
| `STARTER_BALANCE_BDT` | Signup bonus balance (default ৳100,000) |
| `DISPUTE_WINDOW_DAYS` | How long after a transaction a dispute can be filed |

---

## Design Notes & Deviations from Spec

The original design docs (`backend_spec.md`, `spec-new-features.md`) describe a larger production-shaped architecture. A few places the actual implementation intentionally diverges, for good reasons:

- **No standalone `db-mcp-server` / literal MCP protocol.** The chat agent calls FastAPI service functions directly (an in-process OpenAI-style tool-calling loop) rather than routing reads through a separate MCP server process. Functionally equivalent for this app's scale, with one fewer moving part.
- **TF-IDF instead of ChromaDB for support-doc retrieval.** ChromaDB's default embedding function depends on `onnxruntime`, whose compiled extension fails to load on this environment's Python version. `scikit-learn`'s TF-IDF vectorizer is pure NumPy/SciPy, has solid prebuilt wheels, and is more than adequate for a small PDF knowledge base.
- **`bcrypt` directly, not via `passlib`.** `passlib`'s bcrypt handler reads a `bcrypt.__about__.__version__` attribute that modern `bcrypt` releases removed, breaking it silently. Calling `bcrypt`'s own API directly sidesteps that.
- **The original `split_bills` design is superseded by Group Payments.** The `split_bills` / `split_bill_participants` models still exist but aren't wired to any endpoint — Group Payments implements the same "split a bill" use case with a substantially richer feature set (partial-balance debt tracking, auto-deduction, reminders, refundable cancellation).
- **Single-balance-column locking, not a ledger.** `users.balance` is updated under `SELECT FOR UPDATE`, which is correct and sufficient at this scale. The documented production migration path is a double-entry `ledger_entries` table (`SUM(credit) - SUM(debit)`), which also yields a full audit trail by construction — intentionally deferred here.
