import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NotificationType(str, enum.Enum):
    money_received = "money_received"
    money_sent = "money_sent"
    request_received = "request_received"
    request_accepted = "request_accepted"
    request_declined = "request_declined"
    account_frozen = "account_frozen"
    ticket_update = "ticket_update"
    security_alert = "security_alert"
    system = "system"
    # Scheduled payments
    scheduled_reminder = "scheduled_reminder"
    scheduled_due_today = "scheduled_due_today"
    scheduled_paid = "scheduled_paid"
    scheduled_missed = "scheduled_missed"
    scheduled_failed = "scheduled_failed"
    # Group payments
    group_invite = "group_invite"
    group_member_paid = "group_member_paid"
    group_member_agreed_debt = "group_member_agreed_debt"
    group_member_declined = "group_member_declined"
    group_invite_agreed = "group_invite_agreed"
    group_invite_agreed_debt = "group_invite_agreed_debt"
    group_debt_reminder = "group_debt_reminder"
    group_debt_auto_paid_partial = "group_debt_auto_paid_partial"
    group_debt_fully_paid = "group_debt_fully_paid"
    group_debt_cancelled = "group_debt_cancelled"
    group_completed = "group_completed"
    group_cancelled = "group_cancelled"
    group_expired = "group_expired"
    group_member_expired = "group_member_expired"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
