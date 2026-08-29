"""Scheduled payments — recurring/one-time payment reminders.

The system NEVER auto-pays. It sends a reminder (via Celery Beat at 08:00) with a
deep link; the user still confirms every cycle with one tap + PIN through
``pay_now``. A missed cycle is logged and the schedule advances — past payments are
never retroactively executed.
"""

import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationType
from app.models.scheduled_payment import (
    ScheduledPayment,
    ScheduledPaymentLog,
    ScheduledPaymentLogStatus,
    ScheduleFrequency,
    ScheduleStatus,
)
from app.models.transaction import InitiatedVia, TransactionType
from app.models.user import User
from app.redis_client import redis_client
from app.schemas.scheduled_payment import (
    CreateScheduledPaymentResponse,
    PayNowResponse,
    ReceiverBrief,
    ScheduledPaymentDetailResponse,
    ScheduledPaymentHistoryResponse,
    ScheduledPaymentItem,
    ScheduledPaymentListResponse,
    ScheduledPaymentLogItem,
)
from app.services.audit_service import write_audit_log
from app.services.notification_service import send_notification
from app.services.transfer_service import _check_receiver_valid, resolve_receiver, send_money

MAX_DAY_OF_MONTH = 28  # cap so monthly/yearly schedules survive February


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _py_weekday_from_dow(day_of_week: int) -> int:
    """Schema stores 0=Sunday..6=Saturday; Python's date.weekday() is 0=Monday..6=Sunday."""
    return (day_of_week - 1) % 7


# ── Date maths ──────────────────────────────────────────────────────────────
def compute_next_payment_date(
    frequency: ScheduleFrequency,
    *,
    specific_date: date | None,
    day_of_week: int | None,
    day_of_month: int | None,
    month_of_year: int | None,
    start_date: date | None,
    today: date | None = None,
) -> date | None:
    today = today or date.today()
    anchor = max(today, start_date) if start_date else today

    if frequency == ScheduleFrequency.one_time:
        return specific_date

    if frequency == ScheduleFrequency.weekly:
        target = _py_weekday_from_dow(day_of_week)
        days_ahead = (target - anchor.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7  # never "today"; use next week
        return anchor + timedelta(days=days_ahead)

    if frequency == ScheduleFrequency.monthly:
        day = min(day_of_month, MAX_DAY_OF_MONTH)
        candidate = anchor.replace(day=min(day, monthrange(anchor.year, anchor.month)[1]))
        if candidate <= today:
            if anchor.month == 12:
                candidate = date(anchor.year + 1, 1, day)
            else:
                candidate = date(anchor.year, anchor.month + 1, day)
        return candidate

    if frequency == ScheduleFrequency.yearly:
        day = min(day_of_month, MAX_DAY_OF_MONTH)
        candidate = date(anchor.year, month_of_year, day)
        if candidate <= today:
            candidate = date(anchor.year + 1, month_of_year, day)
        return candidate

    return None


def advance_to_next_cycle(schedule: ScheduledPayment) -> date | None:
    """next_payment_date for the cycle after the current one, or None if the schedule is done."""
    if schedule.frequency == ScheduleFrequency.one_time:
        return None

    base = schedule.next_payment_date
    if base is None:
        return None

    if schedule.frequency == ScheduleFrequency.weekly:
        nxt = base + timedelta(weeks=1)
    elif schedule.frequency == ScheduleFrequency.monthly:
        day = min(schedule.day_of_month or base.day, MAX_DAY_OF_MONTH)
        if base.month == 12:
            nxt = date(base.year + 1, 1, day)
        else:
            nxt = date(base.year, base.month + 1, day)
    elif schedule.frequency == ScheduleFrequency.yearly:
        day = min(schedule.day_of_month or base.day, MAX_DAY_OF_MONTH)
        nxt = date(base.year + 1, schedule.month_of_year or base.month, day)
    else:
        return None

    if schedule.end_date and nxt > schedule.end_date:
        return None
    return nxt


# ── Serialisation ──────────────────────────────────────────────────────────
async def _receiver_brief(db: AsyncSession, receiver_id: int) -> ReceiverBrief:
    u = (await db.execute(select(User).where(User.id == receiver_id))).scalar_one_or_none()
    if not u:
        return ReceiverBrief(full_name="Unknown", mobile_last4="----")
    return ReceiverBrief(full_name=u.full_name, mobile_last4=u.mobile_number[-4:])


def _to_item(s: ScheduledPayment, receiver: ReceiverBrief) -> ScheduledPaymentItem:
    return ScheduledPaymentItem(
        id=s.id,
        reference_id=s.reference_id,
        label=s.label,
        amount=float(s.amount),
        frequency=s.frequency.value,
        specific_date=s.specific_date,
        day_of_week=s.day_of_week,
        day_of_month=s.day_of_month,
        month_of_year=s.month_of_year,
        next_payment_date=s.next_payment_date,
        reminder_days_before=s.reminder_days_before,
        status=s.status.value,
        last_paid_at=s.last_paid_at,
        total_paid_count=s.total_paid_count,
        receiver=receiver,
    )


def _log_item(log: ScheduledPaymentLog) -> ScheduledPaymentLogItem:
    return ScheduledPaymentLogItem(
        cycle_date=log.cycle_date,
        status=log.status.value,
        transaction_id=log.transaction_id,
        paid_at=log.paid_at,
        created_at=log.created_at,
    )


# ── CRUD / flows ───────────────────────────────────────────────────────────
async def create_scheduled_payment(
    db: AsyncSession, creator: User, body
) -> CreateScheduledPaymentResponse:
    receiver = await resolve_receiver(db, body.receiver_identifier)
    receiver = _check_receiver_valid(receiver, creator.id)

    freq = ScheduleFrequency(body.frequency)
    today = date.today()

    if freq == ScheduleFrequency.one_time:
        if not body.specific_date:
            raise HTTPException(422, "specific_date is required for one_time payments")
        if body.specific_date <= today:
            raise HTTPException(422, "specific_date must be in the future")
    elif freq == ScheduleFrequency.weekly:
        if body.day_of_week is None:
            raise HTTPException(422, "day_of_week (0-6) is required for weekly payments")
    elif freq == ScheduleFrequency.monthly:
        if body.day_of_month is None:
            raise HTTPException(422, "day_of_month is required for monthly payments")
        if not 1 <= body.day_of_month <= MAX_DAY_OF_MONTH:
            raise HTTPException(422, "Use day 1–28 for monthly/yearly.")
    elif freq == ScheduleFrequency.yearly:
        if body.day_of_month is None or body.month_of_year is None:
            raise HTTPException(422, "day_of_month and month_of_year are required for yearly payments")
        if not 1 <= body.day_of_month <= MAX_DAY_OF_MONTH:
            raise HTTPException(422, "Use day 1–28 for monthly/yearly.")

    if body.end_date and body.start_date and body.end_date < body.start_date:
        raise HTTPException(422, "end_date cannot be before start_date")

    next_date = compute_next_payment_date(
        freq,
        specific_date=body.specific_date,
        day_of_week=body.day_of_week,
        day_of_month=body.day_of_month,
        month_of_year=body.month_of_year,
        start_date=body.start_date,
        today=today,
    )
    if next_date is None:
        raise HTTPException(422, "Could not compute a next payment date from this schedule")
    if body.end_date and next_date > body.end_date:
        raise HTTPException(422, "Schedule would complete before its first cycle (check end_date)")

    schedule = ScheduledPayment(
        reference_id=str(uuid.uuid4()),
        creator_id=creator.id,
        receiver_id=receiver.id,
        label=body.label,
        amount=body.amount,
        note=body.note,
        frequency=freq,
        specific_date=body.specific_date,
        day_of_week=body.day_of_week,
        day_of_month=body.day_of_month,
        month_of_year=body.month_of_year,
        start_date=body.start_date,
        end_date=body.end_date,
        reminder_days_before=body.reminder_days_before,
        reminder_on_due_day=body.reminder_on_due_day,
        status=ScheduleStatus.active,
        next_payment_date=next_date,
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)

    await write_audit_log(
        db, "SCHEDULED_PAYMENT_CREATED", actor_id=creator.id, target_id=receiver.id,
        entity_type="scheduled_payment", entity_id=schedule.id,
    )

    return CreateScheduledPaymentResponse(
        reference_id=schedule.reference_id,
        label=schedule.label,
        amount=float(schedule.amount),
        frequency=schedule.frequency.value,
        next_payment_date=schedule.next_payment_date,
        receiver=ReceiverBrief(full_name=receiver.full_name, mobile_last4=receiver.mobile_number[-4:]),
    )


async def _owned(db: AsyncSession, schedule_id: int, user_id: int) -> ScheduledPayment:
    s = (
        await db.execute(select(ScheduledPayment).where(ScheduledPayment.id == schedule_id))
    ).scalar_one_or_none()
    if not s or s.creator_id != user_id:
        raise HTTPException(404, "Scheduled payment not found")
    return s


async def list_scheduled_payments(db: AsyncSession, user: User) -> ScheduledPaymentListResponse:
    rows = (
        (
            await db.execute(
                select(ScheduledPayment)
                .where(ScheduledPayment.creator_id == user.id)
                .order_by(ScheduledPayment.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    items = []
    for s in rows:
        items.append(_to_item(s, await _receiver_brief(db, s.receiver_id)))
    return ScheduledPaymentListResponse(scheduled_payments=items)


async def get_detail(db: AsyncSession, user: User, schedule_id: int) -> ScheduledPaymentDetailResponse:
    s = await _owned(db, schedule_id, user.id)
    logs = (
        (
            await db.execute(
                select(ScheduledPaymentLog)
                .where(ScheduledPaymentLog.scheduled_payment_id == s.id)
                .order_by(ScheduledPaymentLog.cycle_date.desc(), ScheduledPaymentLog.id.desc())
            )
        )
        .scalars()
        .all()
    )
    base = _to_item(s, await _receiver_brief(db, s.receiver_id)).model_dump()
    return ScheduledPaymentDetailResponse(**base, history=[_log_item(x) for x in logs])


async def update_scheduled_payment(
    db: AsyncSession, user: User, schedule_id: int, body
) -> ScheduledPaymentItem:
    s = await _owned(db, schedule_id, user.id)
    if s.status in (ScheduleStatus.cancelled, ScheduleStatus.completed):
        raise HTTPException(422, f"Cannot edit a {s.status.value} schedule")

    if body.label is not None:
        s.label = body.label
    if body.amount is not None:
        s.amount = body.amount  # applies from the NEXT cycle
    if body.reminder_days_before is not None:
        s.reminder_days_before = body.reminder_days_before
    if body.note is not None:
        s.note = body.note
    await db.commit()
    await db.refresh(s)
    await write_audit_log(
        db, "SCHEDULED_PAYMENT_UPDATED", actor_id=user.id, entity_type="scheduled_payment", entity_id=s.id
    )
    return _to_item(s, await _receiver_brief(db, s.receiver_id))


async def pause(db: AsyncSession, user: User, schedule_id: int) -> dict:
    s = await _owned(db, schedule_id, user.id)
    if s.status != ScheduleStatus.active:
        raise HTTPException(422, f"Only an active schedule can be paused (currently {s.status.value})")
    s.status = ScheduleStatus.paused
    await db.commit()
    await write_audit_log(
        db, "SCHEDULED_PAYMENT_PAUSED", actor_id=user.id, entity_type="scheduled_payment", entity_id=s.id
    )
    return {"status": "paused"}


async def resume(db: AsyncSession, user: User, schedule_id: int) -> dict:
    s = await _owned(db, schedule_id, user.id)
    if s.status != ScheduleStatus.paused:
        raise HTTPException(422, f"Only a paused schedule can be resumed (currently {s.status.value})")

    next_date = compute_next_payment_date(
        s.frequency,
        specific_date=s.specific_date,
        day_of_week=s.day_of_week,
        day_of_month=s.day_of_month,
        month_of_year=s.month_of_year,
        start_date=None,
        today=date.today(),
    )
    if s.frequency == ScheduleFrequency.one_time and (
        s.specific_date is None or s.specific_date <= date.today()
    ):
        raise HTTPException(422, "This one-time payment's date has already passed")
    if next_date and s.end_date and next_date > s.end_date:
        s.status = ScheduleStatus.completed
        s.next_payment_date = None
        await db.commit()
        raise HTTPException(422, "Schedule has passed its end_date and is now completed")

    s.status = ScheduleStatus.active
    s.next_payment_date = next_date
    s.last_reminder_sent_date = None
    await db.commit()
    await write_audit_log(
        db, "SCHEDULED_PAYMENT_RESUMED", actor_id=user.id, entity_type="scheduled_payment", entity_id=s.id
    )
    return {"next_payment_date": next_date.isoformat() if next_date else None}


async def cancel(db: AsyncSession, user: User, schedule_id: int) -> dict:
    s = await _owned(db, schedule_id, user.id)
    if s.status in (ScheduleStatus.cancelled, ScheduleStatus.completed):
        raise HTTPException(422, f"Schedule is already {s.status.value}")
    s.status = ScheduleStatus.cancelled
    s.next_payment_date = None
    await db.commit()
    await write_audit_log(
        db, "SCHEDULED_PAYMENT_CANCELLED", actor_id=user.id, entity_type="scheduled_payment", entity_id=s.id
    )
    return {"status": "cancelled"}


async def pay_now(
    db: AsyncSession, redis, user: User, schedule_id: int, pin: str, background_tasks=None
) -> PayNowResponse:
    s = await _owned(db, schedule_id, user.id)
    if s.status != ScheduleStatus.active:
        raise HTTPException(422, f"Schedule is {s.status.value} — cannot pay")
    if s.next_payment_date is None:
        raise HTTPException(422, "This schedule has no upcoming payment")

    receiver = (await db.execute(select(User).where(User.id == s.receiver_id))).scalar_one_or_none()
    receiver = _check_receiver_valid(receiver, user.id)

    cycle_date = s.next_payment_date

    # Full transfer with every existing safety check (PIN lockout, cooldown,
    # daily limit, idempotency, atomic debit/credit).
    result = await send_money(
        db,
        redis,
        user,
        idempotency_key=f"scheduled-{s.reference_id}-{cycle_date.isoformat()}",
        receiver_identifier=str(receiver.id),
        amount=float(s.amount),
        pin=pin,
        note=(s.note or s.label),
        extra_confirmed=True,
        initiated_via=InitiatedVia.web,
        tx_type=TransactionType.scheduled_payment,
        background_tasks=background_tasks,
    )

    db.add(
        ScheduledPaymentLog(
            scheduled_payment_id=s.id,
            cycle_date=cycle_date,
            status=ScheduledPaymentLogStatus.paid,
            transaction_id=result.transaction_id,
            paid_at=_now(),
        )
    )
    s.last_paid_at = _now()
    s.total_paid_count += 1
    if s.frequency == ScheduleFrequency.one_time:
        s.status = ScheduleStatus.completed
        s.next_payment_date = None
    else:
        nxt = advance_to_next_cycle(s)
        if nxt is None:
            s.status = ScheduleStatus.completed
            s.next_payment_date = None
        else:
            s.next_payment_date = nxt
        s.last_reminder_sent_date = None
    await db.commit()
    await db.refresh(s)

    await send_notification(
        db, s.creator_id, NotificationType.scheduled_paid,
        "Scheduled payment sent",
        f"Scheduled payment '{s.label}' sent successfully. Next due: {s.next_payment_date or 'N/A'}",
        s.reference_id,
    )
    await send_notification(
        db, s.receiver_id, NotificationType.scheduled_paid,
        "Scheduled payment received",
        f"Received ৳{float(s.amount):,.2f} — scheduled payment from {user.full_name} ({s.label})",
        s.reference_id,
    )
    await write_audit_log(
        db, "SCHEDULED_PAYMENT_PAID", actor_id=user.id, target_id=s.receiver_id,
        entity_type="scheduled_payment", entity_id=s.id,
        payload={"transaction_id": result.transaction_id, "cycle_date": cycle_date.isoformat()},
    )

    return PayNowResponse(
        transaction_id=result.transaction_id,
        reference_id=result.reference_id,
        new_balance=result.new_balance,
        next_payment_date=s.next_payment_date,
    )


async def get_history(
    db: AsyncSession, user: User, schedule_id: int, page: int, per_page: int
) -> ScheduledPaymentHistoryResponse:
    s = await _owned(db, schedule_id, user.id)
    total = (
        await db.execute(
            select(func.count())
            .select_from(ScheduledPaymentLog)
            .where(ScheduledPaymentLog.scheduled_payment_id == s.id)
        )
    ).scalar_one()
    rows = (
        (
            await db.execute(
                select(ScheduledPaymentLog)
                .where(ScheduledPaymentLog.scheduled_payment_id == s.id)
                .order_by(ScheduledPaymentLog.cycle_date.desc(), ScheduledPaymentLog.id.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        )
        .scalars()
        .all()
    )
    return ScheduledPaymentHistoryResponse(
        total=total, page=page, per_page=per_page, logs=[_log_item(x) for x in rows]
    )


# ── Reminder engine (Celery Beat @ 08:00 Asia/Dhaka, also callable directly) ──
async def _receiver_name(db: AsyncSession, receiver_id: int) -> str:
    u = (await db.execute(select(User).where(User.id == receiver_id))).scalar_one_or_none()
    return u.full_name if u else "the recipient"


async def mark_as_missed(db: AsyncSession, schedule: ScheduledPayment) -> None:
    """Due date passed without payment. Log it and advance the cycle."""
    db.add(
        ScheduledPaymentLog(
            scheduled_payment_id=schedule.id,
            cycle_date=schedule.next_payment_date,
            status=ScheduledPaymentLogStatus.missed,
        )
    )
    next_date = advance_to_next_cycle(schedule)
    if next_date:
        schedule.next_payment_date = next_date
        schedule.last_reminder_sent_date = None
    else:
        schedule.status = ScheduleStatus.completed
        schedule.next_payment_date = None
    await db.commit()

    await send_notification(
        db, schedule.creator_id, NotificationType.scheduled_missed,
        f"Missed payment: {schedule.label}",
        f"You missed your scheduled payment of ৳{float(schedule.amount):,.2f}. "
        f"Next due: {next_date or 'N/A'}",
        schedule.reference_id,
    )


async def run_reminder_scan(db: AsyncSession, today: date | None = None) -> dict:
    """Scan active schedules whose due date is within their reminder window and
    send at most one reminder per cycle (Redis-deduplicated). Overdue cycles are
    marked missed and advanced."""
    today = today or date.today()
    reminders_sent = 0
    missed = 0

    schedules = (
        (
            await db.execute(
                select(ScheduledPayment).where(
                    ScheduledPayment.status == ScheduleStatus.active,
                    ScheduledPayment.next_payment_date.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )

    for s in schedules:
        window_start = s.next_payment_date - timedelta(days=s.reminder_days_before)
        days_until = (s.next_payment_date - today).days

        if days_until < 0:
            await mark_as_missed(db, s)
            missed += 1
            continue

        if today < window_start:
            continue  # not in the reminder window yet

        redis_key = f"sched:reminded:{s.id}:{s.next_payment_date.isoformat()}"
        try:
            if await redis_client.get(redis_key):
                continue
        except Exception:  # noqa: BLE001 - redis outage must not stop the scan
            pass

        receiver_name = await _receiver_name(db, s.receiver_id)
        if days_until == 0 and s.reminder_on_due_day:
            ntype = NotificationType.scheduled_due_today
            title = f"Payment DUE TODAY: {s.label}"
            body = f"'{s.label}' of ৳{float(s.amount):,.2f} to {receiver_name} is DUE TODAY. Pay Now."
        elif days_until == 0:
            continue  # due today but due-day reminder disabled
        else:
            ntype = NotificationType.scheduled_reminder
            title = f"Upcoming payment: {s.label}"
            body = (
                f"Your payment '{s.label}' of ৳{float(s.amount):,.2f} to {receiver_name} "
                f"is due in {days_until} day(s). Pay Now."
            )

        await send_notification(db, s.creator_id, ntype, title, body, s.reference_id)

        s.last_reminder_sent_date = today
        db.add(
            ScheduledPaymentLog(
                scheduled_payment_id=s.id,
                cycle_date=s.next_payment_date,
                status=ScheduledPaymentLogStatus.reminder_sent,
            )
        )
        await db.commit()

        try:
            await redis_client.setex(redis_key, 82800, "1")  # 23h — cleared before next 08:00 run
        except Exception:  # noqa: BLE001
            pass
        reminders_sent += 1

    return {"scanned": len(schedules), "reminders_sent": reminders_sent, "missed": missed}
