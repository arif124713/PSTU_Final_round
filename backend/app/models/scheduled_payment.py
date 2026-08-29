import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ScheduleFrequency(str, enum.Enum):
    one_time = "one_time"
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"


class ScheduleStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    cancelled = "cancelled"
    completed = "completed"


class ScheduledPayment(Base):
    __tablename__ = "scheduled_payments"
    __table_args__ = (
        Index("idx_sched_due_date", "next_payment_date", "status"),  # Celery beat daily scan
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reference_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4())
    )

    # Parties
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)  # who pays
    receiver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)  # who receives

    # Payment details
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Schedule definition
    frequency: Mapped[ScheduleFrequency] = mapped_column(Enum(ScheduleFrequency), nullable=False)
    specific_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # one_time only
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0=Sunday..6=Saturday
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-28, monthly + yearly
    month_of_year: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-12, yearly only
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # NULL = runs forever

    # Reminder config
    reminder_days_before: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    reminder_on_due_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # State tracking
    status: Mapped[ScheduleStatus] = mapped_column(
        Enum(ScheduleStatus), nullable=False, default=ScheduleStatus.active
    )
    next_payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_reminder_sent_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_paid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ScheduledPaymentLogStatus(str, enum.Enum):
    reminder_sent = "reminder_sent"
    paid = "paid"
    missed = "missed"
    skipped = "skipped"


class ScheduledPaymentLog(Base):
    """Immutable record of every cycle for every scheduled payment. Never UPDATE or DELETE."""

    __tablename__ = "scheduled_payment_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scheduled_payment_id: Mapped[int] = mapped_column(
        ForeignKey("scheduled_payments.id"), nullable=False, index=True
    )
    cycle_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[ScheduledPaymentLogStatus] = mapped_column(
        Enum(ScheduledPaymentLogStatus), nullable=False
    )
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
