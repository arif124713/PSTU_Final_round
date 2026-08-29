"""Group payments — a creator splits a bill equally and collects each member's share.

A member's "Agree" (with PIN) is consent to the amount AND pre-authorisation of
future auto-deduction if their balance is short. Immediate payers transfer at once;
short members get a ``member_debt`` that auto-settles (partially, FIFO) whenever they
next receive funds — see ``debt_service``.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_secret
from app.models.group_payment import (
    DebtPayment,
    GroupMemberStatus,
    GroupPayment,
    GroupPaymentMember,
    GroupPaymentStatus,
    MemberDebt,
    MemberDebtStatus,
)
from app.models.notification import NotificationType
from app.models.transaction import InitiatedVia, Transaction, TransactionStatus, TransactionType
from app.models.user import User
from app.schemas.group_payment import (
    CancelGroupResponse,
    CreateGroupPaymentResponse,
    DebtHistoryItem,
    DebtHistoryResponse,
    GroupAsCreatorItem,
    GroupAsMemberItem,
    GroupMemberBrief,
    GroupPaymentDetailResponse,
    GroupPaymentListResponse,
    MessageResponse,
    MyDebtItem,
    MyDebtsResponse,
    OwedToMeItem,
    OwedToMeResponse,
    RespondGroupPaymentResponse,
)
from app.services import fraud_service
from app.services.audit_service import write_audit_log
from app.services.debt_service import check_group_completion
from app.services.notification_service import send_notification
from app.services.transfer_service import resolve_receiver, send_money

EXPIRY_HOURS = 72
MIN_PER_PERSON = Decimal("1.00")
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _load_group(db: AsyncSession, group_id: int) -> GroupPayment:
    gp = (await db.execute(select(GroupPayment).where(GroupPayment.id == group_id))).scalar_one_or_none()
    if not gp:
        raise HTTPException(404, "Group payment not found")
    return gp


async def _users_by_id(db: AsyncSession, ids: set[int]) -> dict[int, User]:
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: u for u in rows}


# ── Create ─────────────────────────────────────────────────────────────────
async def create_group_payment(
    db: AsyncSession, redis: Redis, creator: User, body
) -> CreateGroupPaymentResponse:
    if body.idempotency_key:
        idem = f"group:idem:{creator.id}:{body.idempotency_key}"
        if await redis.get(idem):
            raise HTTPException(409, "Duplicate request — this group payment was already created")

    if body.total_amount <= 0:
        raise HTTPException(422, "Total amount must be greater than 0")
    if not body.members:
        raise HTTPException(422, "At least one member is required")
    if len(body.members) > 20:
        raise HTTPException(422, "A group payment can have at most 20 members")

    # Resolve members
    resolved: list[User] = []
    seen_ids: set[int] = set()
    for ident in body.members:
        u = await resolve_receiver(db, ident)
        if not u:
            raise HTTPException(404, f"Member not found: {ident}")
        if not u.is_active:
            raise HTTPException(422, f"Member account is not active: {u.full_name}")
        if u.id == creator.id:
            raise HTTPException(422, "You cannot add yourself as a member")
        if u.id in seen_ids:
            raise HTTPException(422, "Duplicate member in list")
        seen_ids.add(u.id)
        resolved.append(u)

    n = len(resolved)
    total = Decimal(str(body.total_amount))
    divisor = n + 1 if body.creator_included else n
    per_person = (total / divisor).quantize(_CENT, rounding=ROUND_HALF_UP)
    if per_person < MIN_PER_PERSON:
        raise HTTPException(422, "Per-person amount is too small. Minimum per person: ৳1.00")

    gp = GroupPayment(
        reference_id=str(uuid.uuid4()),
        title=body.title,
        creator_id=creator.id,
        total_amount=total,
        per_person_amount=per_person,
        member_count=n,
        creator_included=body.creator_included,
        collected_amount=_ZERO,
        note=body.note,
        status=GroupPaymentStatus.open,
        expires_at=_now() + timedelta(hours=EXPIRY_HOURS),
    )
    db.add(gp)
    await db.flush()

    members: list[GroupPaymentMember] = []
    for u in resolved:
        m = GroupPaymentMember(
            group_payment_id=gp.id,
            member_id=u.id,
            amount_owed=per_person,
            status=GroupMemberStatus.pending,
        )
        db.add(m)
        members.append(m)
    await db.commit()
    await db.refresh(gp)

    for u in resolved:
        await send_notification(
            db, u.id, NotificationType.group_invite,
            f"Group payment: {gp.title}",
            f"{creator.full_name} added you to '{gp.title}'. Your share: ৳{float(per_person):,.2f}. "
            f"Tap to agree or decline.",
            gp.reference_id,
        )

    if body.idempotency_key:
        await redis.setex(f"group:idem:{creator.id}:{body.idempotency_key}", 86400, "1")

    await write_audit_log(
        db, "GROUP_PAYMENT_CREATED", actor_id=creator.id,
        entity_type="group_payment", entity_id=gp.id,
        payload={"total": float(total), "members": n, "per_person": float(per_person)},
    )

    return CreateGroupPaymentResponse(
        group_payment_id=gp.id,
        reference_id=gp.reference_id,
        title=gp.title,
        total_amount=float(gp.total_amount),
        per_person_amount=float(gp.per_person_amount),
        member_count=gp.member_count,
        expires_at=gp.expires_at,
        members=[
            GroupMemberBrief(
                member_id=u.id,
                full_name=u.full_name,
                mobile_last4=u.mobile_number[-4:],
                status="pending",
                amount_owed=float(per_person),
            )
            for u in resolved
        ],
    )


# ── Respond (agree / decline) ──────────────────────────────────────────────
async def respond(
    db: AsyncSession, redis: Redis, member: User, group_id: int, body, background_tasks=None
) -> RespondGroupPaymentResponse:
    gp = await _load_group(db, group_id)
    if gp.status != GroupPaymentStatus.open:
        raise HTTPException(422, f"This group payment is {gp.status.value}")
    if gp.expires_at < _now():
        raise HTTPException(422, "This group payment has expired")

    gpm = (
        await db.execute(
            select(GroupPaymentMember).where(
                GroupPaymentMember.group_payment_id == gp.id,
                GroupPaymentMember.member_id == member.id,
            )
        )
    ).scalar_one_or_none()
    if not gpm:
        raise HTTPException(403, "You are not a member of this group payment")
    if gpm.status != GroupMemberStatus.pending:
        raise HTTPException(422, f"You have already responded ({gpm.status.value})")

    creator = (await db.execute(select(User).where(User.id == gp.creator_id))).scalar_one()

    # ── Decline ───────────────────────────────────────────────────────────
    if body.action == "decline":
        gpm.status = GroupMemberStatus.declined
        gpm.responded_at = _now()
        await db.commit()
        await send_notification(
            db, gp.creator_id, NotificationType.group_member_declined,
            "Member declined",
            f"{member.full_name} declined their share of '{gp.title}'",
            gp.reference_id,
        )
        await write_audit_log(
            db, "GROUP_MEMBER_DECLINED", actor_id=member.id, target_id=gp.creator_id,
            entity_type="group_payment", entity_id=gp.id,
        )
        return RespondGroupPaymentResponse(status="declined", detail="You declined this share.")

    # ── Agree ─────────────────────────────────────────────────────────────
    if not body.pin:
        raise HTTPException(422, "PIN is required to agree")

    amount_owed = Decimal(str(gpm.amount_owed))
    fresh_balance = (
        await db.execute(select(User.balance).where(User.id == member.id))
    ).scalar_one()

    case_a = Decimal(str(fresh_balance)) >= amount_owed

    if case_a:
        try:
            result = await send_money(
                db,
                redis,
                member,
                idempotency_key=f"group-{gp.reference_id}-{member.id}",
                receiver_identifier=str(creator.id),
                amount=float(amount_owed),
                pin=body.pin,
                note=f"Group payment: {gp.title}",
                extra_confirmed=True,
                initiated_via=InitiatedVia.web,
                tx_type=TransactionType.group_payment,
                background_tasks=background_tasks,
            )
        except HTTPException as exc:
            # Balance dropped between the read and the locked transfer -> fall to CASE B.
            if exc.status_code == 422 and "balance" in str(exc.detail).lower():
                case_a = False
            else:
                raise

    if case_a:
        gpm.status = GroupMemberStatus.agreed_paid
        gpm.agreed_at = _now()
        gpm.paid_at = _now()
        gpm.responded_at = _now()
        gp.collected_amount = Decimal(str(gp.collected_amount)) + amount_owed
        await db.commit()

        await send_notification(
            db, gp.creator_id, NotificationType.group_member_paid,
            "Member paid",
            f"{member.full_name} paid their ৳{float(amount_owed):,.2f} share of '{gp.title}'",
            gp.reference_id,
        )
        await send_notification(
            db, member.id, NotificationType.group_invite_agreed,
            "Share paid",
            f"You paid ৳{float(amount_owed):,.2f} for '{gp.title}'. Balance: ৳{result.new_balance:,.2f}",
            gp.reference_id,
        )
        await check_group_completion(db, gp.id)
        await write_audit_log(
            db, "GROUP_MEMBER_PAID", actor_id=member.id, target_id=gp.creator_id,
            entity_type="group_payment", entity_id=gp.id,
            payload={"amount": float(amount_owed), "transaction_id": result.transaction_id},
        )
        return RespondGroupPaymentResponse(
            status="agreed_paid",
            detail=f"You paid ৳{float(amount_owed):,.2f} for '{gp.title}'.",
            new_balance=result.new_balance,
        )

    # ── CASE B: no money moves, a pre-authorised debt is recorded ──────────
    await fraud_service.check_pin(redis, member.id, body.pin, member.pin_hash, verify_secret)

    debt = MemberDebt(
        reference_id=str(uuid.uuid4()),
        group_payment_id=gp.id,
        group_payment_member_id=gpm.id,
        debtor_id=member.id,
        creditor_id=gp.creator_id,
        original_amount=amount_owed,
        remaining_amount=amount_owed,
        status=MemberDebtStatus.pending,
        pre_authorized=True,
    )
    db.add(debt)
    await db.flush()

    gpm.status = GroupMemberStatus.agreed_debt
    gpm.agreed_at = _now()
    gpm.responded_at = _now()
    gpm.debt_id = debt.id
    await db.commit()
    await db.refresh(debt)

    await send_notification(
        db, gp.creator_id, NotificationType.group_member_agreed_debt,
        "Member agreed (debt)",
        f"{member.full_name} agreed but balance is low. Debt ৳{float(amount_owed):,.2f} recorded — "
        f"auto-pays when they receive funds.",
        gp.reference_id,
    )
    await send_notification(
        db, member.id, NotificationType.group_invite_agreed_debt,
        "Agreed — will auto-deduct",
        f"You agreed to pay ৳{float(amount_owed):,.2f} for '{gp.title}'. "
        f"Since your balance is low, it will auto-deduct when you receive money. No action needed.",
        gp.reference_id,
    )
    await write_audit_log(
        db, "GROUP_MEMBER_AGREED_DEBT", actor_id=member.id, target_id=gp.creator_id,
        entity_type="member_debt", entity_id=debt.id, payload={"amount": float(amount_owed)},
    )
    return RespondGroupPaymentResponse(
        status="agreed_debt",
        detail="Agreed. The amount will auto-deduct when you next receive money.",
        debt_reference_id=debt.reference_id,
    )


# ── Creator: remind a debtor ───────────────────────────────────────────────
async def remind(db: AsyncSession, redis: Redis, creator: User, group_id: int, member_id: int) -> MessageResponse:
    gp = await _load_group(db, group_id)
    if gp.creator_id != creator.id:
        raise HTTPException(403, "Only the creator can send reminders")

    gpm = (
        await db.execute(
            select(GroupPaymentMember).where(
                GroupPaymentMember.group_payment_id == gp.id,
                GroupPaymentMember.member_id == member_id,
            )
        )
    ).scalar_one_or_none()
    if not gpm:
        raise HTTPException(404, "Member not found in this group")
    if gpm.status == GroupMemberStatus.declined:
        raise HTTPException(422, "This member declined the payment.")
    if gpm.status != GroupMemberStatus.agreed_debt or not gpm.debt_id:
        raise HTTPException(422, "This member has no outstanding debt.")

    debt = (await db.execute(select(MemberDebt).where(MemberDebt.id == gpm.debt_id))).scalar_one()
    if debt.status not in (MemberDebtStatus.pending, MemberDebtStatus.partially_paid) or Decimal(
        str(debt.remaining_amount)
    ) <= _ZERO:
        raise HTTPException(422, "This member's debt is already settled.")

    throttle_key = f"group:reminder:{gp.id}:{member_id}"
    if await redis.get(throttle_key):
        raise HTTPException(429, "You can only send one reminder per 24 hours per member")

    await send_notification(
        db, member_id, NotificationType.group_debt_reminder,
        f"Reminder: {gp.title}",
        f"Reminder from {creator.full_name}: You still owe ৳{float(debt.remaining_amount):,.2f} for "
        f"'{gp.title}'. It will auto-deduct the next time you receive funds.",
        gp.reference_id,
    )
    gpm.last_reminder_sent_at = _now()
    await db.commit()
    await redis.setex(throttle_key, 86400, "1")
    return MessageResponse(message="Reminder sent")


# ── Creator: cancel a member's debt (settled externally) ───────────────────
async def cancel_debt(
    db: AsyncSession, creator: User, group_id: int, member_id: int, reason: str
) -> MessageResponse:
    gp = await _load_group(db, group_id)
    if gp.creator_id != creator.id:
        raise HTTPException(403, "Only the creator can cancel a debt")

    gpm = (
        await db.execute(
            select(GroupPaymentMember).where(
                GroupPaymentMember.group_payment_id == gp.id,
                GroupPaymentMember.member_id == member_id,
            )
        )
    ).scalar_one_or_none()
    if not gpm or gpm.status != GroupMemberStatus.agreed_debt or not gpm.debt_id:
        raise HTTPException(422, "This member's debt is already settled.")

    debt = (await db.execute(select(MemberDebt).where(MemberDebt.id == gpm.debt_id))).scalar_one()
    if debt.status not in (MemberDebtStatus.pending, MemberDebtStatus.partially_paid):
        raise HTTPException(422, "This member's debt is already settled.")

    remaining = Decimal(str(debt.remaining_amount))
    debt.status = MemberDebtStatus.cancelled
    debt.cancelled_at = _now()
    debt.cancelled_reason = reason
    gpm.status = GroupMemberStatus.debt_cancelled
    await db.commit()

    await check_group_completion(db, gp.id)

    await send_notification(
        db, member_id, NotificationType.group_debt_cancelled,
        "Debt cancelled",
        f"{creator.full_name} marked your ৳{float(remaining):,.2f} debt for '{gp.title}' as settled. "
        f"No further payment required.",
        gp.reference_id,
    )
    await send_notification(
        db, gp.creator_id, NotificationType.group_debt_cancelled,
        "Debt cancelled",
        f"Debt of ৳{float(remaining):,.2f} from this member for '{gp.title}' cancelled.",
        gp.reference_id,
    )
    await write_audit_log(
        db, "GROUP_DEBT_CANCELLED", actor_id=creator.id, target_id=member_id,
        entity_type="member_debt", entity_id=debt.id, payload={"reason": reason, "remaining": float(remaining)},
    )
    return MessageResponse(message="Debt cancelled")


# ── Creator: cancel the whole group payment (with refunds) ─────────────────
async def cancel_group(db: AsyncSession, creator: User, group_id: int, reason: str | None) -> CancelGroupResponse:
    gp = await _load_group(db, group_id)
    if gp.creator_id != creator.id:
        raise HTTPException(403, "Only the creator can cancel this group payment")
    if gp.status != GroupPaymentStatus.open:
        raise HTTPException(422, f"Group payment is {gp.status.value} — cannot cancel")

    members = (
        (
            await db.execute(
                select(GroupPaymentMember).where(GroupPaymentMember.group_payment_id == gp.id)
            )
        )
        .scalars()
        .all()
    )
    to_refund = [m for m in members if m.status == GroupMemberStatus.agreed_paid]
    total_to_refund = sum((Decimal(str(m.amount_owed)) for m in to_refund), _ZERO)

    # All-or-nothing: verify the creator can cover every refund before moving money.
    creator_row = (
        await db.execute(select(User).where(User.id == creator.id).with_for_update())
    ).scalar_one()
    if Decimal(str(creator_row.balance)) < total_to_refund:
        raise HTTPException(
            422,
            f"Insufficient balance to process all refunds. "
            f"Please ensure you have ৳{float(total_to_refund):,.2f} available.",
        )

    refunded = 0
    for m in members:
        member_user = (await db.execute(select(User).where(User.id == m.member_id))).scalar_one()
        if m.status == GroupMemberStatus.agreed_paid:
            amt = Decimal(str(m.amount_owed))
            locked_creator = (
                await db.execute(select(User).where(User.id == creator.id).with_for_update())
            ).scalar_one()
            locked_member = (
                await db.execute(select(User).where(User.id == m.member_id).with_for_update())
            ).scalar_one()
            locked_creator.balance = Decimal(str(locked_creator.balance)) - amt
            locked_member.balance = Decimal(str(locked_member.balance)) + amt
            tx = Transaction(
                reference_id=str(uuid.uuid4()),
                sender_id=creator.id,
                receiver_id=m.member_id,
                amount=amt,
                note=f"Group payment refund: {gp.title}",
                status=TransactionStatus.completed,
                type=TransactionType.group_payment_refund,
                initiated_via=InitiatedVia.system,
                completed_at=_now(),
            )
            db.add(tx)
            m.status = GroupMemberStatus.refunded
            await db.commit()
            refunded += 1
            await send_notification(
                db, m.member_id, NotificationType.group_cancelled,
                "Group payment cancelled",
                f"'{gp.title}' was cancelled. ৳{float(amt):,.2f} refunded to your account.",
                gp.reference_id,
            )
        elif m.status == GroupMemberStatus.agreed_debt and m.debt_id:
            debt = (await db.execute(select(MemberDebt).where(MemberDebt.id == m.debt_id))).scalar_one()
            debt.status = MemberDebtStatus.cancelled
            debt.cancelled_at = _now()
            debt.cancelled_reason = "group_cancelled"
            m.status = GroupMemberStatus.debt_cancelled
            await db.commit()
            await send_notification(
                db, m.member_id, NotificationType.group_cancelled,
                "Group payment cancelled",
                f"'{gp.title}' was cancelled. Your debt of ৳{float(debt.original_amount):,.2f} has been cleared.",
                gp.reference_id,
            )
        elif m.status == GroupMemberStatus.pending:
            m.status = GroupMemberStatus.expired
            await db.commit()

    gp.status = GroupPaymentStatus.cancelled
    await db.commit()

    await send_notification(
        db, gp.creator_id, NotificationType.group_cancelled,
        "Group payment cancelled",
        f"Group payment '{gp.title}' cancelled. Refunds issued to {refunded} member(s)."
        + (f" Reason: {reason}" if reason else ""),
        gp.reference_id,
    )
    await write_audit_log(
        db, "GROUP_PAYMENT_CANCELLED", actor_id=creator.id,
        entity_type="group_payment", entity_id=gp.id,
        payload={"refunded_count": refunded, "reason": reason},
    )
    return CancelGroupResponse(message="Group payment cancelled", refunded_count=refunded)


# ── Reads ──────────────────────────────────────────────────────────────────
def _member_brief(m: GroupPaymentMember, u: User | None) -> GroupMemberBrief:
    return GroupMemberBrief(
        member_id=m.member_id,
        full_name=u.full_name if u else "Unknown",
        mobile_last4=u.mobile_number[-4:] if u else "----",
        status=m.status.value,
        amount_owed=float(m.amount_owed),
    )


async def list_group_payments(db: AsyncSession, user: User) -> GroupPaymentListResponse:
    as_creator_rows = (
        (
            await db.execute(
                select(GroupPayment)
                .where(GroupPayment.creator_id == user.id)
                .order_by(GroupPayment.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    as_creator = []
    for gp in as_creator_rows:
        members = (
            (
                await db.execute(
                    select(GroupPaymentMember).where(GroupPaymentMember.group_payment_id == gp.id)
                )
            )
            .scalars()
            .all()
        )
        as_creator.append(
            GroupAsCreatorItem(
                id=gp.id,
                reference_id=gp.reference_id,
                title=gp.title,
                total_amount=float(gp.total_amount),
                per_person_amount=float(gp.per_person_amount),
                collected_amount=float(gp.collected_amount),
                status=gp.status.value,
                member_count=gp.member_count,
                members_paid=sum(
                    1
                    for m in members
                    if m.status in (GroupMemberStatus.agreed_paid, GroupMemberStatus.debt_cancelled)
                ),
                members_pending=sum(1 for m in members if m.status == GroupMemberStatus.pending),
                members_debt=sum(1 for m in members if m.status == GroupMemberStatus.agreed_debt),
                expires_at=gp.expires_at,
                created_at=gp.created_at,
            )
        )

    my_memberships = (
        (
            await db.execute(
                select(GroupPaymentMember)
                .where(GroupPaymentMember.member_id == user.id)
                .order_by(GroupPaymentMember.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    group_ids = {m.group_payment_id for m in my_memberships}
    groups = {
        g.id: g
        for g in (
            await db.execute(select(GroupPayment).where(GroupPayment.id.in_(group_ids)))
        ).scalars().all()
    } if group_ids else {}
    creator_ids = {g.creator_id for g in groups.values()}
    creators = await _users_by_id(db, creator_ids)

    as_member = []
    for m in my_memberships:
        g = groups.get(m.group_payment_id)
        if not g:
            continue
        as_member.append(
            GroupAsMemberItem(
                id=g.id,
                reference_id=g.reference_id,
                title=g.title,
                creator_name=creators[g.creator_id].full_name if g.creator_id in creators else "Unknown",
                amount_owed=float(m.amount_owed),
                my_status=m.status.value,
                expires_at=g.expires_at,
            )
        )
    return GroupPaymentListResponse(as_creator=as_creator, as_member=as_member)


async def get_detail(db: AsyncSession, user: User, group_id: int) -> GroupPaymentDetailResponse:
    gp = await _load_group(db, group_id)
    members = (
        (
            await db.execute(
                select(GroupPaymentMember).where(GroupPaymentMember.group_payment_id == gp.id)
            )
        )
        .scalars()
        .all()
    )
    is_member = any(m.member_id == user.id for m in members)
    if gp.creator_id != user.id and not is_member:
        raise HTTPException(403, "You do not have access to this group payment")

    member_users = await _users_by_id(db, {m.member_id for m in members})
    creator = (await db.execute(select(User).where(User.id == gp.creator_id))).scalar_one()
    return GroupPaymentDetailResponse(
        id=gp.id,
        reference_id=gp.reference_id,
        title=gp.title,
        creator_name=creator.full_name,
        total_amount=float(gp.total_amount),
        per_person_amount=float(gp.per_person_amount),
        collected_amount=float(gp.collected_amount),
        member_count=gp.member_count,
        creator_included=gp.creator_included,
        status=gp.status.value,
        note=gp.note,
        expires_at=gp.expires_at,
        created_at=gp.created_at,
        members=[_member_brief(m, member_users.get(m.member_id)) for m in members],
        is_creator=gp.creator_id == user.id,
    )


async def list_members(db: AsyncSession, user: User, group_id: int) -> list[GroupMemberBrief]:
    gp = await _load_group(db, group_id)
    if gp.creator_id != user.id:
        raise HTTPException(403, "Only the creator can view the member list")
    members = (
        (
            await db.execute(
                select(GroupPaymentMember).where(GroupPaymentMember.group_payment_id == gp.id)
            )
        )
        .scalars()
        .all()
    )
    member_users = await _users_by_id(db, {m.member_id for m in members})
    return [_member_brief(m, member_users.get(m.member_id)) for m in members]


# ── Debt reads ─────────────────────────────────────────────────────────────
async def _last_payment(db: AsyncSession, debt_id: int) -> DebtPayment | None:
    return (
        await db.execute(
            select(DebtPayment)
            .where(DebtPayment.debt_id == debt_id)
            .order_by(DebtPayment.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def my_debts(db: AsyncSession, user: User) -> MyDebtsResponse:
    rows = (
        (
            await db.execute(
                select(MemberDebt)
                .where(
                    MemberDebt.debtor_id == user.id,
                    MemberDebt.status.in_(
                        [MemberDebtStatus.pending, MemberDebtStatus.partially_paid]
                    ),
                )
                .order_by(MemberDebt.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    groups = {
        g.id: g
        for g in (
            await db.execute(
                select(GroupPayment).where(GroupPayment.id.in_({d.group_payment_id for d in rows}))
            )
        ).scalars().all()
    } if rows else {}
    creditors = await _users_by_id(db, {d.creditor_id for d in rows})

    items = []
    total = _ZERO
    for d in rows:
        total += Decimal(str(d.remaining_amount))
        lp = await _last_payment(db, d.id)
        g = groups.get(d.group_payment_id)
        items.append(
            MyDebtItem(
                debt_id=d.id,
                reference_id=d.reference_id,
                group_title=g.title if g else "Unknown",
                creditor_name=creditors[d.creditor_id].full_name if d.creditor_id in creditors else "Unknown",
                original_amount=float(d.original_amount),
                remaining_amount=float(d.remaining_amount),
                status=d.status.value,
                created_at=d.created_at,
                last_payment=(
                    {"amount": float(lp.amount), "paid_at": lp.created_at} if lp else None
                ),
            )
        )
    return MyDebtsResponse(total_outstanding=float(total), debts=items)


async def owed_to_me(db: AsyncSession, user: User) -> OwedToMeResponse:
    rows = (
        (
            await db.execute(
                select(MemberDebt)
                .where(
                    MemberDebt.creditor_id == user.id,
                    MemberDebt.status.in_(
                        [MemberDebtStatus.pending, MemberDebtStatus.partially_paid]
                    ),
                )
                .order_by(MemberDebt.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    groups = {
        g.id: g
        for g in (
            await db.execute(
                select(GroupPayment).where(GroupPayment.id.in_({d.group_payment_id for d in rows}))
            )
        ).scalars().all()
    } if rows else {}
    debtors = await _users_by_id(db, {d.debtor_id for d in rows})

    items = []
    total = _ZERO
    for d in rows:
        total += Decimal(str(d.remaining_amount))
        g = groups.get(d.group_payment_id)
        items.append(
            OwedToMeItem(
                debt_id=d.id,
                reference_id=d.reference_id,
                group_title=g.title if g else "Unknown",
                debtor_name=debtors[d.debtor_id].full_name if d.debtor_id in debtors else "Unknown",
                original_amount=float(d.original_amount),
                remaining_amount=float(d.remaining_amount),
                status=d.status.value,
                created_at=d.created_at,
            )
        )
    return OwedToMeResponse(total_incoming=float(total), debts=items)


async def debt_history(db: AsyncSession, user: User, debt_id: int) -> DebtHistoryResponse:
    debt = (await db.execute(select(MemberDebt).where(MemberDebt.id == debt_id))).scalar_one_or_none()
    if not debt or user.id not in (debt.debtor_id, debt.creditor_id):
        raise HTTPException(404, "Debt not found")
    rows = (
        (
            await db.execute(
                select(DebtPayment)
                .where(DebtPayment.debt_id == debt_id)
                .order_by(DebtPayment.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return DebtHistoryResponse(
        debt_id=debt.id,
        reference_id=debt.reference_id,
        original_amount=float(debt.original_amount),
        remaining_amount=float(debt.remaining_amount),
        status=debt.status.value,
        installments=[
            DebtHistoryItem(
                amount=float(r.amount),
                remaining_after=float(r.remaining_after),
                payment_type=r.payment_type.value,
                transaction_id=r.transaction_id,
                created_at=r.created_at,
            )
            for r in rows
        ],
    )


# ── Expiry sweep (Celery Beat every 30 min, also callable directly) ────────
async def expire_group_payments(db: AsyncSession) -> dict:
    now = _now()
    open_groups = (
        (
            await db.execute(
                select(GroupPayment).where(
                    GroupPayment.status == GroupPaymentStatus.open,
                    GroupPayment.expires_at < now,
                )
            )
        )
        .scalars()
        .all()
    )
    invites_expired = 0
    groups_expired = 0
    for gp in open_groups:
        members = (
            (
                await db.execute(
                    select(GroupPaymentMember).where(GroupPaymentMember.group_payment_id == gp.id)
                )
            )
            .scalars()
            .all()
        )
        for m in members:
            if m.status == GroupMemberStatus.pending:
                m.status = GroupMemberStatus.expired
                invites_expired += 1
                await send_notification(
                    db, m.member_id, NotificationType.group_member_expired,
                    "Invite expired",
                    f"The group payment invite for '{gp.title}' has expired.",
                    gp.reference_id,
                )

        any_agreed = any(
            m.status in (GroupMemberStatus.agreed_paid, GroupMemberStatus.agreed_debt)
            for m in members
        )
        if not any_agreed:
            gp.status = GroupPaymentStatus.expired
            groups_expired += 1
            await send_notification(
                db, gp.creator_id, NotificationType.group_expired,
                "Group payment expired",
                f"'{gp.title}' expired. Some members didn't respond in time.",
                gp.reference_id,
            )
        await db.commit()

    return {
        "open_groups_checked": len(open_groups),
        "invites_expired": invites_expired,
        "groups_expired": groups_expired,
    }
