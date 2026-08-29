from datetime import datetime

from pydantic import BaseModel, Field


class ValidateReceiverRequest(BaseModel):
    receiver_identifier: str


class ReceiverInfo(BaseModel):
    id: int
    full_name: str
    mobile_last4: str
    is_active: bool


class ValidateReceiverResponse(BaseModel):
    valid: bool
    receiver: ReceiverInfo


class SendMoneyRequest(BaseModel):
    idempotency_key: str
    receiver_identifier: str
    amount: float = Field(..., gt=0)
    pin: str = Field(..., pattern=r"^\d{6}$")
    note: str | None = None
    extra_confirmed: bool = False


class SendMoneyResponse(BaseModel):
    transaction_id: int
    reference_id: str
    amount: float
    receiver_name: str
    new_balance: float
    status: str
    timestamp: str


class TransactionListItem(BaseModel):
    reference_id: str
    amount: float
    counterparty_name: str
    direction: str  # "sent" | "received"
    note: str | None
    status: str
    created_at: datetime


class Pagination(BaseModel):
    total: int
    page: int
    per_page: int
    total_pages: int


class TransactionHistorySummary(BaseModel):
    total_sent: float
    total_received: float
    period: str


class TransactionHistoryResponse(BaseModel):
    transactions: list[TransactionListItem]
    pagination: Pagination
    summary: TransactionHistorySummary


class TransactionPartyInfo(BaseModel):
    name: str
    mobile_last4: str


class TransactionDetailResponse(BaseModel):
    reference_id: str
    amount: float
    sender: TransactionPartyInfo
    receiver: TransactionPartyInfo
    note: str | None
    status: str
    initiated_via: str
    created_at: datetime
    can_dispute: bool


class ConfirmDraftRequest(BaseModel):
    draft_id: str
    pin: str = Field(..., pattern=r"^\d{6}$")


class ConfirmDraftResponse(BaseModel):
    status: str
    reference_id: str
    new_balance: float
