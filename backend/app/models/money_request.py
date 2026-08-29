import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RequestStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"
    expired = "expired"


class MoneyRequest(Base):
    __tablename__ = "money_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reference_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    payer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[RequestStatus] = mapped_column(Enum(RequestStatus), nullable=False, default=RequestStatus.pending, index=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SplitBillStatus(str, enum.Enum):
    open = "open"
    completed = "completed"
    cancelled = "cancelled"


class SplitBill(Base):
    __tablename__ = "split_bills"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reference_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    status: Mapped[SplitBillStatus] = mapped_column(Enum(SplitBillStatus), nullable=False, default=SplitBillStatus.open)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ParticipantStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"


class SplitBillParticipant(Base):
    __tablename__ = "split_bill_participants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    split_bill_id: Mapped[int] = mapped_column(ForeignKey("split_bills.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount_owed: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    money_request_id: Mapped[int | None] = mapped_column(ForeignKey("money_requests.id"), nullable=True)
    status: Mapped[ParticipantStatus] = mapped_column(Enum(ParticipantStatus), nullable=False, default=ParticipantStatus.pending)
