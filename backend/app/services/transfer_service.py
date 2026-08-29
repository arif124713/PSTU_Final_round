import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import verify_secret
from app.models.notification import NotificationType
from app.models.transaction import (
    DraftStatus,
    InitiatedVia,
    Transaction,
    TransactionDraft,
    TransactionStatus,
    TransactionType,
)
from app.models.user import User
from app.schemas.transaction import (
    Pagination,
    ReceiverInfo,
    SendMoneyResponse,
    TransactionDetailResponse,
    TransactionHistoryResponse,
    TransactionHistorySummary,
    TransactionListItem,
    TransactionPartyInfo,
    ValidateReceiverResponse,
)
from app.services import fraud_service
from app.services.audit_service import write_audit_log
from app.services.notification_service import send_notification


async def resolve_receiver(db: AsyncSession, identifier: str) -> User | None:
    identifier = identifier.strip()
    if identifier.isdigit() and len(identifier) < 11:
        # short numeric string -> treat as user id
        user = (await db.execute(select(User).where(User.id == int(identifier)))).scalar_one_or_none()
        if user:
            return user

    by_mobile = (await db.execute(select(User).where(User.mobile_number == identifier))).scalar_one_or_none()
    if by_mobile:
        return by_mobile

    # Fall back to a name search (used by the AI agent, which is handed names,
    # not mobile numbers, e.g. "send 2000 to Ankon"). Exact match preferred;
    # otherwise the first partial match.
    exact_name = (await db.execute(select(User).where(User.full_name == identifier))).scalar_one_or_none()
    if exact_name:
        return exact_name

    return (
        await db.execute(select(User).where(User.full_name.ilike(f"%{identifier}%")).limit(1))
    ).scalar_one_or_none()


def _check_receiver_valid(receiver: User | None, sender_id: int) -> User:
    if not receiver:
        raise HTTPException(404, "Account not found")
    if not receiver.is_active:
        raise HTTPException(422, "Receiver account is not active")
    if receiver.is_frozen:
        raise HTTPException(422, "Receiver account is currently frozen")
    if receiver.id == sender_id:
        raise HTTPException(422, "Cannot send money to yourself")
    return receiver


async def validate_receiver(db: AsyncSession, sender_id: int, identifier: str) -> ValidateReceiverResponse:
    receiver = await resolve_receiver(db, identifier)
    receiver = _check_receiver_valid(receiver, sender_id)
    return ValidateReceiverResponse(
        valid=True,
        receiver=ReceiverInfo(
            id=receiver.id,
            full_name=receiver.full_name,
            mobile_last4=receiver.mobile_number[-4:],
            is_active=receiver.is_active,
        ),
    )


async def _execute_atomic_transfer(
    db: AsyncSession,
    sender_id: int,
    receiver_id: int,
    amount: Decimal,
    note: str | None,
    initiated_via: InitiatedVia,
    flagged: bool,
    flag_reason: str | None,
    tx_type: TransactionType = TransactionType.transfer,
) -> Transaction:
    """The critical section: pessimistic row lock + debit/credit + insert, all-or-nothing."""
    sender = (
        await db.execute(select(User).where(User.id == sender_id).with_for_update())
    ).scalar_one()

    if sender.is_frozen:
        raise HTTPException(423, "Your account has been frozen")
    if sender.balance < amount:
        raise HTTPException(422, "Insufficient balance")

    receiver = (
        await db.execute(select(User).where(User.id == receiver_id).with_for_update())
    ).scalar_one()

    sender.balance -= amount
    receiver.balance += amount

    tx = Transaction(
        reference_id=str(uuid.uuid4()),
        sender_id=sender_id,
        receiver_id=receiver_id,
        amount=amount,
        note=note,
        status=TransactionStatus.completed,
        type=tx_type,
        initiated_via=initiated_via,
        flagged=flagged,
        flag_reason=flag_reason,
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    await db.refresh(sender)
    return tx


async def send_money(
    db: AsyncSession,
    redis: Redis,
    current_user: User,
    idempotency_key: str,
    receiver_identifier: str,
    amount: float,
    pin: str,
    note: str | None,
    extra_confirmed: bool,
    initiated_via: InitiatedVia = InitiatedVia.web,
    tx_type: TransactionType = TransactionType.transfer,
    background_tasks=None,
) -> SendMoneyResponse:
    # Step 1: idempotency
    idem_key = f"idem:{current_user.id}:{idempotency_key}"
    cached = await redis.get(idem_key)
    if cached:
        return SendMoneyResponse(**json.loads(cached))

    # Step 2: resolve + validate receiver
    receiver = await resolve_receiver(db, receiver_identifier)
    receiver = _check_receiver_valid(receiver, current_user.id)

    # Step 3: amount limits
    if amount > settings.max_single_transfer_bdt:
        raise HTTPException(422, f"Exceeds single transfer limit of {settings.max_single_transfer_bdt}")

    # Step 4-7: Redis guardrails
    await fraud_service.check_cooldown(redis, current_user.id, receiver.id)
    await fraud_service.check_daily_limit(redis, current_user.id, amount)
    velocity_flag = await fraud_service.check_velocity(redis, current_user.id)
    unusual_flag = await fraud_service.check_unusual_amount(redis, current_user.id, amount, extra_confirmed)

    # Step 8: PIN
    await write_audit_log(db, "TRANSFER_INITIATED", actor_id=current_user.id, target_id=receiver.id)
    await fraud_service.check_pin(redis, current_user.id, pin, current_user.pin_hash, verify_secret)

    flagged = velocity_flag or unusual_flag
    flag_reason = "velocity_exceeded" if velocity_flag else ("unusual_amount" if unusual_flag else None)

    amount_decimal = Decimal(str(amount))

    try:
        tx = await _execute_atomic_transfer(
            db, current_user.id, receiver.id, amount_decimal, note, initiated_via, flagged, flag_reason, tx_type
        )
    except HTTPException:
        await write_audit_log(db, "TRANSFER_FAILED", actor_id=current_user.id, target_id=receiver.id)
        raise

    # Step 11: post-transaction state
    await fraud_service.set_post_transfer_state(redis, current_user.id, receiver.id, amount)
    if flagged:
        await write_audit_log(db, "VELOCITY_FLAGGED", actor_id=current_user.id, entity_type="transaction", entity_id=tx.id, payload={"reason": flag_reason})

    response = SendMoneyResponse(
        transaction_id=tx.id,
        reference_id=tx.reference_id,
        amount=float(tx.amount),
        receiver_name=receiver.full_name,
        receiver_id=receiver.id,
        new_balance=float((await db.execute(select(User.balance).where(User.id == current_user.id))).scalar_one()),
        status="completed",
        timestamp=tx.completed_at.isoformat() if tx.completed_at else datetime.now(timezone.utc).isoformat(),
    )

    await redis.setex(idem_key, 86400, response.model_dump_json())

    # After a successful credit, settle any pending group-payment debts the
    # receiver owes (FIFO, partial). Runs off the request path.
    if background_tasks is not None:
        from app.services.debt_service import settle_pending_debts_bg

        background_tasks.add_task(settle_pending_debts_bg, receiver.id)

    await send_notification(
        db, receiver.id, NotificationType.money_received,
        "Money received", f"You received ৳{amount:,.2f} from {current_user.full_name}", tx.reference_id,
    )
    await send_notification(
        db, current_user.id, NotificationType.money_sent,
        "Money sent", f"৳{amount:,.2f} sent to {receiver.full_name} successfully", tx.reference_id,
    )
    await write_audit_log(db, "TRANSFER_COMPLETED", actor_id=current_user.id, target_id=receiver.id, entity_type="transaction", entity_id=tx.id)

    return response


async def create_draft(
    db: AsyncSession,
    redis: Redis,
    current_user: User,
    receiver_id: int,
    amount: float,
    note: str | None,
) -> TransactionDraft:
    """Called by the AI agent tool `initiate_transfer`. Runs the non-PIN pre-checks
    and stages a draft. No PIN is involved at any point here."""
    receiver = (await db.execute(select(User).where(User.id == receiver_id))).scalar_one_or_none()
    receiver = _check_receiver_valid(receiver, current_user.id)

    if amount > settings.max_single_transfer_bdt:
        raise HTTPException(422, f"Exceeds single transfer limit of {settings.max_single_transfer_bdt}")
    await fraud_service.check_cooldown(redis, current_user.id, receiver.id)
    await fraud_service.check_daily_limit(redis, current_user.id, amount)
    if current_user.balance < Decimal(str(amount)):
        raise HTTPException(422, "Insufficient balance")

    draft = TransactionDraft(
        draft_id=str(uuid.uuid4()),
        sender_id=current_user.id,
        receiver_id=receiver.id,
        receiver_name=receiver.full_name,
        amount=Decimal(str(amount)),
        note=note,
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).replace(tzinfo=None),
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return draft


async def confirm_draft(
    db: AsyncSession, redis: Redis, current_user: User, draft_id: str, pin: str, background_tasks=None
) -> SendMoneyResponse:
    draft = (
        await db.execute(select(TransactionDraft).where(TransactionDraft.draft_id == draft_id))
    ).scalar_one_or_none()

    if not draft or draft.sender_id != current_user.id:
        raise HTTPException(404, "Draft not found")
    if draft.status != DraftStatus.pending_pin:
        raise HTTPException(422, f"Draft is not pending confirmation (status: {draft.status.value})")
    if draft.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        draft.status = DraftStatus.expired
        await db.commit()
        raise HTTPException(422, "Draft has expired. Please ask again.")

    await fraud_service.check_pin(redis, current_user.id, pin, current_user.pin_hash, verify_secret)

    tx = await _execute_atomic_transfer(
        db, draft.sender_id, draft.receiver_id, draft.amount, draft.note, InitiatedVia.ai_agent, False, None
    )

    draft.status = DraftStatus.confirmed
    await db.commit()

    if background_tasks is not None:
        from app.services.debt_service import settle_pending_debts_bg

        background_tasks.add_task(settle_pending_debts_bg, draft.receiver_id)

    await fraud_service.set_post_transfer_state(redis, draft.sender_id, draft.receiver_id, float(draft.amount))

    receiver = (await db.execute(select(User).where(User.id == draft.receiver_id))).scalar_one()
    sender_balance = (await db.execute(select(User.balance).where(User.id == current_user.id))).scalar_one()

    await send_notification(
        db, draft.receiver_id, NotificationType.money_received,
        "Money received", f"You received ৳{float(draft.amount):,.2f} from {current_user.full_name}", tx.reference_id,
    )
    await write_audit_log(db, "TRANSFER_COMPLETED", actor_id=current_user.id, target_id=draft.receiver_id, entity_type="transaction", entity_id=tx.id)

    return SendMoneyResponse(
        transaction_id=tx.id,
        reference_id=tx.reference_id,
        amount=float(tx.amount),
        receiver_name=receiver.full_name,
        receiver_id=receiver.id,
        new_balance=float(sender_balance),
        status="completed",
        timestamp=tx.completed_at.isoformat() if tx.completed_at else datetime.now(timezone.utc).isoformat(),
    )


async def get_history(
    db: AsyncSession,
    user: User,
    type_: str,
    status_: str,
    from_date: str | None,
    to_date: str | None,
    page: int,
    per_page: int,
) -> TransactionHistoryResponse:
    conditions = []
    if type_ == "sent":
        conditions.append(Transaction.sender_id == user.id)
    elif type_ == "received":
        conditions.append(Transaction.receiver_id == user.id)
    else:
        conditions.append(or_(Transaction.sender_id == user.id, Transaction.receiver_id == user.id))

    if status_ != "all":
        conditions.append(Transaction.status == TransactionStatus(status_))
    if from_date:
        conditions.append(Transaction.created_at >= from_date)
    if to_date:
        conditions.append(Transaction.created_at <= to_date + " 23:59:59")

    base_query = select(Transaction).where(*conditions).order_by(Transaction.created_at.desc())
    total = (await db.execute(select(func.count()).select_from(base_query.subquery()))).scalar_one()

    rows = (
        await db.execute(base_query.offset((page - 1) * per_page).limit(per_page))
    ).scalars().all()

    counterparty_ids = {tx.receiver_id if tx.sender_id == user.id else tx.sender_id for tx in rows}
    counterparties = {}
    if counterparty_ids:
        users = (await db.execute(select(User).where(User.id.in_(counterparty_ids)))).scalars().all()
        counterparties = {u.id: u for u in users}

    items = []
    for tx in rows:
        is_sender = tx.sender_id == user.id
        counterparty = counterparties.get(tx.receiver_id if is_sender else tx.sender_id)
        items.append(
            TransactionListItem(
                reference_id=tx.reference_id,
                amount=float(tx.amount),
                counterparty_name=counterparty.full_name if counterparty else "Unknown",
                direction="sent" if is_sender else "received",
                note=tx.note,
                status=tx.status.value,
                created_at=tx.created_at,
            )
        )

    total_sent = (
        await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.sender_id == user.id, Transaction.status == TransactionStatus.completed
            )
        )
    ).scalar_one()
    total_received = (
        await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.receiver_id == user.id, Transaction.status == TransactionStatus.completed
            )
        )
    ).scalar_one()

    return TransactionHistoryResponse(
        transactions=items,
        pagination=Pagination(
            total=total, page=page, per_page=per_page, total_pages=max((total + per_page - 1) // per_page, 1)
        ),
        summary=TransactionHistorySummary(
            total_sent=float(total_sent), total_received=float(total_received), period=datetime.now().strftime("%Y-%m")
        ),
    )


async def get_detail(db: AsyncSession, user: User, reference_id: str) -> TransactionDetailResponse:
    tx = (
        await db.execute(select(Transaction).where(Transaction.reference_id == reference_id))
    ).scalar_one_or_none()
    if not tx or (tx.sender_id != user.id and tx.receiver_id != user.id):
        raise HTTPException(404, "Transaction not found")

    sender = (await db.execute(select(User).where(User.id == tx.sender_id))).scalar_one()
    receiver = (await db.execute(select(User).where(User.id == tx.receiver_id))).scalar_one()

    can_dispute = (
        tx.status == TransactionStatus.completed
        and tx.sender_id == user.id
        and tx.created_at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=settings.dispute_window_days)
    )

    return TransactionDetailResponse(
        reference_id=tx.reference_id,
        amount=float(tx.amount),
        sender=TransactionPartyInfo(name=sender.full_name, mobile_last4=sender.mobile_number[-4:]),
        receiver=TransactionPartyInfo(name=receiver.full_name, mobile_last4=receiver.mobile_number[-4:]),
        note=tx.note,
        status=tx.status.value,
        initiated_via=tx.initiated_via.value,
        created_at=tx.created_at,
        can_dispute=can_dispute,
    )
