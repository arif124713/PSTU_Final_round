"""Auto-deduction engine for group-payment debts.

`settle_pending_debts` is invoked (as a FastAPI ``BackgroundTask``) after any event
that increases a user's balance — a received transfer, an accepted money request, or
an installment credited to a creditor (cascade). It pays off the user's oldest
pending debts FIFO, partially if the incoming amount is smaller than what is owed.

No PIN is taken here: consent was captured when the member typed their PIN and
tapped "Agree" (``member_debts.pre_authorized = TRUE``). Auto-deductions are scoped
to the exact debt amount for a specific group payment — never open-ended.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.group_payment import (
    DebtPayment,
    DebtPaymentType,
    GroupPayment,
    GroupPaymentMember,
    GroupPaymentStatus,
    MemberDebt,
    MemberDebtStatus,
    GroupMemberStatus,
)
from app.models.notification import NotificationType
from app.models.transaction import InitiatedVia, Transaction, TransactionStatus, TransactionType
from app.models.user import User
from app.services.audit_service import write_audit_log
from app.services.notification_service import send_notification

_ZERO = Decimal("0.00")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def check_group_completion(db: AsyncSession, group_payment_id: int) -> None:
    """A group is complete once no member is still ``pending`` and no debt is still
    active (``pending``/``partially_paid``). Cancelled and declined shares don't
    block completion — the creator has chosen to absorb them."""
    pending_members = (
        await db.execute(
            select(func.count())
            .select_from(GroupPaymentMember)
            .where(
                GroupPaymentMember.group_payment_id == group_payment_id,
                GroupPaymentMember.status.in_(
                    [GroupMemberStatus.pending, GroupMemberStatus.agreed_debt]
                ),
            )
        )
    ).scalar_one()

    active_debts = (
        await db.execute(
            select(func.count())
            .select_from(MemberDebt)
            .where(
                MemberDebt.group_payment_id == group_payment_id,
                MemberDebt.status.in_([MemberDebtStatus.pending, MemberDebtStatus.partially_paid]),
            )
        )
    ).scalar_one()

    if pending_members or active_debts:
        return

    gp = (
        await db.execute(select(GroupPayment).where(GroupPayment.id == group_payment_id))
    ).scalar_one_or_none()
    if not gp or gp.status != GroupPaymentStatus.open:
        return

    gp.status = GroupPaymentStatus.completed
    await db.commit()

    await send_notification(
        db,
        gp.creator_id,
        NotificationType.group_completed,
        "Group payment collected",
        f"'{gp.title}' fully collected! All ৳{float(gp.total_amount):,.2f} received ✓",
        gp.reference_id,
    )


async def settle_pending_debts(
    db: AsyncSession, debtor_id: int, _visited: set[int] | None = None
) -> None:
    """Pay off ``debtor_id``'s pending debts FIFO from their current balance."""
    visited = _visited if _visited is not None else set()
    if debtor_id in visited:
        return
    visited.add(debtor_id)

    debtor = (
        await db.execute(select(User).where(User.id == debtor_id).with_for_update())
    ).scalar_one_or_none()
    if debtor is None:
        return
    # A frozen account cannot transact — the debit that auto-deduction performs is
    # blocked until the debtor is unfrozen. Retried on their next incoming transfer.
    if debtor.is_frozen or not debtor.is_active:
        return

    pending_debts = (
        (
            await db.execute(
                select(MemberDebt)
                .where(
                    MemberDebt.debtor_id == debtor_id,
                    MemberDebt.status.in_(
                        [MemberDebtStatus.pending, MemberDebtStatus.partially_paid]
                    ),
                    MemberDebt.pre_authorized.is_(True),
                )
                .order_by(MemberDebt.created_at.asc(), MemberDebt.id.asc())
            )
        )
        .scalars()
        .all()
    )
    if not pending_debts:
        return

    available = Decimal(str(debtor.balance))
    credited_creditors: set[int] = set()

    for debt in pending_debts:
        if available <= _ZERO:
            break

        creditor = (
            await db.execute(select(User).where(User.id == debt.creditor_id).with_for_update())
        ).scalar_one_or_none()
        if creditor is None:
            continue
        # Creditor frozen -> auto-deduction is queued (skip this debt, try the rest).
        if creditor.is_frozen or not creditor.is_active:
            continue

        payable = min(available, Decimal(str(debt.remaining_amount)))
        if payable <= _ZERO:
            continue
        new_remaining = Decimal(str(debt.remaining_amount)) - payable
        fully_paid = new_remaining <= _ZERO
        new_status = MemberDebtStatus.fully_paid if fully_paid else MemberDebtStatus.partially_paid

        # ── Atomic installment ──────────────────────────────────────────────
        # Guarded debit: WHERE balance >= payable. If the balance dropped between
        # our locked read and here (concurrent outgoing transfer), rowcount is 0
        # and we stop — the next incoming transfer retries from remaining_amount.
        upd = await db.execute(
            User.__table__.update()
            .where(User.id == debtor_id, User.balance >= payable)
            .values(balance=User.balance - payable)
        )
        if upd.rowcount == 0:
            await db.rollback()
            break

        await db.execute(
            User.__table__.update().where(User.id == debt.creditor_id).values(balance=User.balance + payable)
        )

        tx = Transaction(
            reference_id=str(uuid.uuid4()),
            sender_id=debt.debtor_id,
            receiver_id=debt.creditor_id,
            amount=payable,
            note=f"Auto-settlement: group payment debt {debt.reference_id}",
            status=TransactionStatus.completed,
            type=TransactionType.debt_settlement,
            initiated_via=InitiatedVia.system,
            completed_at=_now(),
        )
        db.add(tx)
        await db.flush()

        db.add(
            DebtPayment(
                debt_id=debt.id,
                transaction_id=tx.id,
                amount=payable,
                remaining_after=new_remaining if new_remaining > _ZERO else _ZERO,
                payment_type=DebtPaymentType.auto_deduction,
            )
        )

        debt.remaining_amount = new_remaining if new_remaining > _ZERO else _ZERO
        debt.status = new_status
        if fully_paid:
            debt.fully_paid_at = _now()

        # collected_amount tracks money actually received by the creator.
        gp = (
            await db.execute(select(GroupPayment).where(GroupPayment.id == debt.group_payment_id))
        ).scalar_one()
        gp.collected_amount = Decimal(str(gp.collected_amount)) + payable

        if fully_paid:
            gpm = (
                await db.execute(
                    select(GroupPaymentMember).where(GroupPaymentMember.debt_id == debt.id)
                )
            ).scalar_one_or_none()
            if gpm is not None:
                gpm.status = GroupMemberStatus.agreed_paid
                gpm.paid_at = _now()

        await db.commit()

        # ── Notifications ──────────────────────────────────────────────────
        gp_title = gp.title
        gp_ref = gp.reference_id
        if fully_paid:
            await send_notification(
                db, debt.debtor_id, NotificationType.group_debt_fully_paid,
                "Debt settled",
                f"Your ৳{float(debt.original_amount):,.2f} debt for '{gp_title}' is fully settled ✓",
                gp_ref,
            )
            await send_notification(
                db, debt.creditor_id, NotificationType.group_debt_fully_paid,
                "Share settled",
                f"{debtor.full_name}'s full ৳{float(debt.original_amount):,.2f} share for '{gp_title}' has been settled ✓",
                gp_ref,
            )
            await check_group_completion(db, debt.group_payment_id)
        else:
            await send_notification(
                db, debt.debtor_id, NotificationType.group_debt_auto_paid_partial,
                "Auto-deduction",
                f"৳{float(payable):,.2f} auto-deducted for '{gp_title}' debt. Remaining: ৳{float(new_remaining):,.2f}",
                gp_ref,
            )
            await send_notification(
                db, debt.creditor_id, NotificationType.group_debt_auto_paid_partial,
                "Partial settlement",
                f"{debtor.full_name} auto-paid ৳{float(payable):,.2f} toward '{gp_title}'. Still owed: ৳{float(new_remaining):,.2f}",
                gp_ref,
            )

        await write_audit_log(
            db, "DEBT_AUTO_SETTLED", actor_id=debt.debtor_id, target_id=debt.creditor_id,
            entity_type="member_debt", entity_id=debt.id,
            payload={"amount": float(payable), "remaining": float(new_remaining)},
        )

        credited_creditors.add(debt.creditor_id)
        available -= payable

    # Cascade: a creditor who just received funds may themselves owe debts.
    for creditor_id in credited_creditors:
        await settle_pending_debts(db, creditor_id, visited)


async def settle_pending_debts_bg(debtor_id: int) -> None:
    """BackgroundTask entrypoint — owns its own DB session (the request's session
    is already closed by the time this runs)."""
    async with AsyncSessionLocal() as db:
        try:
            await settle_pending_debts(db, debtor_id)
        except Exception:  # noqa: BLE001 - background task must never crash the worker
            await db.rollback()
