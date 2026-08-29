from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.money_request import MoneyRequest, RequestStatus
from app.models.notification import Notification
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import SavedBeneficiary, User
from app.services.transfer_service import get_history

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_sent = (
        await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.sender_id == current_user.id,
                Transaction.status == TransactionStatus.completed,
                Transaction.created_at >= month_start,
            )
        )
    ).scalar_one()
    total_received = (
        await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.receiver_id == current_user.id,
                Transaction.status == TransactionStatus.completed,
                Transaction.created_at >= month_start,
            )
        )
    ).scalar_one()
    tx_count = (
        await db.execute(
            select(func.count()).where(
                or_(Transaction.sender_id == current_user.id, Transaction.receiver_id == current_user.id),
                Transaction.created_at >= month_start,
            )
        )
    ).scalar_one()

    recent = await get_history(db, current_user, "all", "all", None, None, 1, 5)

    incoming = (
        await db.execute(
            select(func.count()).where(
                MoneyRequest.payer_id == current_user.id, MoneyRequest.status == RequestStatus.pending
            )
        )
    ).scalar_one()
    outgoing = (
        await db.execute(
            select(func.count()).where(
                MoneyRequest.requester_id == current_user.id, MoneyRequest.status == RequestStatus.pending
            )
        )
    ).scalar_one()

    unread = (
        await db.execute(
            select(func.count()).where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        )
    ).scalar_one()

    beneficiaries = (
        await db.execute(
            select(SavedBeneficiary, User)
            .join(User, User.id == SavedBeneficiary.beneficiary_id)
            .where(SavedBeneficiary.user_id == current_user.id)
            .limit(4)
        )
    ).all()

    return {
        "balance": float(current_user.balance),
        "this_month": {
            "total_sent": float(total_sent),
            "total_received": float(total_received),
            "transactions_count": tx_count,
        },
        "recent_transactions": [t.model_dump() for t in recent.transactions],
        "pending_requests": {"incoming": incoming, "outgoing": outgoing},
        "unread_notifications": unread,
        "saved_beneficiaries": [
            {"id": b.beneficiary_id, "full_name": u.full_name, "nickname": b.nickname, "mobile_last4": u.mobile_number[-4:]}
            for b, u in beneficiaries
        ],
    }
