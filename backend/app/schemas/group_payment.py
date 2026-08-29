from datetime import datetime

from pydantic import BaseModel, Field


class CreateGroupPaymentBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    total_amount: float = Field(..., gt=0)
    members: list[str] = Field(..., min_length=1, max_length=20)
    creator_included: bool = False
    note: str | None = Field(None, max_length=255)
    idempotency_key: str | None = None


class GroupMemberBrief(BaseModel):
    member_id: int
    full_name: str
    mobile_last4: str
    status: str
    amount_owed: float


class CreateGroupPaymentResponse(BaseModel):
    group_payment_id: int
    reference_id: str
    title: str
    total_amount: float
    per_person_amount: float
    member_count: int
    expires_at: datetime
    members: list[GroupMemberBrief]


class RespondGroupPaymentBody(BaseModel):
    action: str = Field(..., pattern="^(agree|decline)$")
    pin: str | None = Field(None, pattern=r"^\d{6}$")


class RespondGroupPaymentResponse(BaseModel):
    status: str
    detail: str
    new_balance: float | None = None
    debt_reference_id: str | None = None


class CancelDebtBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=255)


class CancelGroupBody(BaseModel):
    reason: str | None = Field(None, max_length=255)


class MessageResponse(BaseModel):
    message: str


class CancelGroupResponse(BaseModel):
    message: str
    refunded_count: int


class GroupAsCreatorItem(BaseModel):
    id: int
    reference_id: str
    title: str
    total_amount: float
    per_person_amount: float
    collected_amount: float
    status: str
    member_count: int
    members_paid: int
    members_pending: int
    members_debt: int
    expires_at: datetime
    created_at: datetime


class GroupAsMemberItem(BaseModel):
    id: int
    reference_id: str
    title: str
    creator_name: str
    amount_owed: float
    my_status: str
    expires_at: datetime


class GroupPaymentListResponse(BaseModel):
    as_creator: list[GroupAsCreatorItem]
    as_member: list[GroupAsMemberItem]


class GroupPaymentDetailResponse(BaseModel):
    id: int
    reference_id: str
    title: str
    creator_name: str
    total_amount: float
    per_person_amount: float
    collected_amount: float
    member_count: int
    creator_included: bool
    status: str
    note: str | None
    expires_at: datetime
    created_at: datetime
    members: list[GroupMemberBrief]
    is_creator: bool


class DebtLastPayment(BaseModel):
    amount: float
    paid_at: datetime


class MyDebtItem(BaseModel):
    debt_id: int
    reference_id: str
    group_title: str
    creditor_name: str
    original_amount: float
    remaining_amount: float
    status: str
    created_at: datetime
    last_payment: DebtLastPayment | None


class MyDebtsResponse(BaseModel):
    total_outstanding: float
    debts: list[MyDebtItem]


class OwedToMeItem(BaseModel):
    debt_id: int
    reference_id: str
    group_title: str
    debtor_name: str
    original_amount: float
    remaining_amount: float
    status: str
    created_at: datetime


class OwedToMeResponse(BaseModel):
    total_incoming: float
    debts: list[OwedToMeItem]


class DebtHistoryItem(BaseModel):
    amount: float
    remaining_after: float
    payment_type: str
    transaction_id: int
    created_at: datetime


class DebtHistoryResponse(BaseModel):
    debt_id: int
    reference_id: str
    original_amount: float
    remaining_amount: float
    status: str
    installments: list[DebtHistoryItem]
