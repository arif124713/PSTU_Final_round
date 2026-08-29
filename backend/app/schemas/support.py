from datetime import datetime

from pydantic import BaseModel


class CreateDisputeBody(BaseModel):
    transaction_reference_id: str
    category: str = "wrong_transfer"
    description: str


class CreateDisputeResponse(BaseModel):
    ticket_id: int
    reference_id: str
    message: str


class TicketMessageBody(BaseModel):
    message: str


class TicketSummary(BaseModel):
    ticket_id: int
    reference_id: str
    category: str
    subject: str
    status: str
    created_at: datetime
    updated_at: datetime


class ResolveTicketBody(BaseModel):
    decision: str  # "approved" | "rejected"
    resolution_note: str
    execute_reversal: bool = False


class ChatBody(BaseModel):
    message: str
    session_id: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    confidence: str
    needs_human: bool
