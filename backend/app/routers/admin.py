from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_admin
from app.models.audit_log import AuditLog
from app.models.notification import NotificationType
from app.models.support_ticket import SenderRole, SupportTicket, TicketStatus
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.support import ResolveTicketBody, TicketMessageBody
from app.services import support_service
from app.services.audit_service import write_audit_log
from app.services.notification_service import send_notification

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/dashboard")
async def admin_dashboard(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)

    registered_users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    transactions_today = (
        await db.execute(select(func.count()).where(Transaction.created_at >= today_start))
    ).scalar_one()
    volume_today = (
        await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.created_at >= today_start, Transaction.status == TransactionStatus.completed
            )
        )
    ).scalar_one()
    pending_tickets = (
        await db.execute(select(func.count()).where(SupportTicket.status == TicketStatus.open))
    ).scalar_one()
    flagged_transactions = (
        await db.execute(select(func.count()).where(Transaction.flagged.is_(True)))
    ).scalar_one()
    frozen_accounts = (await db.execute(select(func.count()).where(User.is_frozen.is_(True)))).scalar_one()

    return {
        "totals": {
            "registered_users": registered_users,
            "transactions_today": transactions_today,
            "transaction_volume_today": float(volume_today),
            "pending_tickets": pending_tickets,
            "flagged_transactions": flagged_transactions,
            "frozen_accounts": frozen_accounts,
        },
    }


@router.get("/users")
async def list_users(
    search: str | None = None,
    is_frozen: bool | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    conditions = []
    if search:
        conditions.append(or_(User.full_name.ilike(f"%{search}%"), User.mobile_number.ilike(f"%{search}%")))
    if is_frozen is not None:
        conditions.append(User.is_frozen == is_frozen)

    rows = (
        await db.execute(
            select(User).where(*conditions).offset((page - 1) * per_page).limit(per_page)
        )
    ).scalars().all()
    return [
        {
            "id": u.id, "full_name": u.full_name, "mobile_number": u.mobile_number,
            "balance": float(u.balance), "is_active": u.is_active, "is_frozen": u.is_frozen,
        }
        for u in rows
    ]


@router.get("/users/{user_id}")
async def user_detail(user_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        return {"error": "not found"}
    return {
        "id": user.id, "full_name": user.full_name, "mobile_number": user.mobile_number,
        "nid_last4": user.nid_last4, "balance": float(user.balance),
        "is_active": user.is_active, "is_frozen": user.is_frozen, "frozen_reason": user.frozen_reason,
        "created_at": user.created_at, "last_login_at": user.last_login_at,
    }


class FreezeBody(BaseModel):
    reason: str


@router.post("/users/{user_id}/freeze")
async def freeze_user(
    user_id: int, body: FreezeBody, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
    user.is_frozen = True
    user.frozen_reason = body.reason
    user.frozen_at = datetime.now(timezone.utc).replace(tzinfo=None)
    user.frozen_by = admin.id
    await db.commit()

    redis = await get_redis()
    from app.models.user import LoginSession

    sessions = (
        await db.execute(select(LoginSession).where(LoginSession.user_id == user_id, LoginSession.revoked.is_(False)))
    ).scalars().all()
    for s in sessions:
        ttl = max(int((s.expires_at - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds()), 1)
        await redis.setex(f"jwt:blocklist:{s.jwt_jti}", ttl, "1")
        s.revoked = True
    await db.commit()

    await send_notification(db, user_id, NotificationType.account_frozen, "Account frozen", "Your account has been temporarily frozen. Contact support.")
    await write_audit_log(db, "ACCOUNT_FROZEN", actor_id=admin.id, target_id=user_id, payload={"reason": body.reason})
    return {"user_id": user_id, "is_frozen": True}


@router.post("/users/{user_id}/unfreeze")
async def unfreeze_user(
    user_id: int, body: FreezeBody, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
    user.is_frozen = False
    await db.commit()
    await send_notification(db, user_id, NotificationType.system, "Account unfrozen", "Your account has been unfrozen.")
    await write_audit_log(db, "ACCOUNT_UNFROZEN", actor_id=admin.id, target_id=user_id, payload={"reason": body.reason})
    return {"user_id": user_id, "is_frozen": False}


@router.get("/transactions")
async def list_transactions(
    status: str | None = None,
    flagged: bool | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    conditions = []
    if status:
        conditions.append(Transaction.status == TransactionStatus(status))
    if flagged is not None:
        conditions.append(Transaction.flagged == flagged)
    rows = (
        await db.execute(
            select(Transaction).where(*conditions).order_by(Transaction.created_at.desc())
            .offset((page - 1) * per_page).limit(per_page)
        )
    ).scalars().all()
    return [
        {
            "reference_id": t.reference_id, "amount": float(t.amount), "status": t.status.value,
            "flagged": t.flagged, "flag_reason": t.flag_reason, "created_at": t.created_at,
        }
        for t in rows
    ]


@router.get("/flagged")
async def flagged_accounts(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Transaction.sender_id, func.count().label("flag_count"))
            .where(Transaction.flagged.is_(True))
            .group_by(Transaction.sender_id)
        )
    ).all()
    result = []
    for sender_id, flag_count in rows:
        user = (await db.execute(select(User).where(User.id == sender_id))).scalar_one()
        result.append({"user_id": user.id, "full_name": user.full_name, "flag_count": flag_count, "is_frozen": user.is_frozen})
    return result


@router.get("/tickets")
async def list_tickets(
    status: str = "open",
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    conditions = []
    if status != "all":
        conditions.append(SupportTicket.status == TicketStatus(status))
    rows = (
        await db.execute(select(SupportTicket).where(*conditions).order_by(SupportTicket.created_at.asc()))
    ).scalars().all()
    return [
        {
            "ticket_id": t.id, "reference_id": t.reference_id, "user_id": t.user_id,
            "category": t.category.value, "subject": t.subject, "status": t.status.value,
            "created_at": t.created_at,
        }
        for t in rows
    ]


class AssignBody(BaseModel):
    agent_id: int


@router.post("/tickets/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: int, body: AssignBody, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    ticket = (await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))).scalar_one()
    ticket.assigned_to = body.agent_id
    ticket.status = TicketStatus.under_review
    await db.commit()
    return {"ticket_id": ticket.id, "assigned_to": body.agent_id}


@router.post("/tickets/{ticket_id}/message")
async def admin_message(
    ticket_id: int, body: TicketMessageBody, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    msg = await support_service.add_message(db, admin, ticket_id, body.message, SenderRole.admin)
    return {"message_id": msg.id, "created_at": msg.created_at}


@router.post("/tickets/{ticket_id}/resolve")
async def resolve_ticket(
    ticket_id: int, body: ResolveTicketBody, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    ticket = await support_service.resolve_ticket(
        db, admin, ticket_id, body.decision, body.resolution_note, body.execute_reversal
    )
    return {"ticket_id": ticket.id, "status": ticket.status.value, "reversal_tx_id": ticket.reversal_tx_id}


@router.get("/audit-log")
async def audit_log(
    event_type: str | None = None,
    actor_id: int | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    conditions = []
    if event_type:
        conditions.append(AuditLog.event_type == event_type)
    if actor_id:
        conditions.append(AuditLog.actor_id == actor_id)
    rows = (
        await db.execute(
            select(AuditLog).where(*conditions).order_by(AuditLog.created_at.desc())
            .offset((page - 1) * per_page).limit(per_page)
        )
    ).scalars().all()
    return [
        {
            "id": a.id, "event_type": a.event_type, "actor_id": a.actor_id, "target_id": a.target_id,
            "entity_type": a.entity_type, "entity_id": a.entity_id, "payload": a.payload, "created_at": a.created_at,
        }
        for a in rows
    ]


@router.post("/support-docs/upload")
async def upload_support_doc(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    import os

    from app.config import settings
    from app.models.support_ticket import RagDocument
    from app.services import rag_service

    os.makedirs(settings.rag_docs_path, exist_ok=True)
    file_path = os.path.join(settings.rag_docs_path, file.filename)
    contents = await file.read()
    with open(file_path, "wb") as f:
        f.write(contents)

    doc = RagDocument(filename=file.filename, file_path=file_path, uploaded_by=admin.id)
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    chunk_count = rag_service.index_pdf(file_path, file.filename)
    doc.chunk_count = chunk_count
    doc.indexed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    return {"document_id": doc.id, "status": "indexed", "chunk_count": chunk_count}


@router.get("/support-docs")
async def list_support_docs(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    from app.models.support_ticket import RagDocument

    rows = (await db.execute(select(RagDocument))).scalars().all()
    return [
        {
            "document_id": d.id, "filename": d.filename, "chunk_count": d.chunk_count,
            "indexed_at": d.indexed_at, "created_at": d.created_at,
        }
        for d in rows
    ]


@router.delete("/support-docs/{document_id}")
async def delete_support_doc(document_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    import os

    from app.models.support_ticket import RagDocument
    from app.services import rag_service

    doc = (await db.execute(select(RagDocument).where(RagDocument.id == document_id))).scalar_one_or_none()
    if not doc:
        return {"error": "not found"}

    rag_service.delete_document(doc.filename)
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)
    await db.delete(doc)
    await db.commit()
    return {"deleted": document_id}
