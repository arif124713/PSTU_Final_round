from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.notification import NotificationType
from app.models.support_ticket import SenderRole, SupportTicket, TicketCategory, TicketMessage, TicketStatus
from app.models.transaction import InitiatedVia, Transaction, TransactionStatus
from app.models.user import User
from app.services.audit_service import write_audit_log
from app.services.notification_service import send_notification
from app.services.transfer_service import _execute_atomic_transfer


async def create_dispute(db: AsyncSession, user: User, transaction_reference_id: str, category: str, description: str) -> SupportTicket:
    tx = (
        await db.execute(select(Transaction).where(Transaction.reference_id == transaction_reference_id))
    ).scalar_one_or_none()
    if not tx:
        raise HTTPException(404, "Transaction not found")
    if tx.sender_id != user.id:
        raise HTTPException(403, "Only the sender can dispute this transaction")
    if tx.status != TransactionStatus.completed:
        raise HTTPException(422, "Only completed transactions can be disputed")
    if tx.created_at < datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=settings.dispute_window_days):
        raise HTTPException(422, f"Dispute window ({settings.dispute_window_days} days) has passed")

    existing = (
        await db.execute(
            select(SupportTicket).where(
                SupportTicket.transaction_id == tx.id, SupportTicket.status.in_([TicketStatus.open, TicketStatus.under_review])
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "An open dispute already exists for this transaction")

    import uuid

    ticket = SupportTicket(
        reference_id=str(uuid.uuid4()),
        user_id=user.id,
        transaction_id=tx.id,
        category=TicketCategory(category),
        subject="Wrong Transfer Dispute",
        description=description,
    )
    db.add(ticket)
    tx.status = TransactionStatus.disputed
    await db.commit()
    await db.refresh(ticket)

    await write_audit_log(db, "DISPUTE_CREATED", actor_id=user.id, entity_type="support_ticket", entity_id=ticket.id)
    return ticket


async def add_message(db: AsyncSession, user: User, ticket_id: int, message: str, sender_role: SenderRole) -> TicketMessage:
    ticket = (await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))).scalar_one_or_none()
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if sender_role == SenderRole.user and ticket.user_id != user.id:
        raise HTTPException(403, "Not your ticket")

    msg = TicketMessage(ticket_id=ticket.id, sender_id=user.id, message=message, sender_role=sender_role)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def list_my_tickets(db: AsyncSession, user: User, status_filter: str) -> list[SupportTicket]:
    conditions = [SupportTicket.user_id == user.id]
    if status_filter != "all":
        conditions.append(SupportTicket.status == TicketStatus(status_filter))
    rows = (
        await db.execute(select(SupportTicket).where(*conditions).order_by(SupportTicket.created_at.desc()))
    ).scalars().all()
    return rows


async def resolve_ticket(
    db: AsyncSession, admin: User, ticket_id: int, decision: str, resolution_note: str, execute_reversal: bool
) -> SupportTicket:
    ticket = (await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))).scalar_one_or_none()
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    ticket.resolution_note = resolution_note
    ticket.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)

    if decision == "approved":
        ticket.reversal_approved = True
        ticket.status = TicketStatus.resolved
        if execute_reversal and ticket.transaction_id:
            original = (await db.execute(select(Transaction).where(Transaction.id == ticket.transaction_id))).scalar_one()
            reversal_tx = await _execute_atomic_transfer(
                db, original.receiver_id, original.sender_id, original.amount,
                f"Reversal of {original.reference_id}", InitiatedVia.web, False, None,
            )
            ticket.reversal_tx_id = reversal_tx.id
            await write_audit_log(db, "REVERSAL_EXECUTED", actor_id=admin.id, entity_type="transaction", entity_id=reversal_tx.id)

            for party_id in (original.sender_id, original.receiver_id):
                await send_notification(
                    db, party_id, NotificationType.ticket_update,
                    "Reversal processed", f"Transaction reversal of ৳{float(original.amount):,.2f} has been processed", ticket.reference_id,
                )
        await write_audit_log(db, "REVERSAL_APPROVED", actor_id=admin.id, entity_type="support_ticket", entity_id=ticket.id)
    else:
        ticket.reversal_approved = False
        ticket.status = TicketStatus.rejected
        original = None
        if ticket.transaction_id:
            original = (await db.execute(select(Transaction).where(Transaction.id == ticket.transaction_id))).scalar_one_or_none()
            if original:
                original.status = TransactionStatus.completed
        await send_notification(
            db, ticket.user_id, NotificationType.ticket_update,
            "Dispute rejected", f"Your dispute was rejected: {resolution_note}", ticket.reference_id,
        )

    await db.commit()
    await db.refresh(ticket)
    return ticket
