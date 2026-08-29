import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GroupPaymentStatus(str, enum.Enum):
    open = "open"
    completed = "completed"
    cancelled = "cancelled"
    expired = "expired"


class GroupPayment(Base):
    __tablename__ = "group_payments"
    __table_args__ = (
        Index("idx_group_expires", "expires_at", "status"),  # Celery expiry job
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reference_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    per_person_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)  # excludes creator
    creator_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    collected_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[GroupPaymentStatus] = mapped_column(
        Enum(GroupPaymentStatus), nullable=False, default=GroupPaymentStatus.open, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # created_at + 72h
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class GroupMemberStatus(str, enum.Enum):
    pending = "pending"
    agreed_paid = "agreed_paid"
    agreed_debt = "agreed_debt"
    declined = "declined"
    expired = "expired"
    debt_cancelled = "debt_cancelled"
    refunded = "refunded"


class GroupPaymentMember(Base):
    __tablename__ = "group_payment_members"
    __table_args__ = (
        UniqueConstraint("group_payment_id", "member_id", name="uq_group_member"),
        Index("idx_member_status", "member_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_payment_id: Mapped[int] = mapped_column(ForeignKey("group_payments.id"), nullable=False)
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount_owed: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    status: Mapped[GroupMemberStatus] = mapped_column(
        Enum(GroupMemberStatus), nullable=False, default=GroupMemberStatus.pending
    )
    # FK added with use_alter to break the circular dependency with member_debts.
    debt_id: Mapped[int | None] = mapped_column(
        ForeignKey("member_debts.id", use_alter=True, name="fk_gpm_debt"), nullable=True
    )
    agreed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MemberDebtStatus(str, enum.Enum):
    pending = "pending"
    partially_paid = "partially_paid"
    fully_paid = "fully_paid"
    cancelled = "cancelled"


class MemberDebt(Base):
    """Money owed by a member to a creator due to insufficient balance at agreement time.
    Paid off via auto-deduction in installments when the member receives funds."""

    __tablename__ = "member_debts"
    __table_args__ = (
        Index("idx_debt_debtor", "debtor_id", "status"),  # auto-deduction lookup
        Index("idx_debt_creditor", "creditor_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reference_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4())
    )
    group_payment_id: Mapped[int] = mapped_column(ForeignKey("group_payments.id"), nullable=False)
    group_payment_member_id: Mapped[int] = mapped_column(
        ForeignKey("group_payment_members.id"), nullable=False
    )
    debtor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)  # member who owes
    creditor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)  # creator who is owed
    original_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    remaining_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    status: Mapped[MemberDebtStatus] = mapped_column(
        Enum(MemberDebtStatus), nullable=False, default=MemberDebtStatus.pending
    )
    pre_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fully_paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class DebtPaymentType(str, enum.Enum):
    auto_deduction = "auto_deduction"
    manual = "manual"


class DebtPayment(Base):
    """Immutable log of every auto-deduction installment. Never UPDATE or DELETE."""

    __tablename__ = "debt_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    debt_id: Mapped[int] = mapped_column(ForeignKey("member_debts.id"), nullable=False, index=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    remaining_after: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    payment_type: Mapped[DebtPaymentType] = mapped_column(
        Enum(DebtPaymentType), nullable=False, default=DebtPaymentType.auto_deduction
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
