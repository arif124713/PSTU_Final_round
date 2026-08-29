# 💸 Money Movement Application — Full Technical Specification

> **Hackathon:** PSTU IT Carnival 2026
> **Date:** 29 August 2026 | 9:00 AM – 3:00 PM
> **Challenge:** Money Movement Application
> **Team Stack:** React · FastAPI · MySQL · DeepSeek API · ChromaDB · Redis · db-mcp-server

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack](#2-tech-stack)
3. [System Architecture](#3-system-architecture)
4. [Database Schema](#4-database-schema)
5. [Authentication & Identity](#5-authentication--identity)
6. [Core Money Movement](#6-core-money-movement)
7. [Safety & Fraud Prevention](#7-safety--fraud-prevention)
8. [Transaction History & Records](#8-transaction-history--records)
9. [MCP + AI Agent](#9-mcp--ai-agent)
10. [Support System (RAG + Human)](#10-support-system-rag--human)
11. [Notifications](#11-notifications)
12. [User Experience Features](#12-user-experience-features)
13. [Admin Dashboard](#13-admin-dashboard)
14. [API Endpoints Reference](#14-api-endpoints-reference)
15. [Redis Key Design](#15-redis-key-design)
16. [Security Considerations](#16-security-considerations)
17. [Environment Variables](#17-environment-variables)
18. [Project Structure](#18-project-structure)
19. [Build Priority for Hackathon](#19-build-priority-for-hackathon)
20. [Engineering Defense Guide — Judge Q&A](#20-engineering-defense-guide--judge-qa)

---

## 1. Project Overview

### Brief
A closed digital money ecosystem where users can send, receive, and request money from each other using simulated balances. The system is designed to be **correct, reliable, and trustworthy** — handling concurrency, fraud prevention, and dispute resolution like a real-world fintech product.

### Core User Stories
- "I need to send ৳2,500 to another user."
- "My friend owes me ৳1,200. I want to collect it through the app."
- "I accidentally sent money to the wrong person. I need help."
- "Send ৳5,000 to Ankon" — spoken to an AI agent.
- "What did I spend last month?" — asked to an AI agent.

### Closed Ecosystem Rules
- No real bank integration
- No real payment gateways
- Every new user receives **৳1,00,000 BDT (fake)** automatically on registration
- All money stays within the platform

---

## 2. Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | React (Vite) | User interface |
| Backend | FastAPI (Python 3.11+) | REST API server |
| Database | MySQL 8.x (InnoDB) | Primary data store |
| Cache / State | Redis 7.x | Rate limits, cooldowns, sessions, cache |
| LLM | DeepSeek API | AI agent + RAG answers |
| Vector DB | ChromaDB (local) | RAG knowledge base for support |
| PDF Parsing | LangChain + PyMuPDF | Load and chunk support PDFs |
| MCP Server | db-mcp-server (FreePeak) | Expose MySQL to LLM agent via MCP |
| Background Jobs | Celery + Redis broker | Notifications, audit logging, graph gen |
| Auth | JWT (python-jose) | Stateless session tokens |
| Password Hash | bcrypt (passlib) | Login password + Transaction PIN |
| HTTP Client | httpx | Async external API calls |
| ORM | SQLAlchemy 2.x (async) | DB access layer |
| Migrations | Alembic | DB schema versioning |

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Frontend                           │
│           (Vite · React Query · Axios · Zustand)               │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS REST + WebSocket
┌────────────────────────────▼────────────────────────────────────┐
│                     Nginx (Reverse Proxy)                       │
│              Load balancer + SSL termination                    │
└───┬────────────────────────┬────────────────────────────────────┘
    │                        │
┌───▼──────────┐    ┌────────▼──────────┐
│ FastAPI App 1│    │  FastAPI App N     │   ← Multiple workers (uvicorn)
│  (uvicorn)   │    │  (uvicorn)         │
└───┬──────────┘    └────────┬───────────┘
    │                        │
    └───────────┬────────────┘
                │
    ┌───────────┴──────────────────────────────┐
    │                                          │
┌───▼────────────────┐         ┌───────────────▼──────────────┐
│    Redis Cluster   │         │        MySQL Cluster          │
│                    │         │                              │
│ • JWT blocklist    │         │  Master (Writes Only)        │
│ • OTP store        │         │  ├── users                   │
│ • PIN lockout      │         │  ├── transactions            │
│ • Cooldown keys    │         │  ├── money_requests          │
│ • Daily limits     │         │  ├── audit_log               │
│ • Velocity tracker │         │  ├── support_tickets         │
│ • Idempotency keys │         │  └── notifications           │
│ • Balance cache    │         │                              │
│ • Celery broker    │         │  Read Replica (Reads Only)   │
└────────────────────┘         │  ├── transaction history     │
                               │  ├── reports & graphs        │
                               │  └── support queries         │
                               └──────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│                    Celery Workers                             │
│  • Push notifications    • Graph generation (matplotlib)     │
│  • Audit log writes      • Support ticket email alerts       │
│  • Velocity analysis     • PDF re-indexing jobs              │
└──────────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│              AI / MCP Layer                                   │
│                                                              │
│  ┌─────────────────────┐    ┌──────────────────────────────┐ │
│  │   db-mcp-server     │    │   ChromaDB (Local)           │ │
│  │  (FreePeak/db-mcp)  │    │   RAG vector store           │ │
│  │                     │    │   ← Admin uploads PDFs       │ │
│  │  MCP Tools:         │    │   ← LangChain chunking       │ │
│  │  • query_db()       │    │   ← DeepSeek embeddings      │ │
│  │  • execute_sql()    │    └──────────────────────────────┘ │
│  └─────────────────────┘                                     │
│                ↑                                             │
│         DeepSeek API  ←── Agent orchestration (FastAPI)     │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Database Schema

### 4.1 `users`
```sql
CREATE TABLE users (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    full_name       VARCHAR(100)        NOT NULL,
    mobile_number   VARCHAR(15)         NOT NULL UNIQUE,   -- +8801XXXXXXXXX format
    email           VARCHAR(255)        UNIQUE,
    nid_hash        VARCHAR(64)         NOT NULL UNIQUE,   -- SHA-256 of NID, one NID = one account
    nid_last4       CHAR(4)             NOT NULL,          -- for admin display only
    password_hash   VARCHAR(255)        NOT NULL,          -- bcrypt
    pin_hash        VARCHAR(255)        NOT NULL,          -- bcrypt, separate from password
    balance         DECIMAL(15,2)       NOT NULL DEFAULT 100000.00,  -- ৳1,00,000 starter
    qr_code         TEXT,                                  -- base64 encoded QR
    is_active       BOOLEAN             NOT NULL DEFAULT TRUE,
    is_frozen       BOOLEAN             NOT NULL DEFAULT FALSE,
    frozen_reason   VARCHAR(255),
    frozen_at       DATETIME,
    frozen_by       BIGINT UNSIGNED,                       -- admin user id
    role            ENUM('user','admin','support') NOT NULL DEFAULT 'user',
    mobile_verified BOOLEAN             NOT NULL DEFAULT FALSE,
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login_at   DATETIME,

    INDEX idx_mobile (mobile_number),
    INDEX idx_active (is_active),
    FOREIGN KEY (frozen_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

> **⚠️ Scalability Note — The Single Balance Column:** The `balance` column on the `users` table uses row-level `SELECT FOR UPDATE` locking which is correct for a hackathon. At 10M+ users and high concurrency this becomes a write bottleneck on hot accounts. **Production migration path:** Replace the balance column with a **double-entry ledger** — an immutable `ledger_entries` table with `debit` and `credit` columns, where the current balance is always computed as `SUM(credit) - SUM(debit)`. A materialized view or periodic balance snapshot prevents expensive full-table aggregation. This also gives you a full transaction audit trail by design. For the hackathon, row-level locking is the correct and sufficient answer.

### 4.2 `otp_store`
```sql
CREATE TABLE otp_store (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    mobile_number   VARCHAR(15)         NOT NULL,
    otp_code        CHAR(4)             NOT NULL,           -- always "1234" in demo
    purpose         ENUM('registration','pin_reset','login_verify') NOT NULL,
    is_used         BOOLEAN             NOT NULL DEFAULT FALSE,
    expires_at      DATETIME            NOT NULL,           -- 5 minutes from creation
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_mobile_purpose (mobile_number, purpose)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.3 `login_sessions`
```sql
CREATE TABLE login_sessions (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT UNSIGNED     NOT NULL,
    jwt_jti         VARCHAR(64)         NOT NULL UNIQUE,    -- JWT unique ID for blocklist
    ip_address      VARCHAR(45),
    user_agent      TEXT,
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at      DATETIME            NOT NULL,
    revoked         BOOLEAN             NOT NULL DEFAULT FALSE,

    INDEX idx_user (user_id),
    INDEX idx_jti (jwt_jti),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.4 `transactions`
```sql
CREATE TABLE transactions (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    reference_id    CHAR(36)            NOT NULL UNIQUE,   -- UUID v4, idempotency key
    sender_id       BIGINT UNSIGNED     NOT NULL,
    receiver_id     BIGINT UNSIGNED     NOT NULL,
    amount          DECIMAL(15,2)       NOT NULL,
    fee             DECIMAL(15,2)       NOT NULL DEFAULT 0.00,
    note            VARCHAR(255),                          -- memo/description
    status          ENUM('pending','completed','failed','disputed') NOT NULL DEFAULT 'pending',
    type            ENUM('transfer','request_fulfillment','split_fulfillment') NOT NULL DEFAULT 'transfer',
    initiated_via   ENUM('web','mobile','ai_agent')        NOT NULL DEFAULT 'web',
    flagged         BOOLEAN             NOT NULL DEFAULT FALSE,
    flag_reason     VARCHAR(255),
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at    DATETIME,

    INDEX idx_sender (sender_id),
    INDEX idx_receiver (receiver_id),
    INDEX idx_reference (reference_id),
    INDEX idx_status (status),
    INDEX idx_created (created_at),
    FOREIGN KEY (sender_id) REFERENCES users(id),
    FOREIGN KEY (receiver_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### 4.5 `money_requests`
```sql
CREATE TABLE money_requests (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    reference_id    CHAR(36)            NOT NULL UNIQUE,
    requester_id    BIGINT UNSIGNED     NOT NULL,           -- who wants money
    payer_id        BIGINT UNSIGNED     NOT NULL,           -- who should pay
    amount          DECIMAL(15,2)       NOT NULL,
    reason          VARCHAR(255),
    status          ENUM('pending','accepted','declined','expired') NOT NULL DEFAULT 'pending',
    transaction_id  BIGINT UNSIGNED,                        -- set when accepted
    expires_at      DATETIME            NOT NULL,           -- auto-expire after 48h
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    responded_at    DATETIME,

    INDEX idx_requester (requester_id),
    INDEX idx_payer (payer_id),
    INDEX idx_status (status),
    FOREIGN KEY (requester_id) REFERENCES users(id),
    FOREIGN KEY (payer_id) REFERENCES users(id),
    FOREIGN KEY (transaction_id) REFERENCES transactions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.6 `split_bills`
```sql
CREATE TABLE split_bills (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    reference_id    CHAR(36)            NOT NULL UNIQUE,
    created_by      BIGINT UNSIGNED     NOT NULL,
    title           VARCHAR(255)        NOT NULL,           -- "Dinner at XYZ"
    total_amount    DECIMAL(15,2)       NOT NULL,
    status          ENUM('open','completed','cancelled') NOT NULL DEFAULT 'open',
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE split_bill_participants (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    split_bill_id   BIGINT UNSIGNED     NOT NULL,
    user_id         BIGINT UNSIGNED     NOT NULL,
    amount_owed     DECIMAL(15,2)       NOT NULL,
    money_request_id BIGINT UNSIGNED,                      -- linked individual request
    status          ENUM('pending','paid') NOT NULL DEFAULT 'pending',

    FOREIGN KEY (split_bill_id) REFERENCES split_bills(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (money_request_id) REFERENCES money_requests(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.7 `audit_log` *(Append-only — NEVER UPDATE or DELETE)*
```sql
CREATE TABLE audit_log (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_type      VARCHAR(64)         NOT NULL,           -- e.g. TRANSFER_INITIATED, PIN_FAILED
    actor_id        BIGINT UNSIGNED,                        -- user who did the action
    target_id       BIGINT UNSIGNED,                        -- affected user (if any)
    entity_type     VARCHAR(32),                            -- 'transaction', 'user', 'ticket'
    entity_id       BIGINT UNSIGNED,
    payload         JSON,                                   -- full event data snapshot
    ip_address      VARCHAR(45),
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_actor (actor_id),
    INDEX idx_event (event_type),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- NOTE: Grant INSERT only on this table. No UPDATE, no DELETE, ever.
```

### 4.8 `saved_beneficiaries`
```sql
CREATE TABLE saved_beneficiaries (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT UNSIGNED     NOT NULL,
    beneficiary_id  BIGINT UNSIGNED     NOT NULL,
    nickname        VARCHAR(50),
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_user_beneficiary (user_id, beneficiary_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (beneficiary_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.9 `notifications`
```sql
CREATE TABLE notifications (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT UNSIGNED     NOT NULL,
    title           VARCHAR(100)        NOT NULL,
    body            TEXT                NOT NULL,
    type            ENUM(
                        'money_received',
                        'money_sent',
                        'request_received',
                        'request_accepted',
                        'request_declined',
                        'account_frozen',
                        'ticket_update',
                        'security_alert',
                        'system'
                    ) NOT NULL,
    reference_id    VARCHAR(64),                            -- transaction or ticket ref
    is_read         BOOLEAN             NOT NULL DEFAULT FALSE,
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_user_read (user_id, is_read),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.10 `support_tickets`
```sql
CREATE TABLE support_tickets (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    reference_id    CHAR(36)            NOT NULL UNIQUE,
    user_id         BIGINT UNSIGNED     NOT NULL,
    transaction_id  BIGINT UNSIGNED,                        -- NULL for general support
    category        ENUM(
                        'wrong_transfer',
                        'account_issue',
                        'request_dispute',
                        'general'
                    ) NOT NULL,
    subject         VARCHAR(255)        NOT NULL,
    description     TEXT                NOT NULL,
    status          ENUM('open','under_review','resolved','rejected') NOT NULL DEFAULT 'open',
    assigned_to     BIGINT UNSIGNED,                        -- support agent user id
    resolution_note TEXT,
    reversal_approved BOOLEAN           DEFAULT NULL,       -- NULL=not decided, TRUE/FALSE
    reversal_tx_id  BIGINT UNSIGNED,                        -- reversal transaction if approved
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    resolved_at     DATETIME,

    INDEX idx_user (user_id),
    INDEX idx_status (status),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (transaction_id) REFERENCES transactions(id),
    FOREIGN KEY (assigned_to) REFERENCES users(id),
    FOREIGN KEY (reversal_tx_id) REFERENCES transactions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.11 `ticket_messages`
```sql
CREATE TABLE ticket_messages (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ticket_id       BIGINT UNSIGNED     NOT NULL,
    sender_id       BIGINT UNSIGNED     NOT NULL,
    message         TEXT                NOT NULL,
    sender_role     ENUM('user','support','admin') NOT NULL,
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_ticket (ticket_id),
    FOREIGN KEY (ticket_id) REFERENCES support_tickets(id) ON DELETE CASCADE,
    FOREIGN KEY (sender_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 4.12 `transaction_drafts` *(Agent-initiated pending transfers — awaiting PIN from frontend)*
```sql
-- This table holds transfers the AI agent has staged but not yet executed.
-- The PIN is NEVER stored here. It is collected by the React frontend
-- and sent directly to /api/v1/transactions/confirm. The agent only
-- creates the draft; the human confirms with their PIN outside LLM context.
CREATE TABLE transaction_drafts (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    draft_id        CHAR(36)            NOT NULL UNIQUE,   -- UUID, returned to frontend
    sender_id       BIGINT UNSIGNED     NOT NULL,
    receiver_id     BIGINT UNSIGNED     NOT NULL,
    receiver_name   VARCHAR(100)        NOT NULL,          -- snapshot for display
    amount          DECIMAL(15,2)       NOT NULL,
    note            VARCHAR(255),
    initiated_via   ENUM('ai_agent')    NOT NULL DEFAULT 'ai_agent',
    status          ENUM('pending_pin','confirmed','expired','cancelled') NOT NULL DEFAULT 'pending_pin',
    expires_at      DATETIME            NOT NULL,           -- 5 minutes from creation
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_sender_status (sender_id, status),
    FOREIGN KEY (sender_id) REFERENCES users(id),
    FOREIGN KEY (receiver_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- Row expires via application logic (check expires_at); use a cron/Celery beat to
-- mark stale drafts as 'expired' every minute.
```

### 4.13 `rag_documents`
```sql
CREATE TABLE rag_documents (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    filename        VARCHAR(255)        NOT NULL,
    file_path       VARCHAR(500)        NOT NULL,           -- local disk path
    chroma_collection VARCHAR(64)       NOT NULL DEFAULT 'support_docs',
    chunk_count     INT                 NOT NULL DEFAULT 0,
    indexed_at      DATETIME,
    uploaded_by     BIGINT UNSIGNED,
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (uploaded_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 5. Authentication & Identity

### 5.1 Registration Flow

```
Step 1: Enter mobile number
        POST /api/v1/auth/send-otp
        Body: { mobile_number: "+8801XXXXXXXXX" }
        → Validates format (BD: +880 1X-XXXX-XXXX)
        → Checks: mobile not already registered
        → Creates OTP record in otp_store (code always "1234", expires 5 min)
        → Response: { message: "OTP sent", otp_expires_in: 300 }

Step 2: Verify OTP
        POST /api/v1/auth/verify-otp
        Body: { mobile_number, otp_code: "1234" }
        → Validates OTP from DB, checks expiry, checks not already used
        → Marks OTP as used
        → Response: { verified: true, temp_token: "<short-lived JWT 10 min>" }

Step 3: Complete Registration
        POST /api/v1/auth/register
        Headers: Authorization: Bearer <temp_token>
        Body: {
            full_name,
            nid_number,       -- 17-digit NID
            password,         -- min 8 chars
            transaction_pin,  -- exactly 6 digits
            email             -- optional
        }
        → Validates NID format (17 digits, numeric)
        → Checks SHA-256(nid_number) not in users.nid_hash (one NID = one account)
        → Hashes password with bcrypt
        → Hashes transaction_pin with bcrypt (stored separately)
        → Creates user with balance = 100000.00
        → Generates QR code (encode: user_id + mobile)
        → Writes ACCOUNT_CREATED to audit_log
        → Response: { user_id, access_token, refresh_token, balance: 100000 }
```

### 5.2 Login Flow

```
POST /api/v1/auth/login
Body: { mobile_number, password }
→ Fetch user by mobile
→ Check is_active and is_frozen (frozen → 423 with freeze reason)
→ bcrypt verify password
→ Generate JWT: { sub: user_id, jti: uuid4(), role, exp: +24h }
→ Store session in login_sessions
→ Write LOGIN_SUCCESS to audit_log
→ Response: { access_token, refresh_token, user: { id, name, balance, role } }
```

### 5.3 JWT Structure

```json
{
  "sub": "12345",
  "jti": "uuid-v4",
  "role": "user",
  "iat": 1234567890,
  "exp": 1234654290
}
```

- `jti` stored in Redis blocklist on logout: `jwt:blocklist:{jti}` TTL = remaining JWT lifetime
- All protected routes check Redis blocklist before processing

### 5.4 PIN Management

- Stored as bcrypt hash in `users.pin_hash`, completely separate from password
- PIN is **6 digits only**
- Wrong PIN attempts tracked in Redis: `pin:attempts:{user_id}` — incremented on failure
- After **3 failed attempts** → account PIN locked for 15 minutes: `pin:locked:{user_id}` TTL=900
- PIN lock does NOT freeze the account — only prevents transactions
- PIN reset requires: current mobile OTP verification

---

## 6. Core Money Movement

### 6.1 Send Money

**Full Transaction Flow (Critical Path):**

```
POST /api/v1/transactions/send

Headers: Authorization: Bearer <JWT>
Body: {
    idempotency_key: "uuid-v4",    -- client generates, prevents double-submit
    receiver_identifier: "01XXXXXXXXX",  -- mobile number or user_id
    amount: 5000.00,
    pin: "123456",
    note: "For dinner"             -- optional
}
```

**Server Processing Steps:**

```python
async def send_money(request, current_user):

    # ── Step 1: Idempotency check (Redis) ──────────────────────────
    idem_key = f"idem:{current_user.id}:{request.idempotency_key}"
    if await redis.get(idem_key):
        # Return the original transaction result, do not process again
        return cached_response

    # ── Step 2: Resolve receiver ───────────────────────────────────
    receiver = await get_user_by_mobile_or_id(request.receiver_identifier)
    if not receiver:
        raise HTTP404("Account not found")
    if not receiver.is_active:
        raise HTTP422("Receiver account is not active")
    if receiver.is_frozen:
        raise HTTP422("Receiver account is currently frozen")
    if receiver.id == current_user.id:
        raise HTTP422("Cannot send money to yourself")

    # ── Step 3: Return receiver name for frontend confirmation ──────
    # Frontend shows: "You are sending ৳5,000 to Ankon Dey. Confirm?"
    # This step is a separate API call: POST /api/v1/transactions/validate-receiver
    # The actual send requires a second call with pin

    # ── Step 4: Validate amount ────────────────────────────────────
    if request.amount <= 0:
        raise HTTP422("Amount must be positive")
    if request.amount > MAX_SINGLE_TRANSFER:   # e.g. ৳25,000
        raise HTTP422("Exceeds single transfer limit")

    # ── Step 5: Check 10-minute cooldown (Redis) ───────────────────
    cooldown_key = f"cooldown:{current_user.id}:{receiver.id}"
    if await redis.get(cooldown_key):
        ttl = await redis.ttl(cooldown_key)
        raise HTTP429(f"Wait {ttl} seconds before sending to this user again")

    # ── Step 6: Check daily limit (Redis) ─────────────────────────
    today = date.today().isoformat()
    daily_key = f"daily_sent:{current_user.id}:{today}"
    daily_spent = int(await redis.get(daily_key) or 0)
    if daily_spent + int(request.amount * 100) > DAILY_LIMIT_PAISA:
        raise HTTP429("Daily transfer limit exceeded")

    # ── Step 7: Check velocity (Redis, fraud detection) ────────────
    velocity_key = f"velocity:{current_user.id}"
    tx_count = await redis.incr(velocity_key)
    if tx_count == 1:
        await redis.expire(velocity_key, 600)    # 10 min window
    if tx_count > 5:
        # Flag for review but do NOT block (send to Celery for async analysis)
        flag_for_review.delay(current_user.id, "velocity_exceeded")

    # ── Step 8: Unusual amount check ───────────────────────────────
    if request.amount > 10000:
        first_large_key = f"first_large:{current_user.id}"
        if not await redis.get(first_large_key):
            # Frontend should have shown extra confirmation already
            # But verify the extra_confirm flag in request body
            if not request.extra_confirmed:
                raise HTTP422("Large transfer requires additional confirmation")

    # ── Step 9: PIN verification ───────────────────────────────────
    pin_locked = await redis.get(f"pin:locked:{current_user.id}")
    if pin_locked:
        raise HTTP423("PIN is locked. Try again in 15 minutes")
    pin_attempts = await redis.get(f"pin:attempts:{current_user.id}")
    if not bcrypt.verify(request.pin, current_user.pin_hash):
        attempts = await redis.incr(f"pin:attempts:{current_user.id}")
        await redis.expire(f"pin:attempts:{current_user.id}", 900)
        if attempts >= 3:
            await redis.setex(f"pin:locked:{current_user.id}", 900, 1)
            raise HTTP423("PIN locked after 3 failed attempts")
        raise HTTP401(f"Invalid PIN. {3 - attempts} attempts remaining")
    # Clear PIN attempts on success
    await redis.delete(f"pin:attempts:{current_user.id}")

    # ── Step 10: DB Atomic Transaction ────────────────────────────
    async with db.begin():   # All or nothing

        # Lock sender row for update (pessimistic locking)
        sender = await db.execute(
            "SELECT id, balance, is_frozen FROM users "
            "WHERE id = :id FOR UPDATE",
            {"id": current_user.id}
        )
        if sender.is_frozen:
            raise HTTP423("Your account has been frozen")
        if sender.balance < request.amount:
            raise HTTP422("Insufficient balance")

        # Debit sender
        await db.execute(
            "UPDATE users SET balance = balance - :amount WHERE id = :id",
            {"amount": request.amount, "id": current_user.id}
        )
        # Credit receiver
        await db.execute(
            "UPDATE users SET balance = balance + :amount WHERE id = :id",
            {"amount": request.amount, "id": receiver.id}
        )
        # Insert transaction record
        tx_id = await db.execute(
            "INSERT INTO transactions (...) VALUES (...)",
            { reference_id, sender_id, receiver_id, amount, note, status='completed' }
        )

    # ── Step 11: Post-transaction (async, non-blocking) ───────────
    # Set cooldown
    await redis.setex(cooldown_key, 600, 1)

    # Increment daily limit tracker (store in paisa to avoid float)
    await redis.incrby(daily_key, int(request.amount * 100))
    await redis.expireat(daily_key, tomorrow_midnight_unix())

    # Set idempotency cache (TTL 24h)
    await redis.setex(idem_key, 86400, json.dumps(response_data))

    # Update balance cache
    await redis.set(f"balance:{current_user.id}", float(sender.balance - request.amount))
    await redis.set(f"balance:{receiver.id}", ...) # invalidate or update

    # Async jobs via Celery
    send_notification.delay(receiver.id, "money_received", amount, sender_name)
    write_audit_log.delay("TRANSFER_COMPLETED", ...)

    # ── Step 12: Response ──────────────────────────────────────────
    return {
        "transaction_id": tx_id,
        "reference_id": reference_id,
        "amount": request.amount,
        "receiver_name": receiver.full_name,
        "new_balance": sender.balance - request.amount,
        "status": "completed",
        "timestamp": datetime.utcnow().isoformat()
    }
```

### 6.2 Validate Receiver (Pre-Transaction Check)

```
POST /api/v1/transactions/validate-receiver
Body: { receiver_identifier: "01XXXXXXXXX" }

Response (200):
{
    "valid": true,
    "receiver": {
        "id": 123,
        "full_name": "Ankon Dey",
        "mobile_last4": "5678",
        "is_active": true
    }
}

Response (404): Account not found
Response (422): Account inactive / frozen
```
> Frontend uses this to show: **"Sending to Ankon Dey · 01XX-XXXX-5678. Continue?"**

### 6.3 Request Money

```
POST /api/v1/requests/create
Body: {
    payer_identifier: "01XXXXXXXXX",
    amount: 1200.00,
    reason: "Lunch split",
    expires_in_hours: 48          -- default 48h
}

→ Creates money_requests record (status=pending)
→ Notifies payer: "Arif Hussain requested ৳1,200 from you. Reason: Lunch split"
→ Response: { request_id, reference_id, status: "pending", expires_at }
```

**Accept a Request:**
```
POST /api/v1/requests/{request_id}/accept
Body: { pin: "123456" }

→ Validates request is still pending + not expired
→ Checks payer is authenticated user
→ Runs full send_money flow (same atomic path above)
→ Updates money_request status = "accepted"
→ Notifies requester: "Ankon Dey paid your ৳1,200 request"
```

**Decline a Request:**
```
POST /api/v1/requests/{request_id}/decline

→ Updates status = "declined"
→ Notifies requester: "Ankon Dey declined your ৳1,200 request"
```

### 6.4 Split Bill

```
POST /api/v1/split/create
Body: {
    title: "Dinner at Radisson",
    total_amount: 6000.00,
    participants: [
        { mobile_number: "01XXXXXXXXX" },
        { mobile_number: "01YYYYYYYYY" }
    ],
    exclude_self: false    -- if false, creator's share included
}

→ Validates all participants exist and are active
→ Calculates per-person share: total / participant_count
→ Creates split_bills record
→ Creates individual money_requests for each participant
→ Each participant gets notification: "Arif created a split for 'Dinner at Radisson'. You owe ৳2,000"
→ Response: {
    split_id,
    per_person_amount: 2000.00,
    requests_created: [{ user_name, request_id, amount }]
}
```

---

## 7. Safety & Fraud Prevention

### 7.1 Rules Summary

| Rule | Implementation | Storage | Notes |
|---|---|---|---|
| Can't send to self | API validation | — | 422 error |
| Can't exceed balance | `SELECT FOR UPDATE` | MySQL | DB-level, not frontend |
| Account must be active | Pre-check | MySQL | Sender + receiver |
| PIN verify | bcrypt check | MySQL | Server-side only |
| PIN lockout (3 attempts) | Counter + lock | Redis | 15 min lock |
| 10-min cooldown (same pair) | TTL key | Redis | `cooldown:{s}:{r}` |
| Daily transfer limit | Counter | Redis | Resets at midnight |
| Per-tx max limit | Config constant | — | e.g. ৳25,000 |
| Velocity check | Rolling counter | Redis | 5+ txns in 10 min |
| Unusual amount | First-time flag | Redis | Extra confirm for >৳10k |
| Idempotency | UUID key check | Redis | 24h TTL |
| Account freeze | Admin action | MySQL | Blocks all tx |

### 7.2 Configuration Constants

```python
# config.py
MAX_SINGLE_TRANSFER_BDT = 25_000        # ৳25,000 per transaction
DAILY_TRANSFER_LIMIT_BDT = 100_000      # ৳1,00,000 per day
COOLDOWN_SECONDS = 600                  # 10 minutes between same pair
PIN_MAX_ATTEMPTS = 3
PIN_LOCK_SECONDS = 900                  # 15 minutes
VELOCITY_WINDOW_SECONDS = 600           # 10 minute window
VELOCITY_MAX_TRANSFERS = 5              # flag after 5 transfers
UNUSUAL_AMOUNT_THRESHOLD = 10_000       # ৳10,000 triggers extra confirm
OTP_EXPIRY_SECONDS = 300                # 5 minutes
STARTER_BALANCE_BDT = 100_000           # ৳1,00,000 on signup
```

### 7.3 Flagged Transactions

When a transaction is flagged (velocity exceeded or unusual amount on a new user):
- `transactions.flagged = TRUE`
- `transactions.flag_reason` = reason string
- Admin dashboard shows flagged queue
- Does **not** block the transaction — only marks for human review

---

## 8. Transaction History & Records

### 8.1 Get History

```
GET /api/v1/transactions/history

Query params:
    type        = sent | received | requested | all (default: all)
    status      = completed | pending | failed | disputed | all
    from_date   = YYYY-MM-DD
    to_date     = YYYY-MM-DD
    page        = 1
    per_page    = 20 (max 100)

Response:
{
    "transactions": [...],
    "pagination": {
        "total": 145,
        "page": 1,
        "per_page": 20,
        "total_pages": 8
    },
    "summary": {
        "total_sent": 45000.00,
        "total_received": 32000.00,
        "period": "2026-08"
    }
}
```

> **Note:** History queries hit the **Read Replica** in production design.

### 8.2 Transaction Detail

```
GET /api/v1/transactions/{reference_id}

Response:
{
    "reference_id": "uuid",
    "amount": 5000.00,
    "sender": { "name": "Arif Hussain", "mobile_last4": "1234" },
    "receiver": { "name": "Ankon Dey", "mobile_last4": "5678" },
    "note": "For dinner",
    "status": "completed",
    "initiated_via": "web",
    "created_at": "2026-08-29T10:30:00Z",
    "can_dispute": true    -- true for 7 days after completion
}
```

### 8.3 Immutable Audit Log

The `audit_log` table receives writes from Celery workers, never from the API directly. Events logged:

| Event Type | Trigger |
|---|---|
| `ACCOUNT_CREATED` | User registration |
| `LOGIN_SUCCESS` | Successful login |
| `LOGIN_FAILED` | Wrong password |
| `TRANSFER_INITIATED` | Send money started |
| `TRANSFER_COMPLETED` | DB commit succeeded |
| `TRANSFER_FAILED` | Any failure during transfer |
| `PIN_FAILED` | Wrong PIN entered |
| `PIN_LOCKED` | 3 failures reached |
| `ACCOUNT_FROZEN` | Admin froze account |
| `ACCOUNT_UNFROZEN` | Admin unfroze account |
| `DISPUTE_CREATED` | Support ticket opened |
| `REVERSAL_APPROVED` | Admin approved reversal |
| `REVERSAL_EXECUTED` | Reversal transaction completed |
| `VELOCITY_FLAGGED` | Velocity check triggered |
| `REQUEST_CREATED` | Money request sent |
| `REQUEST_ACCEPTED` | Money request paid |
| `REQUEST_DECLINED` | Money request declined |

### 8.4 Statement Export

```
GET /api/v1/transactions/export

Query params:
    format = csv | json
    from_date, to_date

→ Returns file download (Content-Disposition: attachment)
→ CSV includes: Date, Type, From/To, Amount, Note, Status, Reference ID
```

---

## 9. MCP + AI Agent

### 9.1 Architecture

> **🔴 CRITICAL SECURITY PRINCIPLE — The PIN Never Touches the LLM**
>
> The AI agent must **NEVER** receive, handle, transmit, or store the user's transaction PIN. DeepSeek (like all hosted LLM APIs) may log prompt content on their servers. Passing the PIN as a function argument means it appears in the prompt context window, which is a **third-party credential leak**. The fix: the agent stages a *draft* transaction and returns a `pending_pin` state. The React frontend then renders a **native secure PIN-pad** that is completely outside the LLM conversation. The PIN is typed directly into the frontend and sent straight to `/api/v1/transactions/confirm` — it never passes through DeepSeek.

```
User (React Chat UI)
        │
        │ POST /api/v1/agent/chat
        │ { message: "Send 5000 to Ankon", session_id }
        ▼
FastAPI Agent Endpoint
        │ Sends to DeepSeek API with system prompt +
        │ conversation history + available tools list
        ▼
DeepSeek LLM
        │ tool_call → { name: "validate_receiver", args: { identifier: "Ankon" } }
        ▼
FastAPI MCP Tool Dispatcher
        │ Routes read calls → db-mcp-server
        │ Routes write calls → FastAPI internal services
        ▼
db-mcp-server (read-only)       MySQL Database
        │                              │
        │ SELECT id, full_name...      │
        └──────────────────────────────┘
        │ Returns: { id: 45, full_name: "Ankon Dey", is_active: true }
        ▼
DeepSeek LLM (second call with tool result)
        │ tool_call → { name: "initiate_transfer",
        │               args: { receiver_id: 45, amount: 5000, note: "" } }
        ▼
FastAPI: initiate_transfer()
        │ • Runs all pre-checks (cooldown, daily limit, balance, account status)
        │ • Creates transaction_drafts record (status = 'pending_pin')
        │ • Returns draft_id (UUID) — PIN is NOT involved at all here
        ▼
DeepSeek LLM (third call)
        │ Returns: {
        │   "message": "Ready to send ৳5,000 to Ankon Dey.",
        │   "action": "pending_pin",        ← frontend reads this field
        │   "draft_id": "uuid-v4",
        │   "summary": { receiver: "Ankon Dey", amount: 5000 }
        │ }
        ▼
React Chat UI
        │ Detects action = "pending_pin"
        │ Renders NATIVE PIN-PAD MODAL (outside LLM context)
        │ User types PIN into modal
        ▼
POST /api/v1/transactions/confirm        ← PIN sent directly here, bypassing agent
        { draft_id: "uuid", pin: "123456" }
        │
        │ Validates draft exists + not expired + sender = current_user
        │ bcrypt verifies PIN server-side
        │ Executes full atomic transfer (SELECT FOR UPDATE, debit, credit)
        │ Marks draft as 'confirmed'
        ▼
Response: { status: "completed", reference_id, new_balance }
        ▼
React Chat UI — shows success in agent chat window
```

### 9.2 db-mcp-server Setup

```bash
# Clone and configure
git clone https://github.com/FreePeak/db-mcp-server
cd db-mcp-server

# Configure for MySQL
cp config.example.yaml config.yaml
```

```yaml
# config.yaml
database:
  type: mysql
  host: localhost
  port: 3306
  name: money_app
  user: mcp_reader               # READ-ONLY MySQL user
  password: "${DB_MCP_PASSWORD}"

server:
  port: 8001
  allowed_tables:               # Whitelist — only expose what agent needs
    - users
    - transactions
    - money_requests
    - notifications
  readonly: true                 # db-mcp-server in read-only mode
  max_rows: 100                  # prevent large dumps
```

> **CRITICAL SECURITY:** Create a dedicated `mcp_reader` MySQL user with SELECT-only grants on specific tables. The LLM agent should **NEVER** be able to write directly to the DB. All write operations go through FastAPI business logic with full validation.

```sql
-- Create read-only MCP user
CREATE USER 'mcp_reader'@'localhost' IDENTIFIED BY 'secure_password';
GRANT SELECT ON money_app.users TO 'mcp_reader'@'localhost';
GRANT SELECT ON money_app.transactions TO 'mcp_reader'@'localhost';
GRANT SELECT ON money_app.money_requests TO 'mcp_reader'@'localhost';
GRANT SELECT ON money_app.notifications TO 'mcp_reader'@'localhost';
FLUSH PRIVILEGES;
```

### 9.3 Agent Tools Definition

These are the tools exposed to DeepSeek. Some use db-mcp-server (read), others call FastAPI internal functions (write with validation).

```python
AGENT_TOOLS = [
    {
        "name": "validate_receiver",
        "description": "Look up a user by mobile number or name to confirm they exist before a transaction. Always call this before send_money.",
        "input_schema": {
            "type": "object",
            "properties": {
                "identifier": { "type": "string", "description": "Mobile number or full name of the recipient" }
            },
            "required": ["identifier"]
        }
        # → calls db-mcp-server: SELECT id, full_name, mobile_number, is_active, is_frozen FROM users WHERE mobile_number = ?
    },
    {
        "name": "get_balance",
        "description": "Get the current wallet balance of the authenticated user.",
        "input_schema": { "type": "object", "properties": {} }
        # → Redis cache first, then db-mcp-server query
    },
    {
        "name": "initiate_transfer",
        # ⚠️ SECURITY: This tool does NOT accept a PIN.
        # It stages a draft transaction and returns a pending_pin action.
        # The React frontend collects the PIN via a native modal and
        # calls /api/v1/transactions/confirm directly.
        # The PIN never enters the LLM context window — by design.
        "description": (
            "Stage a money transfer for PIN confirmation. Call validate_receiver first. "
            "This does NOT execute the transfer — it creates a pending draft. "
            "The frontend will show a PIN pad to the user. "
            "Never ask the user for their PIN in the chat."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "receiver_id": { "type": "integer", "description": "Receiver's user ID from validate_receiver" },
                "amount":      { "type": "number",  "description": "Amount in BDT, must be positive" },
                "note":        { "type": "string",  "description": "Optional memo for the transaction" }
            },
            "required": ["receiver_id", "amount"]
        }
        # → FastAPI runs: cooldown check, daily limit check, balance check, account status check
        # → Creates transaction_drafts record (status=pending_pin, expires in 5 min)
        # → Returns: { action: "pending_pin", draft_id: "uuid", summary: { receiver_name, amount } }
        # → Frontend detects action="pending_pin" and renders PIN modal
        # → User enters PIN in modal → POST /api/v1/transactions/confirm { draft_id, pin }
    },
    {
        "name": "request_money",
        "description": "Send a money request to another user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "payer_id": { "type": "integer" },
                "amount": { "type": "number" },
                "reason": { "type": "string" }
            },
            "required": ["payer_id", "amount"]
        }
    },
    {
        "name": "get_transaction_history",
        "description": "Retrieve the user's transaction history for a given period.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": { "type": "string", "enum": ["last_7_days", "last_30_days", "this_month", "last_month"] },
                "type": { "type": "string", "enum": ["all", "sent", "received"] }
            }
        }
        # → db-mcp-server read on transactions table, filtered by user_id + date range
    },
    {
        "name": "get_spending_summary",
        "description": "Get a spending summary and generate a chart for a given month.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month": { "type": "string", "description": "YYYY-MM format, e.g. '2026-08'" }
            },
            "required": ["month"]
        }
        # → db-mcp-server aggregation query + matplotlib chart generation
        # → Returns: { summary_text, chart_base64, total_sent, total_received }
    },
    {
        "name": "get_pending_requests",
        "description": "Get all pending money requests for the user (both sent and received).",
        "input_schema": { "type": "object", "properties": {} }
    }
]
```

### 9.4 Agent System Prompt

```
You are a helpful and secure financial assistant for the MoneyMove app.
You help users send money, check balances, view history, and manage requests.

STRICT SECURITY RULES — NEVER VIOLATE THESE:
1. ALWAYS call validate_receiver before initiate_transfer. Never skip this step.
2. NEVER ask the user for their PIN in the chat. Never. Under any circumstances.
   The PIN is collected by a secure frontend modal — it is not your responsibility.
3. NEVER mention the PIN in your messages except to say "please enter your PIN in the secure prompt."
4. If a user types their PIN into the chat, respond: "Please do not share your PIN in chat.
   For security, always enter your PIN only in the secure PIN prompt that appears on screen."
5. NEVER display full mobile numbers. Show only last 4 digits (e.g. "****5678").
6. For any transfer above ৳10,000, explicitly confirm the amount and receiver with the user
   before calling initiate_transfer.
7. If uncertain about the user's intent, ask for clarification. Never assume.
8. After calling initiate_transfer successfully, tell the user:
   "I've prepared the transfer of ৳{amount} to {receiver_name}.
    Please enter your PIN in the secure prompt to confirm."
   Do not say anything else about the PIN.
9. NEVER execute or suggest bypassing the PIN confirmation step.
10. You are a READ-ONLY agent for all data queries. Only initiate_transfer triggers a write,
    and even that write is incomplete until the user confirms via PIN on the frontend.

Current authenticated user: {user_id} | {user_name}
Current balance: ৳{balance} (always fetch fresh via get_balance — never use a cached value)
```

### 9.5 Graph Generation

```python
# Called when get_spending_summary tool is invoked
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')   # non-interactive backend
import io, base64

def generate_spending_chart(monthly_data: dict) -> str:
    """
    monthly_data: { "2026-01": 12000, "2026-02": 8500, ... }
    Returns base64 PNG string
    """
    fig, ax = plt.subplots(figsize=(8, 4))
    months = list(monthly_data.keys())
    amounts = list(monthly_data.values())

    bars = ax.bar(months, amounts, color='#4F46E5', alpha=0.8)
    ax.set_title("Monthly Spending (BDT)", fontsize=14, fontweight='bold')
    ax.set_ylabel("Amount (৳)")
    ax.set_xlabel("Month")

    for bar, amount in zip(bars, amounts):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 100,
                f'৳{amount:,.0f}', ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=120, bbox_inches='tight')
    plt.close(fig)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode('utf-8')
```

---

## 10. Support System (RAG + Human)

### 10.1 RAG Chatbot

**PDF Indexing Pipeline (Admin uploads):**

```python
# Called when admin uploads a PDF via /api/v1/admin/support-docs/upload
from langchain_community.document_loaders import PyMuPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
import chromadb
from chromadb.utils import embedding_functions

async def index_pdf(file_path: str, filename: str, admin_id: int):
    # 1. Load PDF
    loader = PyMuPDFLoader(file_path)
    documents = loader.load()

    # 2. Chunk text
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", ".", "?", "!"]
    )
    chunks = splitter.split_documents(documents)

    # 3. Embed and store in ChromaDB
    client = chromadb.PersistentClient(path="./chroma_db")
    collection = client.get_or_create_collection(
        name="support_docs",
        embedding_function=embedding_functions.DefaultEmbeddingFunction()
        # or use DeepSeek embeddings if available
    )

    texts = [chunk.page_content for chunk in chunks]
    ids = [f"{filename}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": filename, "page": chunk.metadata.get("page", 0)} for chunk in chunks]

    collection.add(documents=texts, ids=ids, metadatas=metadatas)

    # 4. Update rag_documents table
    await db.execute(
        "UPDATE rag_documents SET chunk_count=:n, indexed_at=NOW() WHERE filename=:f",
        {"n": len(chunks), "f": filename}
    )
    return len(chunks)
```

**RAG Query Flow:**

```
POST /api/v1/support/chat
Body: { message: "How do I reset my PIN?", session_id }

→ Embed user query using same embedding model
→ ChromaDB similarity search: top 5 relevant chunks
→ Build prompt:

  System: You are a customer support assistant for MoneyMove app.
          Answer using ONLY the provided context. 
          If the context doesn't answer the question, say: 
          "I don't have information on that. Would you like to speak with a human agent?"

  Context: [top 5 retrieved chunks]

  User: How do I reset my PIN?

→ Call DeepSeek API with above prompt
→ Parse response
→ If response contains "speak with a human": set needs_human=true in response
→ Response: {
    answer: "To reset your PIN, go to Profile → Security → Reset PIN...",
    sources: ["faq.pdf", "security-guide.pdf"],
    confidence: "high",
    needs_human: false
  }
```

**Confidence Detection:**

```python
LOW_CONFIDENCE_PHRASES = [
    "I don't have information",
    "I'm not sure",
    "I cannot find",
    "please contact support",
    "I don't know"
]

def detect_confidence(response_text: str) -> str:
    if any(phrase.lower() in response_text.lower() for phrase in LOW_CONFIDENCE_PHRASES):
        return "low"
    return "high"
```

### 10.2 Wrong Transfer — Dispute System

**Create Dispute:**

```
POST /api/v1/support/dispute
Headers: Authorization: Bearer <JWT>
Body: {
    transaction_reference_id: "uuid-of-transaction",
    category: "wrong_transfer",
    description: "I accidentally sent ৳5,000 to the wrong person. "
                 "I meant to send to 01XXXXX but sent to 01YYYYY."
}

Validations:
→ Transaction must exist and sender must be the authenticated user
→ Transaction must be in status='completed'
→ Dispute must be filed within 7 days of transaction
→ No existing open dispute for same transaction

→ Creates support_ticket (status=open)
→ Sets transactions.status = 'disputed'
→ Notifies admin team
→ Response: { ticket_id, reference_id, message: "Dispute filed. Expected response: 24-48 hours" }
```

**Ticket Message Thread:**

```
POST /api/v1/support/tickets/{ticket_id}/messages
Body: { message: "Any update on my dispute?" }

→ Adds to ticket_messages
→ Notifies assigned support agent
→ Response: { message_id, created_at }

GET /api/v1/support/tickets/{ticket_id}/messages
→ Returns full conversation thread
```

**Get My Tickets:**

```
GET /api/v1/support/tickets
Query: status = open | under_review | resolved | all

Response: [
    {
        "ticket_id": 1,
        "reference_id": "uuid",
        "category": "wrong_transfer",
        "subject": "Wrong Transfer Dispute",
        "status": "under_review",
        "transaction": { reference_id, amount, receiver_name },
        "created_at": "...",
        "last_updated": "...",
        "unread_messages": 1
    }
]
```

**Admin: Approve Reversal:**

```
POST /api/v1/admin/tickets/{ticket_id}/resolve
Body: {
    decision: "approved",           -- or "rejected"
    resolution_note: "Verified wrong transfer. Reversing ৳5,000.",
    execute_reversal: true          -- triggers reversal transaction
}

If approved + execute_reversal:
→ Creates REVERSAL transaction (from original receiver back to original sender)
→ Full atomic transaction: SELECT FOR UPDATE, debit, credit
→ Updates support_ticket: status=resolved, reversal_approved=true, reversal_tx_id
→ Updates original transaction: status stays 'disputed' (for audit trail)
→ Notifies both parties
→ Writes REVERSAL_EXECUTED to audit_log

If rejected:
→ support_ticket: status=rejected, reversal_approved=false
→ Original transaction: status back to 'completed'
→ Notifies user with reason
```

---

## 11. Notifications

### 11.1 Notification Events

| Event | Recipient | Message |
|---|---|---|
| money_received | Receiver | "You received ৳{amount} from {sender_name}" |
| money_sent | Sender | "৳{amount} sent to {receiver_name} successfully" |
| request_received | Payer | "{requester_name} requested ৳{amount} from you. Reason: {reason}" |
| request_accepted | Requester | "{payer_name} paid your ৳{amount} request" |
| request_declined | Requester | "{payer_name} declined your ৳{amount} request" |
| request_expired | Requester | "Your ৳{amount} request to {payer_name} has expired" |
| account_frozen | User | "Your account has been temporarily frozen. Contact support." |
| ticket_update | User | "Your support ticket #{id} has been updated: {status}" |
| security_alert | User | "Failed PIN attempt detected on your account" |
| reversal_completed | Both parties | "Transaction reversal of ৳{amount} has been processed" |

### 11.2 Delivery

```
GET /api/v1/notifications
Query: unread_only=true, page=1, per_page=20

POST /api/v1/notifications/mark-read
Body: { notification_ids: [1, 2, 3] }   -- or all_read: true

Response: { unread_count: 5, notifications: [...] }
```

---

## 12. User Experience Features

### 12.1 Saved Beneficiaries

```
POST /api/v1/beneficiaries
Body: { user_id: 45, nickname: "Ankon Bhai" }

GET /api/v1/beneficiaries
→ Returns list with: id, full_name, mobile_last4, nickname, last_transacted_at

DELETE /api/v1/beneficiaries/{beneficiary_id}
```

### 12.2 User Search

```
GET /api/v1/users/search?q=Ankon
→ Search by name or mobile number (partial match)
→ Returns: [ { id, full_name, mobile_last4, is_active } ]
→ Never return full mobile number to searching user
→ Rate limited: max 20 searches per minute (Redis)
```

### 12.3 QR Code

- Generated on registration using `qrcode` Python library
- Encodes: `moneymove://pay?user_id={id}&mobile={mobile_last4}`
- Stored as base64 in `users.qr_code`
- Endpoint: `GET /api/v1/users/me/qr` → returns base64 PNG

### 12.4 Dashboard Summary

```
GET /api/v1/dashboard

Response:
{
    "balance": 87500.00,
    "this_month": {
        "total_sent": 12500.00,
        "total_received": 8000.00,
        "transactions_count": 14
    },
    "recent_transactions": [...],   -- last 5
    "pending_requests": {
        "incoming": 2,
        "outgoing": 1
    },
    "unread_notifications": 3,
    "saved_beneficiaries": [...]    -- top 4
}
```

---

## 13. Admin Dashboard

### 13.1 Access Control

```python
# Middleware
def require_admin(current_user):
    if current_user.role not in ('admin', 'support'):
        raise HTTP403("Admin access required")

def require_super_admin(current_user):
    if current_user.role != 'admin':
        raise HTTP403("Super admin access required")
```

### 13.2 Admin Endpoints

**System Overview Dashboard:**
```
GET /api/v1/admin/dashboard

Response:
{
    "totals": {
        "registered_users": 1250,
        "active_users_today": 340,
        "transactions_today": 890,
        "transaction_volume_today": 4250000.00,
        "pending_tickets": 12,
        "flagged_transactions": 3,
        "frozen_accounts": 2
    },
    "hourly_volume": [...],     -- chart data: last 24h
    "recent_flags": [...]
}
```

**User Management:**
```
GET /api/v1/admin/users
Query: search, is_frozen, is_active, page, per_page

GET /api/v1/admin/users/{user_id}
→ Full user profile including:
  - NID last 4 digits
  - Full transaction history
  - Login history
  - Any open tickets
  - Total lifetime volume

POST /api/v1/admin/users/{user_id}/freeze
Body: { reason: "Suspicious velocity detected" }
→ Sets is_frozen=true, frozen_reason, frozen_at, frozen_by
→ Revokes all active JWT sessions for that user
→ Notifies user
→ Writes ACCOUNT_FROZEN to audit_log

POST /api/v1/admin/users/{user_id}/unfreeze
Body: { reason: "Investigation complete, cleared" }
→ Sets is_frozen=false
→ Notifies user
→ Writes ACCOUNT_UNFROZEN to audit_log
```

**Transaction Management:**
```
GET /api/v1/admin/transactions
Query: status, flagged=true, from_date, to_date, user_id, min_amount, page

GET /api/v1/admin/transactions/{reference_id}
→ Full transaction detail + audit trail events for this transaction

POST /api/v1/admin/transactions/{reference_id}/flag
Body: { reason: "Manual review: suspicious pattern" }
```

**Support Ticket Queue:**
```
GET /api/v1/admin/tickets
Query: status=open, category, assigned_to=me, page

Response: [tickets sorted by created_at ASC (oldest first)]

POST /api/v1/admin/tickets/{ticket_id}/assign
Body: { agent_id: 5 }

POST /api/v1/admin/tickets/{ticket_id}/message
Body: { message: "We're reviewing your case. Please allow 24 hours." }

POST /api/v1/admin/tickets/{ticket_id}/resolve
Body: {
    decision: "approved" | "rejected",
    resolution_note: "...",
    execute_reversal: true | false
}
```

**RAG Document Management:**
```
POST /api/v1/admin/support-docs/upload
Content-Type: multipart/form-data
Body: file (PDF)
→ Saves to disk at /data/rag_docs/{filename}
→ Creates rag_documents record
→ Triggers Celery task: index_pdf.delay(file_path, filename, admin_id)
→ Response: { document_id, status: "indexing", chunk_count: null }

GET /api/v1/admin/support-docs
→ List all uploaded PDFs with indexing status and chunk counts

DELETE /api/v1/admin/support-docs/{document_id}
→ Removes from ChromaDB collection (by source metadata)
→ Deletes file from disk
→ Removes from rag_documents table
```

**Audit Log Viewer:**
```
GET /api/v1/admin/audit-log
Query: event_type, actor_id, from_date, to_date, page

→ Read-only view of audit_log table
→ No mutations possible here — append-only by design
```

**Flagged Accounts Review:**
```
GET /api/v1/admin/flagged
→ Users with recent flagged transactions
→ Summary: flag count, flag reasons, total volume

→ Quick actions: Freeze / Clear Flag / View History
```

---

## 14. API Endpoints Reference

### Auth
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/auth/send-otp` | Send OTP to mobile |
| POST | `/api/v1/auth/verify-otp` | Verify OTP, get temp token |
| POST | `/api/v1/auth/register` | Complete registration |
| POST | `/api/v1/auth/login` | Login with password |
| POST | `/api/v1/auth/logout` | Revoke JWT |
| POST | `/api/v1/auth/refresh` | Refresh access token |

### User
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/users/me` | Get own profile + balance |
| GET | `/api/v1/users/me/qr` | Get own QR code |
| GET | `/api/v1/users/search` | Search users |
| PUT | `/api/v1/users/me/pin` | Change transaction PIN |

### Transactions
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/transactions/validate-receiver` | Verify receiver before send |
| POST | `/api/v1/transactions/send` | Send money |
| GET | `/api/v1/transactions/history` | Get transaction history |
| GET | `/api/v1/transactions/{ref_id}` | Get transaction detail |
| GET | `/api/v1/transactions/export` | Download CSV/JSON |

### Requests
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/requests/create` | Create money request |
| GET | `/api/v1/requests` | List all requests (sent+received) |
| POST | `/api/v1/requests/{id}/accept` | Accept + pay request |
| POST | `/api/v1/requests/{id}/decline` | Decline request |

### Split
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/split/create` | Create split bill |
| GET | `/api/v1/split/{id}` | Get split detail + status |

### Dashboard
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/dashboard` | Full dashboard data |

### Beneficiaries
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/beneficiaries` | List saved beneficiaries |
| POST | `/api/v1/beneficiaries` | Add beneficiary |
| DELETE | `/api/v1/beneficiaries/{id}` | Remove beneficiary |

### Notifications
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/notifications` | Get notifications |
| POST | `/api/v1/notifications/mark-read` | Mark as read |

### Support
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/support/chat` | RAG chatbot query |
| POST | `/api/v1/support/dispute` | File wrong-transfer dispute |
| GET | `/api/v1/support/tickets` | My tickets |
| GET | `/api/v1/support/tickets/{id}` | Ticket detail |
| POST | `/api/v1/support/tickets/{id}/messages` | Add message to ticket |

### Transactions (continued)
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/transactions/confirm` | Execute agent-staged draft transfer with PIN |
| DELETE | `/api/v1/transactions/drafts/{draft_id}` | Cancel a pending agent draft |

> **`/api/v1/transactions/confirm` — Full spec:**
> ```
> POST /api/v1/transactions/confirm
> Headers: Authorization: Bearer <JWT>
> Body: { draft_id: "uuid-v4", pin: "123456" }
>
> → Fetch draft from transaction_drafts by draft_id
> → Validate: draft.sender_id == current_user.id
> → Validate: draft.status == 'pending_pin'
> → Validate: draft.expires_at > NOW()  (5-minute window)
> → bcrypt verify PIN (with lockout checks — same as regular transfer)
> → Execute full atomic transfer (SELECT FOR UPDATE, debit, credit, INSERT transaction)
> → Mark draft status = 'confirmed'
> → Return: { status: "completed", reference_id, new_balance }
> ```
> The PIN is verified here on the FastAPI server. It never passes through DeepSeek.

### AI Agent
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/agent/chat` | Send message to AI agent |
| GET | `/api/v1/agent/history/{session_id}` | Get agent chat history |

### Admin
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/admin/dashboard` | System overview |
| GET | `/api/v1/admin/users` | All users |
| GET | `/api/v1/admin/users/{id}` | User detail |
| POST | `/api/v1/admin/users/{id}/freeze` | Freeze account |
| POST | `/api/v1/admin/users/{id}/unfreeze` | Unfreeze account |
| GET | `/api/v1/admin/transactions` | All transactions |
| GET | `/api/v1/admin/flagged` | Flagged accounts |
| GET | `/api/v1/admin/tickets` | All support tickets |
| POST | `/api/v1/admin/tickets/{id}/assign` | Assign ticket |
| POST | `/api/v1/admin/tickets/{id}/message` | Reply to ticket |
| POST | `/api/v1/admin/tickets/{id}/resolve` | Resolve + optional reversal |
| GET | `/api/v1/admin/audit-log` | Audit log viewer |
| POST | `/api/v1/admin/support-docs/upload` | Upload RAG PDF |
| GET | `/api/v1/admin/support-docs` | List RAG docs |
| DELETE | `/api/v1/admin/support-docs/{id}` | Remove RAG doc |

---

## 15. Redis Key Design

```
# Authentication
jwt:blocklist:{jti}                   TTL = JWT remaining lifetime
otp:{mobile}:{purpose}                TTL = 300s (5 min)

# PIN Security
pin:attempts:{user_id}                TTL = 900s, value = count (1-3)
pin:locked:{user_id}                  TTL = 900s, value = 1

# Transfer Controls
cooldown:{sender_id}:{receiver_id}    TTL = 600s (10 min)
daily_sent:{user_id}:{YYYY-MM-DD}     TTL = expireat(midnight), value = paisa (int)
velocity:{user_id}                    TTL = 600s, value = tx count
first_large:{user_id}                 TTL = 7d, value = 1 (set after first >10k)

# Idempotency
idem:{user_id}:{idempotency_key}      TTL = 86400s (24h), value = JSON response

# Cache
balance:{user_id}                     TTL = 60s, value = float (invalidate on tx)
user:search:rate:{user_id}            TTL = 60s, value = count (max 20)

# Agent Transaction Drafts
agent:draft:{draft_id}                TTL = 300s (5 min), value = JSON draft snapshot
                                      # Mirrors transaction_drafts table for fast lookup.
                                      # Both Redis + DB checked; DB is source of truth.

# Celery Broker
celery                                (default Celery Redis broker keys)
```

> **⚠️ Redis Single Point of Failure — Acknowledged Trade-off**
>
> Redis is used for business-critical state: daily limits, cooldowns, velocity counters. If Redis crashes, these guardrails temporarily fail open (a user could bypass their daily limit until Redis recovers). This is a deliberate trade-off: the alternative — querying MySQL for every `SUM()` on every transaction at 10M users — causes catastrophic write lock contention.
>
> **Production mitigation strategy:**
> - Deploy Redis Sentinel (HA) or Redis Cluster with replicas
> - Run a **nightly batch reconciliation job**: compare Redis daily counters against `SUM(amount)` from the `transactions` table for that day. Alert on discrepancies > ৳1,000. This catches any drift caused by Redis downtime.
> - Add DB-level `CHECK` constraint as a hard floor: `CONSTRAINT chk_balance CHECK (balance >= 0)`. This prevents overdraft even if all Redis checks fail.
> - Consider writing daily limit as a shadow column in MySQL (`users.daily_sent_today`, reset by a cron), used only as fallback when Redis is unreachable.

---

## 16. Security Considerations

### Passwords & PINs
- Passwords: bcrypt with cost factor 12
- PINs: bcrypt with cost factor 10 (faster for frequent verification)
- NID: SHA-256 hash stored, raw NID never persisted
- Never log passwords, PINs, or raw NID

### API Security
- All endpoints require HTTPS
- JWT tokens in Authorization header (never in query params or cookies)
- CORS configured to allow only frontend origin
- Rate limiting on all public endpoints (Redis-backed)
- Input validation on all request bodies (Pydantic models)
- SQL injection prevention via SQLAlchemy parameterized queries
- MCP server uses read-only DB user — no write access from agent

### AI Agent Security (Principle of Least Privilege)
- The AI agent (DeepSeek) connects via a **read-only** `mcp_reader` MySQL user with `SELECT`-only grants on 4 whitelisted tables. It cannot INSERT, UPDATE, or DELETE anything.
- The agent tool `initiate_transfer` **does not accept a PIN argument**. The PIN is collected by the React frontend's native PIN-pad modal and sent directly to `/api/v1/transactions/confirm`. The PIN never appears in the LLM prompt context window, never traverses the DeepSeek API, and is never logged by a third party.
- Agent chat history is stored in FastAPI memory (per session) and never persisted to DB. Sensitive tool results (account balances, transaction details) are not stored beyond the session.
- If the user types their PIN into the chat window, the agent is instructed to warn them and NOT process it.
- `transaction_drafts` expire in 5 minutes. Any unconfirmed draft is automatically voided — no money moves until the human explicitly enters their PIN.

### Financial Safety
- All balance operations inside `BEGIN ... COMMIT` transactions
- `SELECT ... FOR UPDATE` used on sender row before every debit
- Idempotency keys prevent double-debits on retries
- `CHECK (balance >= 0)` constraint at DB level — last-resort safety net even if application logic fails
- Audit log is append-only (enforced at DB user permission level)
- `transaction_drafts` are never executed automatically — always require explicit PIN confirmation from the authenticated user

### Data Privacy
- Full NID never stored — only SHA-256 hash and last 4 digits
- Full mobile numbers never returned in search results — last 4 digits only
- Agent never displays full account numbers in responses
- Admin access to full mobile only in individual user profile view

---

## 17. Environment Variables

```env
# Application
APP_NAME=MoneyMove
APP_ENV=development
SECRET_KEY=your-super-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440     # 24 hours
REFRESH_TOKEN_EXPIRE_DAYS=30

# Database
DATABASE_URL=mysql+aiomysql://root:password@localhost:3306/money_app
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10

# Redis
REDIS_URL=redis://localhost:6379/0

# DeepSeek API
DEEPSEEK_API_KEY=your-deepseek-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_MAX_TOKENS=1000

# db-mcp-server
MCP_SERVER_URL=http://localhost:8001
DB_MCP_PASSWORD=mcp-reader-password

# ChromaDB
CHROMA_PERSIST_PATH=./chroma_db
CHROMA_COLLECTION=support_docs

# RAG Documents
RAG_DOCS_PATH=./data/rag_docs

# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# Business Rules
MAX_SINGLE_TRANSFER_BDT=25000
DAILY_TRANSFER_LIMIT_BDT=100000
COOLDOWN_SECONDS=600
PIN_MAX_ATTEMPTS=3
PIN_LOCK_SECONDS=900
VELOCITY_MAX_TRANSFERS=5
VELOCITY_WINDOW_SECONDS=600
UNUSUAL_AMOUNT_THRESHOLD=10000
STARTER_BALANCE_BDT=100000
DISPUTE_WINDOW_DAYS=7
```

---

## 18. Project Structure

```
money-move/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app init, middleware, routers
│   │   ├── config.py                  # Settings from env vars (pydantic-settings)
│   │   ├── database.py                # SQLAlchemy async engine + session
│   │   ├── redis_client.py            # Redis connection pool
│   │   │
│   │   ├── models/                    # SQLAlchemy ORM models
│   │   │   ├── user.py
│   │   │   ├── transaction.py
│   │   │   ├── money_request.py
│   │   │   ├── split_bill.py
│   │   │   ├── audit_log.py
│   │   │   ├── notification.py
│   │   │   ├── support_ticket.py
│   │   │   └── rag_document.py
│   │   │
│   │   ├── schemas/                   # Pydantic request/response schemas
│   │   │   ├── auth.py
│   │   │   ├── transaction.py
│   │   │   ├── support.py
│   │   │   └── admin.py
│   │   │
│   │   ├── routers/                   # FastAPI route handlers
│   │   │   ├── auth.py
│   │   │   ├── users.py
│   │   │   ├── transactions.py
│   │   │   ├── requests.py
│   │   │   ├── split.py
│   │   │   ├── dashboard.py
│   │   │   ├── notifications.py
│   │   │   ├── support.py
│   │   │   ├── agent.py
│   │   │   └── admin.py
│   │   │
│   │   ├── services/                  # Business logic
│   │   │   ├── auth_service.py        # OTP, JWT, PIN logic
│   │   │   ├── transfer_service.py    # Core transfer with all safety checks
│   │   │   ├── request_service.py     # Money request logic
│   │   │   ├── fraud_service.py       # Velocity, flags, checks
│   │   │   ├── agent_service.py       # MCP + DeepSeek orchestration
│   │   │   ├── rag_service.py         # ChromaDB + LangChain RAG
│   │   │   ├── chart_service.py       # matplotlib graph generation
│   │   │   └── notification_service.py
│   │   │
│   │   ├── tasks/                     # Celery tasks
│   │   │   ├── celery_app.py
│   │   │   ├── notification_tasks.py
│   │   │   ├── audit_tasks.py
│   │   │   └── rag_tasks.py
│   │   │
│   │   └── middleware/
│   │       ├── auth_middleware.py     # JWT validation
│   │       └── rate_limit.py          # Redis-backed rate limiter
│   │
│   ├── alembic/                       # DB migrations
│   ├── data/
│   │   └── rag_docs/                  # Uploaded support PDFs
│   ├── chroma_db/                     # ChromaDB persistent storage
│   ├── requirements.txt
│   └── .env
│
├── db-mcp-server/                     # git submodule or clone
│   └── config.yaml
│
├── frontend/                          # React (Vite)
│   └── ...                            # Separate spec in frontend.md
│
└── spec.md                            # This file
```

---

## 19. Build Priority for Hackathon

Given 9:00 AM – 3:00 PM (6 hours):

```
⏰ 09:00 – 09:30 (30 min)
  P0: Project setup, DB creation, Alembic migrations, FastAPI skeleton

⏰ 09:30 – 10:30 (60 min)
  P0: Auth — OTP flow, Register (NID + PIN), Login, JWT middleware

⏰ 10:30 – 11:30 (60 min)
  P0: Send Money — full atomic flow with all Redis checks
      Validate Receiver endpoint
      Transaction History

⏰ 11:30 – 12:15 (45 min)
  P1: Request Money — create, accept, decline
      Dashboard endpoint

⏰ 12:15 – 12:45 (30 min)
  P1: Wrong Transfer Dispute button + ticket creation
      Admin: Ticket queue + reply + resolve

⏰ 12:45 – 13:30 (45 min)
  P1: Admin Dashboard — stats, freeze/unfreeze, flagged queue
      Notifications endpoint

⏰ 13:30 – 14:15 (45 min)
  P2: MCP + AI Agent — DeepSeek integration, tool dispatcher
      db-mcp-server configured and running

⏰ 14:15 – 14:45 (30 min)
  P2: RAG Support Chatbot — PDF indexing + query endpoint
      Admin: PDF upload

⏰ 14:45 – 15:00 (15 min)
  P3: Final polish, demo prep, architecture slide
```

### Features To Skip If Time Is Short
- Split Bill (nice-to-have, core flow is Send + Request)
- Saved Beneficiaries (can show manually)
- QR Code (impressive but not core)
- Graph generation (mention it in demo, show the endpoint)
- Scheduled transfer (skip entirely)

### Demo Script (for judges)
1. Register with mobile → OTP → NID → PIN setup
2. Show ৳1,00,000 balance auto-credited
3. Send ৳5,000 → receiver name confirmation → PIN verify → transaction complete
4. Show cooldown: try sending again immediately → blocked
5. Request money flow → accept with PIN
6. Try PIN wrong 3 times → show lockout
7. AI Agent: "Send 2000 to Ankon" → agent validates receiver → agent stages draft → frontend PIN modal appears → user enters PIN in modal (not in chat) → executed
8. AI Agent: "Show my spending last month" → graph
9. Wrong Transfer button → dispute filed → admin panel → resolve with reversal
10. RAG chatbot: "How do I reset my PIN?" → instant answer from PDF

---

---

## 20. Engineering Defense Guide — Judge Q&A

*Reviewed and validated by a 10-expert panel. Use these answers verbatim.*

---

### 🏛️ System Design Questions

**Q: Why did you use `DECIMAL(15,2)` for money instead of `FLOAT` or `DOUBLE`?**

> "Floating-point types like `FLOAT` and `DOUBLE` cannot represent most decimal fractions exactly in binary. `0.1 + 0.2` in a float gives `0.30000000000000004`. In a financial system, that rounding error accumulates across millions of transactions and creates real discrepancies. `DECIMAL(15,2)` is an exact numeric type — MySQL stores it as an integer internally. We also store Redis daily limits in **paisa** (integer), not taka, for the same reason: no float arithmetic anywhere in the money path."

---

**Q: Why pessimistic locking (`SELECT FOR UPDATE`) instead of optimistic locking?**

> "In a financial system, the cost of a failed optimistic lock is a **retry**, which means a bad user experience — 'your transfer failed, please try again.' Pessimistic locking serializes concurrent writes on the sender row, guaranteeing the transaction succeeds on the first attempt. The throughput cost is acceptable because transfers are infrequent per-user (not millisecond-level), and the correctness guarantee is non-negotiable. For a read-heavy workload I'd use optimistic locking; for a write-critical path like money movement, pessimistic is correct."

---

**Q: Why Redis for daily limits and cooldowns instead of the database?**

> "At 10 million users, running a `SELECT SUM(amount) FROM transactions WHERE sender_id = X AND created_at >= TODAY` before every transfer causes massive read lock contention on the transactions table. Redis gives us O(1) `INCRBY` and `GET` operations with TTL-based auto-expiry — the daily counter key literally disappears at midnight. We accept the trade-off that Redis is a single point of failure for these guardrails. Our production mitigation is: Redis Sentinel for HA, a nightly batch reconciliation job to compare Redis counters against DB `SUM()` and alert on drift, and a DB-level `CHECK (balance >= 0)` constraint as an absolute last-resort floor."

---

**Q: Your balance is a single column on the users table. How does that scale to 10 million users?**

> "You're right — that's a deliberate hackathon simplification. The production architecture would migrate to a **double-entry ledger model**: an append-only `ledger_entries` table with `debit` and `credit` columns per transaction leg, where balance = `SUM(credit) - SUM(debit)`. A materialized view or periodic balance snapshot prevents expensive full-history aggregation on every read. This design also gives you an immutable financial audit trail by construction. For the hackathon, row-level locking on the balance column gives us correctness without the complexity overhead."

---

### 🛡️ Security Questions

**Q: How did you secure the AI agent?**

> "We implemented the Principle of Least Privilege at two levels. First, the AI agent connects to MySQL via a dedicated `mcp_reader` user with `SELECT`-only grants on four whitelisted tables. It cannot INSERT, UPDATE, or DELETE anything. Second — and this is the critical one — the agent never handles the user's transaction PIN. The PIN is a credential. Passing it through a hosted LLM's API means it appears in the prompt context window, which the provider may log. Our fix: the agent calls `initiate_transfer` which stages a draft and returns a `pending_pin` state. The React frontend renders a native PIN-pad modal. The user enters their PIN directly into the frontend, which calls `/api/v1/transactions/confirm` — the PIN bypasses DeepSeek entirely and is verified server-side via bcrypt."

---

**Q: What prevents the AI agent from executing a transfer the user didn't authorize?**

> "Three things. One: the agent can only call `initiate_transfer`, which creates a `transaction_draft` record with `status = 'pending_pin'` and a 5-minute expiry. No money moves at this stage. Two: the draft requires an explicit PIN confirmation from the authenticated user via a separate API endpoint — the frontend modal collects this. Three: the `/api/v1/transactions/confirm` endpoint validates that `draft.sender_id == current_user.id`, so a draft created for user A can only be confirmed by user A's authenticated session."

---

**Q: What if an attacker replays a transaction request?**

> "We have two defenses. First, the client generates a `idempotency_key` (UUID v4) per transfer attempt. The server checks `idem:{user_id}:{key}` in Redis before processing. If the key exists, we return the cached original response — no second execution. The key has a 24-hour TTL. Second, JWTs are short-lived (24h) and tied to a `jti` (JWT ID). Logout adds the `jti` to a Redis blocklist for its remaining lifetime. Replaying a stolen token after logout fails at the middleware level."

---

**Q: Why did you hash the NID with SHA-256 instead of bcrypt?**

> "NID numbers are not secrets that users choose — they're deterministic government-issued identifiers. bcrypt adds random salt to prevent rainbow table attacks on **user-chosen** secrets where common passwords cluster. For NIDs, the goal is deduplication detection (one NID = one account) with a consistent hash. SHA-256 gives us a consistent fingerprint for comparison without storing the raw value. If we were storing NIDs in a regulatory context where they need to be decrypted, we'd use AES-256 encryption with a key management service instead."

---

### 🌐 Resilience Questions

**Q: What happens if Redis goes down during a transaction?**

> "The critical path — the MySQL atomic transaction with `SELECT FOR UPDATE` — does not depend on Redis. It will succeed or fail based solely on the DB state. The Redis checks (cooldown, daily limit, velocity) are guardrails that run **before** the DB transaction. If Redis is unavailable, our application falls back to allowing the transfer to proceed — we accept this as a trade-off between availability and strict enforcement. The DB-level `CHECK (balance >= 0)` constraint remains as an absolute safety floor. In production we'd deploy Redis Sentinel and add a circuit breaker that falls back to DB-level checks when Redis is unreachable."

---

**Q: What if two users send from the same account simultaneously?**

> "Exactly what `SELECT ... FOR UPDATE` handles. Both requests reach the MySQL server simultaneously. MySQL's InnoDB engine grants the row lock to one request and blocks the second until the first transaction commits. The first request deducts from the confirmed balance. When the lock releases, the second request reads the updated balance. If the second request's amount exceeds the new balance, it fails with 'Insufficient funds' — correctly. No double-spend is possible. We verified this design using the InnoDB documentation on row-level locking semantics."

---

### 📱 Product Questions

**Q: Why build a dispute system instead of automatic reversal?**

> "Automatic reversal assumes the receiver hasn't already spent the money. If User A sends to User B and B immediately sends it somewhere else, automatic reversal from B's account could overdraft it. Real financial systems handle this with a **dispute-and-review** model: a human agent reviews the claim, confirms the receiver still has the funds, and manually executes a reversal. This is how bKash, Nagad, and all real banks operate. Our admin panel gives the support agent the full transaction audit trail and a one-click reversal that executes as a new atomic transaction. We deliberately didn't automate this because automation without safeguards creates a new fraud vector — users could falsely claim wrong transfers to retrieve sent money."

---

**Q: What's the 10-minute cooldown between same sender and receiver for?**

> "It targets a specific scam pattern: an attacker who has obtained partial access (maybe knows your unlock PIN but not your transfer PIN) could try to send small amounts rapidly hoping one goes through. More commonly, it prevents accidental duplicate transfers — if a user sends ৳5,000 and doesn't see a confirmation, they might tap send again. The cooldown is implemented as a Redis key `cooldown:{sender_id}:{receiver_id}` with a 600-second TTL, set atomically after each successful transfer. It costs zero DB reads and zero compute — pure O(1) Redis GET."

---

*End of spec.md — See frontend.md for UI component specifications.*
