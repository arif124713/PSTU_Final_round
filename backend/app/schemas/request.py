from datetime import datetime

from pydantic import BaseModel, Field


class CreateRequestBody(BaseModel):
    payer_identifier: str
    amount: float = Field(..., gt=0)
    reason: str | None = None
    expires_in_hours: int = 48


class CreateRequestResponse(BaseModel):
    request_id: int
    reference_id: str
    status: str
    expires_at: datetime


class AcceptRequestBody(BaseModel):
    pin: str = Field(..., pattern=r"^\d{6}$")


class RequestListItem(BaseModel):
    request_id: int
    reference_id: str
    amount: float
    reason: str | None
    status: str
    direction: str  # "incoming" | "outgoing"
    counterparty_name: str
    expires_at: datetime
    created_at: datetime
