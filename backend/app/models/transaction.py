import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TransactionStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    disputed = "disputed"


class TransactionType(str, enum.Enum):
    transfer = "transfer"
    request_fulfillment = "request_fulfillment"
    split_fulfillment = "split_fulfillment"


class InitiatedVia(str, enum.Enum):
    web = "web"
    mobile = "mobile"
    ai_agent = "ai_agent"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reference_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    receiver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=Decimal("0.00"))
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[TransactionStatus] = mapped_column(Enum(TransactionStatus), nullable=False, default=TransactionStatus.pending, index=True)
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False, default=TransactionType.transfer)
    initiated_via: Mapped[InitiatedVia] = mapped_column(Enum(InitiatedVia), nullable=False, default=InitiatedVia.web)
    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    flag_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DraftStatus(str, enum.Enum):
    pending_pin = "pending_pin"
    confirmed = "confirmed"
    expired = "expired"
    cancelled = "cancelled"


class TransactionDraft(Base):
    """Agent-staged transfer awaiting PIN confirmation from the frontend.
    The PIN is never stored here or seen by the LLM."""

    __tablename__ = "transaction_drafts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    draft_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    receiver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    receiver_name: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    initiated_via: Mapped[InitiatedVia] = mapped_column(Enum(InitiatedVia), nullable=False, default=InitiatedVia.ai_agent)
    status: Mapped[DraftStatus] = mapped_column(Enum(DraftStatus), nullable=False, default=DraftStatus.pending_pin, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
