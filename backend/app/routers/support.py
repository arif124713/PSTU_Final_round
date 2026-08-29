from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.support_ticket import SenderRole, TicketMessage
from app.models.user import User
from app.schemas.support import ChatBody, ChatResponse, CreateDisputeBody, CreateDisputeResponse, TicketMessageBody
from app.services import support_service

router = APIRouter(prefix="/api/v1/support", tags=["support"])


@router.post("/dispute", response_model=CreateDisputeResponse)
async def dispute(
    body: CreateDisputeBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = await support_service.create_dispute(
        db, current_user, body.transaction_reference_id, body.category, body.description
    )
    return CreateDisputeResponse(
        ticket_id=ticket.id,
        reference_id=ticket.reference_id,
        message="Dispute filed. Expected response: 24-48 hours",
    )


@router.get("/tickets")
async def my_tickets(
    status: str = Query("all"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tickets = await support_service.list_my_tickets(db, current_user, status)
    return [
        {
            "ticket_id": t.id,
            "reference_id": t.reference_id,
            "category": t.category.value,
            "subject": t.subject,
            "status": t.status.value,
            "created_at": t.created_at,
            "last_updated": t.updated_at,
        }
        for t in tickets
    ]


@router.get("/tickets/{ticket_id}/messages")
async def get_messages(
    ticket_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(select(TicketMessage).where(TicketMessage.ticket_id == ticket_id).order_by(TicketMessage.created_at))
    ).scalars().all()
    return [
        {"id": m.id, "message": m.message, "sender_role": m.sender_role.value, "created_at": m.created_at}
        for m in rows
    ]


@router.post("/tickets/{ticket_id}/messages")
async def post_message(
    ticket_id: int,
    body: TicketMessageBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msg = await support_service.add_message(db, current_user, ticket_id, body.message, SenderRole.user)
    return {"message_id": msg.id, "created_at": msg.created_at}


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services import rag_service

    return await rag_service.answer_query(body.message)
