from datetime import date, datetime

from pydantic import BaseModel, Field


class ReceiverBrief(BaseModel):
    full_name: str
    mobile_last4: str


class CreateScheduledPaymentBody(BaseModel):
    receiver_identifier: str
    label: str = Field(..., min_length=1, max_length=100)
    amount: float = Field(..., gt=0)
    note: str | None = Field(None, max_length=255)
    frequency: str = Field(..., pattern="^(one_time|weekly|monthly|yearly)$")
    specific_date: date | None = None
    day_of_week: int | None = Field(None, ge=0, le=6)
    day_of_month: int | None = Field(None, ge=1, le=31)  # business rule narrows to 1-28
    month_of_year: int | None = Field(None, ge=1, le=12)
    start_date: date | None = None
    end_date: date | None = None
    reminder_days_before: int = Field(3, ge=0, le=30)
    reminder_on_due_day: bool = True


class CreateScheduledPaymentResponse(BaseModel):
    reference_id: str
    label: str
    amount: float
    frequency: str
    next_payment_date: date | None
    receiver: ReceiverBrief


class UpdateScheduledPaymentBody(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=100)
    amount: float | None = Field(None, gt=0)
    reminder_days_before: int | None = Field(None, ge=0, le=30)
    note: str | None = Field(None, max_length=255)


class PayNowBody(BaseModel):
    pin: str = Field(..., pattern=r"^\d{6}$")


class PayNowResponse(BaseModel):
    transaction_id: int
    reference_id: str
    new_balance: float
    next_payment_date: date | None


class ScheduledPaymentItem(BaseModel):
    id: int
    reference_id: str
    label: str
    amount: float
    frequency: str
    specific_date: date | None
    day_of_week: int | None
    day_of_month: int | None
    month_of_year: int | None
    next_payment_date: date | None
    reminder_days_before: int
    status: str
    last_paid_at: datetime | None
    total_paid_count: int
    receiver: ReceiverBrief


class ScheduledPaymentListResponse(BaseModel):
    scheduled_payments: list[ScheduledPaymentItem]


class ScheduledPaymentLogItem(BaseModel):
    cycle_date: date
    status: str
    transaction_id: int | None
    paid_at: datetime | None
    created_at: datetime


class ScheduledPaymentDetailResponse(ScheduledPaymentItem):
    history: list[ScheduledPaymentLogItem]


class ScheduledPaymentHistoryResponse(BaseModel):
    total: int
    page: int
    per_page: int
    logs: list[ScheduledPaymentLogItem]
