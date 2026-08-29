# New Features Specification
## Scheduled Payments & Group Payments

> **Stack:** FastAPI · MySQL · Redis · Celery · React
> **Appended to:** main `spec.md`

---

## Table of Contents

- [Feature 1 — Scheduled Payments](#feature-1--scheduled-payments)
  - [Overview & Rules](#11-overview--rules)
  - [Database Schema](#12-database-schema)
  - [Business Logic — Full Flows](#13-business-logic--full-flows)
  - [Celery Beat — Reminder Engine](#14-celery-beat--reminder-engine)
  - [API Endpoints](#15-api-endpoints)
  - [Redis Keys](#16-redis-keys)
  - [Notifications](#17-notifications)
  - [Edge Cases](#18-edge-cases)

- [Feature 2 — Group Payments](#feature-2--group-payments)
  - [Overview & Rules](#21-overview--rules)
  - [Database Schema](#22-database-schema)
  - [Business Logic — Full Flows](#23-business-logic--full-flows)
  - [Auto-Deduction Engine](#24-auto-deduction-engine)
  - [API Endpoints](#25-api-endpoints)
  - [Redis Keys](#26-redis-keys)
  - [Notifications](#27-notifications)
  - [Edge Cases](#28-edge-cases)

- [Engineering Defense Q&A](#engineering-defense-qa)

---

# Feature 1 — Scheduled Payments

---

## 1.1 Overview & Rules

A user can create a scheduled payment — either one-time or recurring — to automatically remind them before a due date and allow one-click payment via PIN. The system **never auto-pays** without explicit PIN confirmation. The reminder is the automation; the payment is always human-triggered.

**Real-world example:**
> "Every 1st of the month I pay house rent of ৳8,000 to my landlord. I want to be reminded 3 days before so I don't forget."

**Core rules:**
- Payment is **never executed automatically.** The system only sends reminders.
- On reminder, a **"Pay Now"** deep link opens the PIN modal directly — one tap, one PIN, done.
- `day_of_month` is capped at **28** for monthly/yearly to safely handle February.
- If a user **misses** a due date (doesn't pay within the payment window), it is logged as `missed` and the next cycle is calculated — the system does not retroactively execute past payments.
- A **paused** schedule skips all cycles until resumed. It does not catch up missed payments.
- Reminders are sent at **8:00 AM** via Celery Beat, not at arbitrary times.
- A duplicate reminder guard in Redis ensures the user receives at most **one reminder per cycle**.

---

## 1.2 Database Schema

### `scheduled_payments`
```sql
CREATE TABLE scheduled_payments (
    id                      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    reference_id            CHAR(36)            NOT NULL UNIQUE,     -- UUID v4

    -- Parties
    creator_id              BIGINT UNSIGNED     NOT NULL,            -- who pays
    receiver_id             BIGINT UNSIGNED     NOT NULL,            -- who receives

    -- Payment details
    label                   VARCHAR(100)        NOT NULL,            -- "House Rent", "Electricity Bill"
    amount                  DECIMAL(15,2)       NOT NULL,
    note                    VARCHAR(255),                            -- optional memo attached to each payment

    -- Schedule definition
    frequency               ENUM(
                                'one_time',      -- pay once on specific_date
                                'weekly',        -- pay every N-th day of week
                                'monthly',       -- pay every N-th day of month
                                'yearly'         -- pay every year on month+day
                            ) NOT NULL,
    specific_date           DATE,                                    -- for one_time only
    day_of_week             TINYINT UNSIGNED,                        -- 0=Sunday…6=Saturday, for weekly
    day_of_month            TINYINT UNSIGNED,                        -- 1–28, for monthly + yearly
    month_of_year           TINYINT UNSIGNED,                        -- 1–12, for yearly only
    start_date              DATE,                                    -- for recurring: when cycle begins
    end_date                DATE,                                    -- for recurring: NULL = runs forever

    -- Reminder config
    reminder_days_before    TINYINT UNSIGNED    NOT NULL DEFAULT 3,  -- remind X days before due date
    reminder_on_due_day     BOOLEAN             NOT NULL DEFAULT TRUE,-- send final reminder on the day itself

    -- State tracking
    status                  ENUM(
                                'active',        -- running normally
                                'paused',        -- skipping cycles until resumed
                                'cancelled',     -- permanently stopped
                                'completed'      -- one_time payment was made
                            ) NOT NULL DEFAULT 'active',
    next_payment_date       DATE,                                    -- computed + stored, updated each cycle
    last_paid_at            DATETIME,
    last_reminder_sent_date DATE,                                    -- track to prevent duplicate reminders per cycle
    total_paid_count        INT UNSIGNED        NOT NULL DEFAULT 0,

    created_at              DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_creator  (creator_id),
    INDEX idx_due_date (next_payment_date, status),                  -- Celery beat daily scan
    FOREIGN KEY (creator_id)  REFERENCES users(id),
    FOREIGN KEY (receiver_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### `scheduled_payment_logs`
```sql
-- Immutable record of every cycle for every scheduled payment.
-- Never UPDATE or DELETE rows here.
CREATE TABLE scheduled_payment_logs (
    id                      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    scheduled_payment_id    BIGINT UNSIGNED     NOT NULL,
    cycle_date              DATE                NOT NULL,            -- the date this cycle was due
    status                  ENUM(
                                'reminder_sent', -- reminder dispatched, awaiting payment
                                'paid',          -- user clicked Pay Now and completed PIN
                                'missed',        -- due date passed without payment
                                'skipped'        -- schedule was paused for this cycle
                            ) NOT NULL,
    transaction_id          BIGINT UNSIGNED,                         -- NULL unless status='paid'
    paid_at                 DATETIME,
    created_at              DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_schedule (scheduled_payment_id),
    INDEX idx_cycle    (cycle_date),
    FOREIGN KEY (scheduled_payment_id) REFERENCES scheduled_payments(id),
    FOREIGN KEY (transaction_id)       REFERENCES transactions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 1.3 Business Logic — Full Flows

### Creating a Scheduled Payment

```
POST /api/v1/scheduled/create
Headers: Authorization: Bearer <JWT>
Body: {
    receiver_identifier: "01XXXXXXXXX",    -- mobile number or user_id
    label: "House Rent",
    amount: 8000.00,
    note: "Landlord: Mr. Rahman",          -- optional
    frequency: "monthly",
    day_of_month: 1,                        -- pay every 1st of month
    reminder_days_before: 3,
    start_date: "2026-09-01",
    end_date: null                          -- runs forever
}

Validations:
→ Resolve receiver (same as validate_receiver in main flow)
→ Receiver must be active and not frozen
→ Cannot schedule to self
→ amount > 0
→ day_of_month: 1–28 only (reject 29, 30, 31 to protect against Feb)
→ If one_time: specific_date must be in the future
→ If weekly: day_of_week must be 0–6
→ If yearly: day_of_month 1–28 AND month_of_year 1–12

→ Compute initial next_payment_date (see helper below)
→ INSERT scheduled_payments
→ Response: {
    reference_id,
    label,
    amount,
    frequency,
    next_payment_date,
    receiver: { full_name, mobile_last4 }
}
```

**Computing `next_payment_date`:**
```python
from datetime import date, timedelta
from calendar import monthrange

def compute_next_payment_date(schedule) -> date:
    today = date.today()

    if schedule.frequency == 'one_time':
        return schedule.specific_date

    elif schedule.frequency == 'weekly':
        # Find next occurrence of target weekday
        target = schedule.day_of_week     # 0=Monday in Python's weekday()
        days_ahead = (target - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7                # Don't return today; use next week
        return today + timedelta(days=days_ahead)

    elif schedule.frequency == 'monthly':
        day = min(schedule.day_of_month, 28)
        # Try this month first
        candidate = today.replace(day=day)
        if candidate <= today:
            # Move to next month
            if today.month == 12:
                candidate = date(today.year + 1, 1, day)
            else:
                candidate = date(today.year, today.month + 1, day)
        return candidate

    elif schedule.frequency == 'yearly':
        day   = min(schedule.day_of_month, 28)
        month = schedule.month_of_year
        candidate = date(today.year, month, day)
        if candidate <= today:
            candidate = date(today.year + 1, month, day)
        return candidate
```

**Advancing to next cycle (called after payment or missed):**
```python
def advance_to_next_cycle(schedule) -> date | None:
    """Return next_payment_date after current cycle, or None if schedule is done."""
    if schedule.frequency == 'one_time':
        return None   # mark as completed

    base = schedule.next_payment_date

    if schedule.frequency == 'weekly':
        nxt = base + timedelta(weeks=1)

    elif schedule.frequency == 'monthly':
        day = schedule.day_of_month
        if base.month == 12:
            nxt = date(base.year + 1, 1, day)
        else:
            nxt = date(base.year, base.month + 1, day)

    elif schedule.frequency == 'yearly':
        nxt = date(base.year + 1, base.month, base.day)

    # Respect end_date
    if schedule.end_date and nxt > schedule.end_date:
        return None   # recurring schedule is done — mark completed
    return nxt
```

### One-Click "Pay Now"

```
POST /api/v1/scheduled/{id}/pay-now
Headers: Authorization: Bearer <JWT>
Body: { pin: "123456" }

→ Fetch scheduled_payment — must belong to current user
→ Status must be 'active' (not paused/cancelled/completed)
→ Validate receiver still exists and is active
→ Verify PIN (full lockout logic — same as regular transfer)
→ Check balance >= amount
→ Execute FULL atomic transfer (SELECT FOR UPDATE, debit, credit, INSERT transaction)
   Note: all existing safety checks apply — cooldown, daily limit, idempotency, etc.
→ INSERT scheduled_payment_logs: { cycle_date: next_payment_date, status: 'paid', transaction_id }
→ UPDATE scheduled_payments:
    last_paid_at = NOW()
    total_paid_count += 1
    IF frequency == 'one_time': status = 'completed', next_payment_date = NULL
    ELSE: next_payment_date = advance_to_next_cycle(schedule)
         last_reminder_sent_date = NULL   -- reset for new cycle
→ Notify receiver: "Received ৳{amount} — Scheduled payment from {creator_name} ({label})"
→ Response: { transaction_id, reference_id, new_balance, next_payment_date }
```

---

## 1.4 Celery Beat — Reminder Engine

Runs **every day at 08:00 AM** (Asia/Dhaka timezone).

```python
# tasks/scheduled_payment_tasks.py

@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        crontab(hour=8, minute=0),
        check_scheduled_reminders.s(),
        name='check-scheduled-payment-reminders'
    )

@celery_app.task
def check_scheduled_reminders():
    today = date.today()
    db   = get_sync_db_session()

    # ── Fetch candidates ─────────────────────────────────────────────────
    schedules = db.execute("""
        SELECT * FROM scheduled_payments
        WHERE status = 'active'
          AND next_payment_date IS NOT NULL
          AND next_payment_date <= DATE_ADD(CURDATE(), INTERVAL reminder_days_before DAY)
    """).fetchall()

    for s in schedules:
        # ── Guard: don't send duplicate reminder for this cycle ───────────
        redis_key = f"sched:reminded:{s.id}:{s.next_payment_date.isoformat()}"
        if redis_client.get(redis_key):
            continue

        days_until = (s.next_payment_date - today).days

        # ── Determine message ─────────────────────────────────────────────
        if days_until == 0 and s.reminder_on_due_day:
            title = f"Payment DUE TODAY: {s.label}"
            body  = (f"Your scheduled payment of ৳{s.amount:,.0f} to "
                     f"{get_receiver_name(s.receiver_id)} is due today.")
        elif days_until > 0:
            title = f"Upcoming Payment: {s.label}"
            body  = (f"Your scheduled payment of ৳{s.amount:,.0f} to "
                     f"{get_receiver_name(s.receiver_id)} is due in {days_until} day(s).")
        else:
            # Overdue — payment date has passed without being paid
            mark_as_missed(s, db)
            continue

        # ── Send notification with deep link ──────────────────────────────
        create_notification(
            user_id      = s.creator_id,
            title        = title,
            body         = body,
            type         = 'scheduled_reminder',
            reference_id = s.reference_id,  # frontend uses this to open Pay Now modal
        )

        # ── Log reminder sent ─────────────────────────────────────────────
        db.execute(
            "UPDATE scheduled_payments SET last_reminder_sent_date = :today WHERE id = :id",
            {"today": today, "id": s.id}
        )
        db.execute(
            "INSERT INTO scheduled_payment_logs (scheduled_payment_id, cycle_date, status) "
            "VALUES (:sid, :cd, 'reminder_sent')",
            {"sid": s.id, "cd": s.next_payment_date}
        )

        # ── Redis guard: TTL = 23h (so it's cleared before next 8am run) ──
        redis_client.setex(redis_key, 82800, 1)

    db.commit()

def mark_as_missed(schedule, db):
    """Payment date passed, user didn't pay. Log it and advance cycle."""
    db.execute(
        "INSERT INTO scheduled_payment_logs (scheduled_payment_id, cycle_date, status) "
        "VALUES (:sid, :cd, 'missed')",
        {"sid": schedule.id, "cd": schedule.next_payment_date}
    )
    next_date = advance_to_next_cycle(schedule)
    if next_date:
        db.execute(
            "UPDATE scheduled_payments SET next_payment_date = :nd, "
            "last_reminder_sent_date = NULL WHERE id = :id",
            {"nd": next_date, "id": schedule.id}
        )
    else:
        db.execute(
            "UPDATE scheduled_payments SET status = 'completed', next_payment_date = NULL "
            "WHERE id = :id",
            {"id": schedule.id}
        )
    # Notify user
    create_notification(
        user_id = schedule.creator_id,
        title   = f"Missed Payment: {schedule.label}",
        body    = (f"You missed your scheduled payment of ৳{schedule.amount:,.0f}. "
                   f"Next due: {next_date or 'N/A'}"),
        type    = 'scheduled_missed',
        reference_id = schedule.reference_id
    )
```

---

## 1.5 API Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/scheduled/create` | User | Create a new scheduled payment |
| GET | `/api/v1/scheduled` | User | List all user's scheduled payments (active + past) |
| GET | `/api/v1/scheduled/{id}` | User | Detail + payment history |
| PUT | `/api/v1/scheduled/{id}` | User | Edit label, amount, reminder_days |
| POST | `/api/v1/scheduled/{id}/pause` | User | Pause — skip upcoming cycles |
| POST | `/api/v1/scheduled/{id}/resume` | User | Resume — recompute next_payment_date |
| DELETE | `/api/v1/scheduled/{id}` | User | Cancel permanently |
| POST | `/api/v1/scheduled/{id}/pay-now` | User | Execute payment with PIN |
| GET | `/api/v1/scheduled/{id}/history` | User | Paginated log of all cycles |

**GET /api/v1/scheduled — Response shape:**
```json
{
  "scheduled_payments": [
    {
      "id": 1,
      "reference_id": "uuid",
      "label": "House Rent",
      "amount": 8000.00,
      "frequency": "monthly",
      "day_of_month": 1,
      "next_payment_date": "2026-09-01",
      "reminder_days_before": 3,
      "status": "active",
      "last_paid_at": "2026-08-01T09:15:00Z",
      "total_paid_count": 8,
      "receiver": { "full_name": "Rahman Landlord", "mobile_last4": "5678" }
    }
  ]
}
```

**PUT /api/v1/scheduled/{id} — Editable fields only:**
```json
{
  "label": "House Rent (Updated)",
  "amount": 8500.00,
  "reminder_days_before": 5,
  "note": "Rent increased from Sept"
}
```
> Amount and label can be changed. Frequency and receiver cannot be changed — cancel and recreate.

**POST /api/v1/scheduled/{id}/resume — Behaviour:**
```
→ status = 'active'
→ Recompute next_payment_date from today (don't backfill missed cycles)
→ Response: { next_payment_date: "..." }
```

---

## 1.6 Redis Keys

```
# Reminder deduplication per cycle
sched:reminded:{scheduled_id}:{YYYY-MM-DD}     TTL = 82800s (23h)
# Ensures at most one reminder notification per cycle even if Celery Beat fires twice.
```

---

## 1.7 Notifications

| Type | Recipient | Message |
|---|---|---|
| `scheduled_reminder` | Creator | "Your payment '{label}' of ৳{amount} to {receiver_name} is due in {N} days. [Pay Now]" |
| `scheduled_due_today` | Creator | "'{label}' of ৳{amount} is DUE TODAY. [Pay Now]" |
| `scheduled_paid` | Creator | "Scheduled payment '{label}' sent successfully. Next due: {date}" |
| `scheduled_paid` | Receiver | "Received ৳{amount} — scheduled payment from {creator_name} ({label})" |
| `scheduled_missed` | Creator | "You missed your '{label}' payment. Next due: {date}" |
| `scheduled_failed` | Creator | "Scheduled payment '{label}' failed: {reason}" |

> All `scheduled_reminder` and `scheduled_due_today` notifications include `reference_id` in metadata. The React frontend reads this field and shows a "Pay Now" button that opens the PIN modal pre-filled with the scheduled payment details.

---

## 1.8 Edge Cases

| Scenario | Behaviour |
|---|---|
| Insufficient balance on due date | Reminder still sent. `pay-now` returns 422 "Insufficient balance". Cycle is **not** auto-skipped. |
| Receiver account frozen on pay-now | `pay-now` returns 422. Log as attempt failed. Cycle stays open. |
| Sender account frozen | Celery marks cycle as `skipped`. Sender notified. |
| monthly on day 29/30/31 | Rejected at creation with validation error: "Use day 1–28 for monthly/yearly." |
| February 28 for day_of_month=28 | Handled naturally — date(year, 2, 28) is valid. |
| end_date < next computed date | Schedule auto-completes, status = 'completed', no further reminders. |
| User edits amount mid-cycle | New amount applies from **next** cycle. Current cycle reminder already shows old amount (no change). |
| Paused during reminder window | Reminder is suppressed. If payment date passes while paused → logged as `skipped`, next cycle computed on resume. |
| Same sender-receiver cooldown | 10-minute cooldown applies even to scheduled payments. If cooldown active on pay-now → 429 error. User retries after cooldown. |
| Daily limit exceeded on pay-now | 429 error returned. User must wait for limit reset or pay next day. |

---
---

# Feature 2 — Group Payments

---

## 2.1 Overview & Rules

A user (creator) splits a bill equally among a group of friends. The creator has typically already paid the bill externally and is now **collecting their shares** from members. Members can agree immediately (money transfers at once), or agree to pay later (debt recorded and auto-settled when their balance is topped up). The creator can send reminders to debtors, cancel individual debts (if settled externally), or cancel the whole group payment (with refunds).

**Real-world example:**
> "After a restaurant dinner, Arif paid ৳3,000. He opens the app, creates a group payment for ৳3,000 split across 3 friends. Each friend owes ৳1,000. Two friends pay immediately. The third has only ৳200 balance. They agree but can't pay now — a debt of ৳1,000 is recorded. When that friend later receives a salary transfer, ৳1,000 is auto-deducted and sent to Arif."

**Core rules:**
- Split is **equal** among all members (creator's own share is excluded by default, since they paid the bill).
- A member **agreeing** is their **consent** to the payment AND pre-authorization of future auto-deduction.
- Auto-deduction triggers on **every incoming transaction** to a debtor — no manual action required.
- Auto-deduction is **partial** — if a member receives ৳300 but owes ৳1,000, ৳300 is auto-deducted and ৳700 remains as debt.
- Creator can send max **1 reminder per 24h** per debtor (Redis-throttled).
- Creator can **cancel a member's debt** (marks it as paid externally — no money moves).
- Cancelling the entire group refunds all members who already paid (atomic reversals, no PIN required from creator since it is a system-initiated reversal).
- Group expires after **72 hours** if any members haven't responded — their invites are marked `expired`.
- PIN is required from the member when they **agree and pay immediately**. No PIN for auto-deduction (pre-authorized at agreement time).

---

## 2.2 Database Schema

### `group_payments`
```sql
CREATE TABLE group_payments (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    reference_id        CHAR(36)            NOT NULL UNIQUE,
    title               VARCHAR(255)        NOT NULL,               -- "Dinner at Radisson"
    creator_id          BIGINT UNSIGNED     NOT NULL,
    total_amount        DECIMAL(15,2)       NOT NULL,               -- the full bill
    per_person_amount   DECIMAL(15,2)       NOT NULL,               -- total / member_count
    member_count        TINYINT UNSIGNED    NOT NULL,               -- excludes creator
    creator_included    BOOLEAN             NOT NULL DEFAULT FALSE,  -- if TRUE creator's share is in total
    collected_amount    DECIMAL(15,2)       NOT NULL DEFAULT 0.00,  -- running total received
    note                VARCHAR(255),
    status              ENUM(
                            'open',          -- members still responding or debts pending
                            'completed',     -- all shares collected (paid or debt-settled)
                            'cancelled',     -- creator cancelled, refunds issued
                            'expired'        -- 72h passed, some members never responded
                        ) NOT NULL DEFAULT 'open',
    expires_at          DATETIME            NOT NULL,               -- created_at + 72h
    created_at          DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_creator (creator_id),
    INDEX idx_status  (status),
    INDEX idx_expires (expires_at, status),                         -- Celery expiry job
    FOREIGN KEY (creator_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### `group_payment_members`
```sql
CREATE TABLE group_payment_members (
    id                      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    group_payment_id        BIGINT UNSIGNED     NOT NULL,
    member_id               BIGINT UNSIGNED     NOT NULL,
    amount_owed             DECIMAL(15,2)       NOT NULL,
    status                  ENUM(
                                'pending',           -- invite sent, no response yet
                                'agreed_paid',       -- agreed + had balance → paid immediately
                                'agreed_debt',       -- agreed + no balance → debt created
                                'declined',          -- member refused
                                'expired',           -- 72h passed, no response
                                'debt_cancelled'     -- creator cancelled this member's debt
                            ) NOT NULL DEFAULT 'pending',
    debt_id                 BIGINT UNSIGNED,                        -- FK to member_debts if applicable
    agreed_at               DATETIME,
    paid_at                 DATETIME,                               -- set when fully paid (immediate or via auto-deduction)
    last_reminder_sent_at   DATETIME,                               -- throttle creator reminders
    created_at              DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uq_group_member    (group_payment_id, member_id),
    INDEX      idx_member_status  (member_id, status),
    FOREIGN KEY (group_payment_id) REFERENCES group_payments(id),
    FOREIGN KEY (member_id)        REFERENCES users(id),
    FOREIGN KEY (debt_id)          REFERENCES member_debts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### `member_debts`
```sql
-- Tracks money owed by a member to a creator due to insufficient balance at agreement time.
-- Paid off via auto-deduction in installments when member receives funds.
CREATE TABLE member_debts (
    id                      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    reference_id            CHAR(36)            NOT NULL UNIQUE,
    group_payment_id        BIGINT UNSIGNED     NOT NULL,
    group_payment_member_id BIGINT UNSIGNED     NOT NULL,
    debtor_id               BIGINT UNSIGNED     NOT NULL,           -- member who owes
    creditor_id             BIGINT UNSIGNED     NOT NULL,           -- creator who is owed
    original_amount         DECIMAL(15,2)       NOT NULL,           -- full debt amount
    remaining_amount        DECIMAL(15,2)       NOT NULL,           -- decreases with each payment
    status                  ENUM(
                                'pending',           -- not yet fully paid
                                'partially_paid',    -- some paid, remainder outstanding
                                'fully_paid',        -- completely settled
                                'cancelled'          -- creator cancelled (paid externally)
                            ) NOT NULL DEFAULT 'pending',
    pre_authorized          BOOLEAN             NOT NULL DEFAULT TRUE,  -- consent given at agree time
    cancelled_at            DATETIME,
    cancelled_reason        VARCHAR(255),
    fully_paid_at           DATETIME,
    created_at              DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_debtor   (debtor_id, status),                         -- auto-deduction lookup
    INDEX idx_creditor (creditor_id, status),
    FOREIGN KEY (group_payment_id)        REFERENCES group_payments(id),
    FOREIGN KEY (group_payment_member_id) REFERENCES group_payment_members(id),
    FOREIGN KEY (debtor_id)               REFERENCES users(id),
    FOREIGN KEY (creditor_id)             REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### `debt_payments`
```sql
-- Immutable log of every auto-deduction installment. Never UPDATE or DELETE.
CREATE TABLE debt_payments (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    debt_id         BIGINT UNSIGNED     NOT NULL,
    transaction_id  BIGINT UNSIGNED     NOT NULL,           -- the atomic transfer record
    amount          DECIMAL(15,2)       NOT NULL,           -- installment amount
    remaining_after DECIMAL(15,2)       NOT NULL,           -- debt remaining after this payment
    payment_type    ENUM('auto_deduction','manual') NOT NULL DEFAULT 'auto_deduction',
    created_at      DATETIME            NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_debt (debt_id),
    FOREIGN KEY (debt_id)        REFERENCES member_debts(id),
    FOREIGN KEY (transaction_id) REFERENCES transactions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 2.3 Business Logic — Full Flows

### Creating a Group Payment

```
POST /api/v1/group-payments/create
Headers: Authorization: Bearer <JWT>
Body: {
    title: "Dinner at Radisson",
    total_amount: 3000.00,
    members: ["01XXXXXXXXX", "01YYYYYYYYY", "01ZZZZZZZZZ"],
    creator_included: false,    -- creator already paid, not collecting their own share
    note: "Friday night dinner"
}

Validations:
→ Resolve all member mobile numbers → user records
→ All members must exist and have is_active=true
→ No member can be the creator themselves
→ No duplicate members in the list
→ members list: min 1, max 20
→ total_amount > 0
→ If creator_included=false: per_person_amount = total_amount / len(members)
   If creator_included=true:  per_person_amount = total_amount / (len(members) + 1)
                              (creator's share is implicit — they've already borne it)

→ INSERT group_payments: {
    reference_id: uuid4(),
    title, creator_id, total_amount,
    per_person_amount,
    member_count: len(members),
    creator_included,
    collected_amount: 0.00,
    status: 'open',
    expires_at: NOW() + 72h
  }

→ For each member: INSERT group_payment_members: { status: 'pending', amount_owed: per_person_amount }

→ For each member: send notification (type=group_invite):
    "{creator_name} added you to '{title}'.
     Your share: ৳{per_person_amount}. Tap to agree or decline."

→ Response: {
    group_payment_id,
    reference_id,
    title,
    total_amount,
    per_person_amount,
    member_count,
    expires_at,
    members: [ { full_name, mobile_last4, status: 'pending' } ]
}
```

### Member Agrees — Full Decision Tree

```
POST /api/v1/group-payments/{group_id}/respond
Headers: Authorization: Bearer <JWT>
Body: { action: "agree", pin: "123456" }

Pre-checks:
→ Fetch group_payment — must be 'open' and not expired
→ Fetch group_payment_members where group_payment_id + member_id = current_user.id
→ Member status must be 'pending'
→ PIN: verify (full lockout logic applies — 3 strikes, 15 min lock)

→ Fetch member's current balance (fresh DB read)

╔══════════════════════════════════════════════════════════════════╗
║  CASE A: member.balance >= amount_owed                          ║
╠══════════════════════════════════════════════════════════════════╣
║ Execute FULL atomic transfer: member → creator (amount_owed)    ║
║   (SELECT FOR UPDATE on member row → debit → credit → commit)  ║
║                                                                  ║
║ INSERT transactions: type='group_payment', note=title           ║
║ UPDATE group_payment_members:                                    ║
║   status = 'agreed_paid', agreed_at = NOW(), paid_at = NOW()   ║
║ UPDATE group_payments:                                           ║
║   collected_amount += amount_owed                               ║
║                                                                  ║
║ Check completion: IF collected_amount >= total_amount (all      ║
║   members agreed_paid or debt_cancelled):                       ║
║   → UPDATE group_payments SET status = 'completed'              ║
║   → Notify creator: "{title} is fully collected! ✓"            ║
║                                                                  ║
║ Notify creator:  "{member_name} paid their ৳{amount} share"    ║
║ Notify member:   "You paid ৳{amount} for '{title}'"             ║
╚══════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════╗
║  CASE B: member.balance < amount_owed                           ║
╠══════════════════════════════════════════════════════════════════╣
║ NO money transfer happens in this step.                          ║
║                                                                  ║
║ INSERT member_debts: {                                           ║
║   debtor_id: member_id,                                         ║
║   creditor_id: creator_id,                                      ║
║   original_amount: amount_owed,                                  ║
║   remaining_amount: amount_owed,                                 ║
║   status: 'pending',                                             ║
║   pre_authorized: TRUE   ← consent given at agreement time      ║
║ }                                                                ║
║                                                                  ║
║ UPDATE group_payment_members:                                    ║
║   status = 'agreed_debt', agreed_at = NOW(), debt_id = new_id  ║
║                                                                  ║
║ Notify creator:                                                  ║
║   "{member_name} agreed but has insufficient balance.           ║
║    Debt of ৳{amount} recorded. Auto-pays when they get funds."  ║
║                                                                  ║
║ Notify member:                                                   ║
║   "You've agreed to pay ৳{amount} for '{title}'.               ║
║    Since your balance is low, it will auto-deduct when you      ║
║    receive money. No action needed."                             ║
╚══════════════════════════════════════════════════════════════════╝
```

### Member Declines

```
POST /api/v1/group-payments/{group_id}/respond
Body: { action: "decline" }

→ No PIN required to decline
→ UPDATE group_payment_members: status = 'declined', responded_at = NOW()
→ Notify creator: "{member_name} declined their share of '{title}'"
→ Creator can: leave it (they absorb that share) or re-invite someone else
→ Response: { status: "declined" }
```

### Creator: Send Reminder to a Debtor

```
POST /api/v1/group-payments/{group_id}/members/{member_id}/remind
Headers: Authorization: Bearer <JWT>

→ Validate current_user = creator
→ Validate group_payment_members record: status must be 'agreed_debt'
→ Validate debt is still pending (remaining_amount > 0)
→ Redis throttle check: group:reminder:{group_id}:{member_id}
     If key exists → 429 "You can only send one reminder per 24 hours per member"
→ Send notification to member (type=group_debt_reminder):
    "Reminder from {creator_name}: You still owe ৳{remaining_amount} for '{title}'.
     It will auto-deduct the next time you receive funds."
→ UPDATE group_payment_members: last_reminder_sent_at = NOW()
→ Redis SET group:reminder:{group_id}:{member_id} TTL=86400s
→ Response: { message: "Reminder sent" }
```

### Creator: Cancel a Member's Debt

```
POST /api/v1/group-payments/{group_id}/members/{member_id}/cancel-debt
Headers: Authorization: Bearer <JWT>
Body: { reason: "He paid me cash outside the app" }

→ Validate current_user = creator
→ Fetch group_payment_members: status must be 'agreed_debt'
→ Fetch member_debts via debt_id: status must be 'pending' or 'partially_paid'

→ UPDATE member_debts:
    status = 'cancelled',
    cancelled_at = NOW(),
    cancelled_reason = body.reason
→ UPDATE group_payment_members:
    status = 'debt_cancelled'
→ UPDATE group_payments:
    collected_amount += (original_amount - remaining_amount)
    -- count already-auto-paid installments as collected

→ Check group completion (all members: agreed_paid | agreed_debt(fully_paid) | debt_cancelled | declined)
→ Notify member:
    "{creator_name} marked your ৳{remaining_amount} debt for '{title}' as settled.
     No further payment required."
→ Notify creator: "Debt of ৳{remaining} from {member_name} cancelled."
→ Response: { message: "Debt cancelled" }
```

### Creator: Cancel Entire Group Payment (With Refunds)

```
POST /api/v1/group-payments/{group_id}/cancel
Headers: Authorization: Bearer <JWT>
Body: { reason: "Plans changed" }   -- optional

→ Validate current_user = creator
→ Validate group_payment.status = 'open'

→ For each member with status = 'agreed_paid':
    Execute REVERSAL (system-initiated, no PIN needed from creator):
    SELECT FOR UPDATE on creator → debit amount_owed from creator → credit to member
    INSERT transactions: type='group_payment_refund'
    UPDATE group_payment_members: status = 'refunded'
    Notify member: "'{title}' was cancelled. ৳{amount} refunded to your account."

→ For each member with status = 'agreed_debt':
    UPDATE member_debts: status = 'cancelled', cancelled_reason = 'group_cancelled'
    UPDATE group_payment_members: status = 'debt_cancelled'
    Notify member: "'{title}' was cancelled. Your debt of ৳{amount} has been cleared."

→ For each member with status = 'pending':
    UPDATE group_payment_members: status = 'expired'
    (No notification needed — invite is simply voided)

→ UPDATE group_payments: status = 'cancelled'
→ Notify creator: "Group payment '{title}' cancelled. Refunds issued to {N} members."
→ Response: { message: "Group payment cancelled", refunded_count: N }

⚠️ Edge: If creator's balance is insufficient to refund all members
(e.g., they spent the collected money), the reversal fails.
→ Return 422: "Insufficient balance to process all refunds.
               Please ensure you have ৳{total_to_refund} available."
→ No partial cancellation — all or nothing.
```

---

## 2.4 Auto-Deduction Engine

This is the core of the debt-settlement system. It is triggered as a **FastAPI `BackgroundTask`** appended to every incoming transaction handler (after commit).

```python
# services/debt_service.py

async def settle_pending_debts(debtor_id: int, db: AsyncSession):
    """
    Called after any event that increases a user's balance:
      - Received a regular transfer
      - Accepted a money request
      - Auto-deduction from someone else (cascade trigger)
    Pays off the debtor's oldest pending debts in FIFO order.
    """

    # ── Step 1: Get pending debts, oldest first ──────────────────────────
    pending_debts = await db.execute(
        """
        SELECT md.*, gpm.group_payment_id
        FROM member_debts md
        JOIN group_payment_members gpm ON gpm.debt_id = md.id
        WHERE md.debtor_id   = :uid
          AND md.status      IN ('pending', 'partially_paid')
          AND md.pre_authorized = TRUE
        ORDER BY md.created_at ASC
        """,
        {"uid": debtor_id}
    )
    if not pending_debts:
        return

    # ── Step 2: Get fresh balance (no cache — this is financial) ─────────
    user_row = await db.execute(
        "SELECT balance FROM users WHERE id = :uid FOR UPDATE",
        {"uid": debtor_id}
    )
    available_balance = Decimal(str(user_row.balance))

    for debt in pending_debts:
        if available_balance <= 0:
            break

        payable = min(available_balance, debt.remaining_amount)
        new_remaining = debt.remaining_amount - payable
        new_debt_status = 'fully_paid' if new_remaining == 0 else 'partially_paid'

        async with db.begin():
            # ── Debit debtor ─────────────────────────────────────────────
            result = await db.execute(
                "UPDATE users SET balance = balance - :amt "
                "WHERE id = :id AND balance >= :amt",
                {"amt": payable, "id": debt.debtor_id}
            )
            if result.rowcount == 0:
                # Balance dropped between our read and the update (race condition)
                break  # Skip and retry on next incoming transaction

            # ── Credit creditor ──────────────────────────────────────────
            await db.execute(
                "UPDATE users SET balance = balance + :amt WHERE id = :id",
                {"amt": payable, "id": debt.creditor_id}
            )

            # ── Insert transaction record ────────────────────────────────
            tx_id = await insert_transaction(
                sender_id   = debt.debtor_id,
                receiver_id = debt.creditor_id,
                amount      = payable,
                type        = 'debt_settlement',
                note        = f"Auto-settlement: {payable} for group payment",
                initiated_via = 'system'
            )

            # ── Log debt payment ─────────────────────────────────────────
            await db.execute(
                "INSERT INTO debt_payments "
                "(debt_id, transaction_id, amount, remaining_after, payment_type) "
                "VALUES (:did, :tid, :amt, :rem, 'auto_deduction')",
                {"did": debt.id, "tid": tx_id, "amt": payable, "rem": new_remaining}
            )

            # ── Update debt record ───────────────────────────────────────
            await db.execute(
                "UPDATE member_debts "
                "SET remaining_amount = :rem, status = :s, "
                "    fully_paid_at = IF(:s='fully_paid', NOW(), NULL) "
                "WHERE id = :id",
                {"rem": new_remaining, "s": new_debt_status, "id": debt.id}
            )

            # ── Update group_payment_members if fully paid ───────────────
            if new_debt_status == 'fully_paid':
                await db.execute(
                    "UPDATE group_payment_members "
                    "SET status = 'agreed_paid', paid_at = NOW() "
                    "WHERE debt_id = :did",
                    {"did": debt.id}
                )
                # Update group collected_amount
                await db.execute(
                    "UPDATE group_payments "
                    "SET collected_amount = collected_amount + :orig_amount "
                    "WHERE id = :gpid",
                    {"orig_amount": debt.original_amount, "gpid": debt.group_payment_id}
                )
                # Check group completion
                await check_group_completion(debt.group_payment_id, db)

            else:
                # Partially paid — update group collected_amount by this installment
                await db.execute(
                    "UPDATE group_payments "
                    "SET collected_amount = collected_amount + :amt "
                    "WHERE id = :gpid",
                    {"amt": payable, "gpid": debt.group_payment_id}
                )

        # ── Notifications ────────────────────────────────────────────────
        if new_debt_status == 'fully_paid':
            notify_debt_fully_paid(debt.debtor_id, debt.creditor_id, payable, debt)
        else:
            notify_debt_partial_paid(debt.debtor_id, debt.creditor_id, payable, new_remaining, debt)

        available_balance -= payable


async def check_group_completion(group_payment_id: int, db: AsyncSession):
    """Group is complete when no members are in pending or agreed_debt(partial) state."""
    pending = await db.execute(
        """
        SELECT COUNT(*) FROM group_payment_members
        WHERE group_payment_id = :gid
          AND status IN ('pending', 'agreed_debt')
        """,
        {"gid": group_payment_id}
    )
    # Also check if all agreed_debt members have fully_paid debts
    active_debts = await db.execute(
        """
        SELECT COUNT(*) FROM member_debts md
        JOIN group_payment_members gpm ON gpm.debt_id = md.id
        WHERE gpm.group_payment_id = :gid
          AND md.status IN ('pending', 'partially_paid')
        """,
        {"gid": group_payment_id}
    )
    if pending.scalar() == 0 and active_debts.scalar() == 0:
        await db.execute(
            "UPDATE group_payments SET status = 'completed' WHERE id = :gid",
            {"gid": group_payment_id}
        )
        gp = await db.execute("SELECT * FROM group_payments WHERE id = :gid", {"gid": group_payment_id})
        create_notification(gp.creator_id, type='group_completed',
                            body=f"'{gp.title}' is fully collected! ৳{gp.total_amount} received.")
```

**Where `settle_pending_debts` is called:**
```python
# In routers/transactions.py — after every successful incoming transfer:
@router.post("/send")
async def send_money(request, background_tasks: BackgroundTasks, ...):
    ...
    result = await transfer_service.send_money(...)
    # After commit, trigger debt settlement for the receiver
    background_tasks.add_task(settle_pending_debts, result.receiver_id, db)
    return result

# Also triggered after:
# - Money request accepted (receiver of payment = payer of request)
# - Any other event that increases a user's balance
```

**Celery Beat — Group Payment Expiry (runs every 30 minutes):**
```python
@celery_app.task
def expire_group_payments():
    """Mark pending member invites as expired after 72h window."""
    now = datetime.utcnow()

    # Mark individual member invites as expired
    db.execute(
        "UPDATE group_payment_members gpm "
        "JOIN group_payments gp ON gp.id = gpm.group_payment_id "
        "SET gpm.status = 'expired' "
        "WHERE gpm.status = 'pending' AND gp.expires_at < :now",
        {"now": now}
    )

    # Mark group as expired if all pending members have now expired
    # and no member has agreed (all declined/expired)
    db.execute(
        """
        UPDATE group_payments SET status = 'expired'
        WHERE status = 'open'
          AND expires_at < :now
          AND id NOT IN (
              SELECT DISTINCT group_payment_id FROM group_payment_members
              WHERE status IN ('agreed_paid', 'agreed_debt')
          )
        """,
        {"now": now}
    )

    # Notify creators of newly expired groups
    ...
```

---

## 2.5 API Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/group-payments/create` | User | Create group payment |
| GET | `/api/v1/group-payments` | User | List groups (as creator OR member) |
| GET | `/api/v1/group-payments/{id}` | User | Full detail + member statuses |
| POST | `/api/v1/group-payments/{id}/respond` | Member | Agree (with PIN) or Decline |
| POST | `/api/v1/group-payments/{id}/members/{member_id}/remind` | Creator | Send debt reminder |
| POST | `/api/v1/group-payments/{id}/members/{member_id}/cancel-debt` | Creator | Cancel member's debt |
| POST | `/api/v1/group-payments/{id}/cancel` | Creator | Cancel group + refund all |
| GET | `/api/v1/group-payments/{id}/members` | Creator | Member list with statuses |
| GET | `/api/v1/debts/my-debts` | User | All my pending debts across all groups |
| GET | `/api/v1/debts/owed-to-me` | User | All debts owed to me |
| GET | `/api/v1/debts/{debt_id}/history` | User (involved) | Installment payment history |

**GET /api/v1/group-payments — Response shape:**
```json
{
  "as_creator": [
    {
      "reference_id": "uuid",
      "title": "Dinner at Radisson",
      "total_amount": 3000.00,
      "per_person_amount": 1000.00,
      "collected_amount": 2000.00,
      "status": "open",
      "member_count": 3,
      "members_paid": 2,
      "members_pending": 0,
      "members_debt": 1,
      "expires_at": "2026-08-31T10:00:00Z",
      "created_at": "2026-08-29T10:00:00Z"
    }
  ],
  "as_member": [
    {
      "reference_id": "uuid",
      "title": "Uber Pool - Friday",
      "creator_name": "Ankon Dey",
      "amount_owed": 250.00,
      "my_status": "pending",
      "expires_at": "2026-09-01T18:00:00Z"
    }
  ]
}
```

**GET /api/v1/debts/my-debts — Response shape:**
```json
{
  "total_outstanding": 1750.00,
  "debts": [
    {
      "debt_id": 1,
      "reference_id": "uuid",
      "group_title": "Dinner at Radisson",
      "creditor_name": "Arif Hussain",
      "original_amount": 1000.00,
      "remaining_amount": 800.00,
      "status": "partially_paid",
      "created_at": "2026-08-29T10:00:00Z",
      "last_payment": {
        "amount": 200.00,
        "paid_at": "2026-08-29T14:00:00Z"
      }
    }
  ]
}
```

---

## 2.6 Redis Keys

```
# Creator reminder throttle — 1 reminder per 24h per member
group:reminder:{group_payment_id}:{member_id}    TTL = 86400s (24h)

# Idempotency for group creation (prevent double-tap on create button)
group:idem:{creator_id}:{idempotency_key}        TTL = 86400s
```

---

## 2.7 Notifications

| Type | Recipient | Message |
|---|---|---|
| `group_invite` | Each member | "{creator_name} added you to '{title}'. Your share: ৳{amount}. [Agree] [Decline]" |
| `group_member_paid` | Creator | "{member_name} paid their ৳{amount} share of '{title}'" |
| `group_member_agreed_debt` | Creator | "{member_name} agreed but balance is low. Debt ৳{amount} recorded — auto-pays when they receive funds." |
| `group_member_declined` | Creator | "{member_name} declined their share of '{title}'" |
| `group_invite_agreed` | Member (CASE A) | "You paid ৳{amount} for '{title}'. Balance: ৳{new_balance}" |
| `group_invite_agreed_debt` | Member (CASE B) | "You agreed to pay ৳{amount} for '{title}'. Will auto-deduct when you receive funds." |
| `group_debt_reminder` | Debtor | "Reminder from {creator_name}: You owe ৳{remaining} for '{title}'. Auto-deducts next time you receive money." |
| `group_debt_auto_paid_partial` | Debtor | "৳{amount} auto-deducted for '{title}' debt. Remaining: ৳{remaining}" |
| `group_debt_auto_paid_partial` | Creditor | "{member_name} auto-paid ৳{amount} toward '{title}'. Still owed: ৳{remaining}" |
| `group_debt_fully_paid` | Debtor | "Your ৳{original} debt for '{title}' is fully settled ✓" |
| `group_debt_fully_paid` | Creditor | "{member_name}'s full ৳{amount} share for '{title}' has been settled ✓" |
| `group_debt_cancelled` | Debtor | "{creator_name} marked your ৳{remaining} debt for '{title}' as settled. No payment needed." |
| `group_completed` | Creator | "'{title}' fully collected! All ৳{total_amount} received ✓" |
| `group_cancelled` | Each member | "'{title}' group payment was cancelled. ৳{amount} refunded to your account." |
| `group_expired` | Creator | "'{title}' expired. {N} members didn't respond in time." |
| `group_member_expired` | Member | "The group payment invite from {creator_name} for '{title}' has expired." |

---

## 2.8 Edge Cases

| Scenario | Behaviour |
|---|---|
| Member agrees (CASE A) but balance drops between read and `FOR UPDATE` | `UPDATE ... WHERE balance >= amount` — rowcount 0 → falls to CASE B automatically, debt created |
| Auto-deduction races with another outgoing transfer | `UPDATE ... WHERE balance >= amount` guard — if balance insufficient at update time, `rowcount = 0`, skip and retry on next incoming |
| Creator doesn't have enough balance to refund on cancel | Return 422. No partial cancellation. Creator must top up and retry. |
| Member has debts to multiple creators | FIFO: oldest debt is settled first. All proceed until available balance is exhausted. |
| Member's incoming transfer is less than smallest debt | Partial payment recorded (debt_payments row inserted). remaining_amount reduced. |
| Creator frozen after group is open | Members can still agree. Agreements create debts but auto-deductions will attempt to credit creator — if creator is frozen, auto-deductions are blocked and queued until creator is unfrozen. |
| Member frozen after agreeing (has debt) | Auto-deductions are debited from debtor → credited to creditor. Debtor's frozen status is irrelevant to outgoing auto-deduction. (Auto-deduction is a debit from the debtor — frozen accounts cannot transact. So auto-deduction is blocked while debtor is frozen.) |
| Group expires with some agreed_debt still pending | Group status → 'expired'. Debts remain active and continue auto-settling. Only the invite window expires, not the debt itself. |
| Creator tries to remind a member who declined | 422: "This member declined the payment." |
| Creator tries to cancel debt of a member who paid | 422: "This member's debt is already settled." |
| Same person in members list twice | 422: "Duplicate member in list" |
| Creator in members list | 422: "You cannot add yourself as a member" |
| Total amount ৳0 | 422: "Total amount must be greater than 0" |
| per_person_amount rounds to ৳0 (e.g. total ৳1, 5 members) | 422: "Per-person amount is too small. Minimum per person: ৳1.00" |
| Member responds after 72h expiry | 422: "This group payment has expired" |

---

## Engineering Defense Q&A

**Q: Why doesn't the system auto-pay scheduled payments without user action?**

> "In a financial system, auto-debit without explicit user consent per cycle is a trust violation. Even recurring standing orders in real banking require the user to set them up with informed consent. Our approach is: the system handles the *reminder* and reduces friction to *one tap + PIN*. The human still confirms each payment. This prevents a compromised account from having money drain automatically, and it's the correct trust model for a fintech app."

---

**Q: Why is the auto-deduction for group payment debts allowed without a PIN per installment?**

> "Because the PIN was captured at agreement time. When a member types their PIN and taps 'Agree', that is their explicit consent — they agreed to the amount AND pre-authorized future auto-deduction of that specific debt. This is exactly how standing instructions and EMI mandates work in real banking: you sign once, deductions happen automatically. The key safeguard is that auto-deductions are scoped to the exact debt amount for a specific group payment — they are not open-ended authorizations."

---

**Q: What prevents infinite cascading auto-deductions?**

> "Two things. First, `settle_pending_debts` only runs against `member_debts` records with `pre_authorized = TRUE` — it cannot deduct against arbitrary future debts. Second, after auto-deduction credits a creditor, the background task that runs for that creditor's incoming balance event checks their own debts as a debtor — not as a cascading creditor. There is no recursive trigger chain. The function terminates when `available_balance <= 0` for the current debtor."

---

**Q: Why FIFO ordering for multiple debts?**

> "Oldest debt first respects the chronological commitment the user made. If someone owes ৳1,000 from a July dinner and ৳500 from an August lunch, their July debt was a longer-standing commitment. FIFO also aligns with how people psychologically think about settling debts. A creditor-priority model (pay largest debt first, or pay one specific creditor first) would require the debtor to rank their creditors, which adds UX complexity without real user value."

---

**Q: How do you prevent a creator from unfairly cancelling a group after collecting money?**

> "The creator can only cancel with a full refund to all members who paid. The cancel endpoint checks the creator's current balance against the total amount to refund, and rejects the request if insufficient — the creator cannot cancel and keep the money. This is enforced at the API level with a balance check before the atomic reversals begin. The audit log records all reversals permanently."

---

**Q: How do you handle the case where a member's auto-deduction fails mid-loop (e.g., DB crash)?**

> "Each debt settlement is wrapped in its own `async with db.begin()` block. If one debt's commit fails, it rolls back that debt atomically — the debit and credit are both reverted. The next auto-deduction trigger (on the debtor's next incoming transaction) will retry from the current `remaining_amount` in the database, which was not changed. The `debt_payments` log has no orphan entry because the transaction was rolled back. There is no double-deduction risk."

---

*End of spec-new-features.md*
