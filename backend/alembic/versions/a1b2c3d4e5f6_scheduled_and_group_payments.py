"""scheduled payments + group payments

Revision ID: a1b2c3d4e5f6
Revises: f112fb5f3228
Create Date: 2026-08-29 13:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f112fb5f3228"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Enum value sets ────────────────────────────────────────────────────────
NOTIFICATION_TYPES_NEW = (
    "money_received", "money_sent", "request_received", "request_accepted",
    "request_declined", "account_frozen", "ticket_update", "security_alert", "system",
    "scheduled_reminder", "scheduled_due_today", "scheduled_paid", "scheduled_missed",
    "scheduled_failed", "group_invite", "group_member_paid", "group_member_agreed_debt",
    "group_member_declined", "group_invite_agreed", "group_invite_agreed_debt",
    "group_debt_reminder", "group_debt_auto_paid_partial", "group_debt_fully_paid",
    "group_debt_cancelled", "group_completed", "group_cancelled", "group_expired",
    "group_member_expired",
)
NOTIFICATION_TYPES_OLD = (
    "money_received", "money_sent", "request_received", "request_accepted",
    "request_declined", "account_frozen", "ticket_update", "security_alert", "system",
)
TX_TYPES_NEW = (
    "transfer", "request_fulfillment", "split_fulfillment", "scheduled_payment",
    "group_payment", "group_payment_refund", "debt_settlement",
)
TX_TYPES_OLD = ("transfer", "request_fulfillment", "split_fulfillment")
INITIATED_VIA_NEW = ("web", "mobile", "ai_agent", "system")
INITIATED_VIA_OLD = ("web", "mobile", "ai_agent")


def _enum_ddl(values: Sequence[str]) -> str:
    return "ENUM(" + ", ".join(f"'{v}'" for v in values) + ")"


def _modify_enum(table: str, column: str, values: Sequence[str], nullable: bool = False) -> None:
    null_sql = "NULL" if nullable else "NOT NULL"
    op.execute(f"ALTER TABLE {table} MODIFY COLUMN {column} {_enum_ddl(values)} {null_sql}")


def upgrade() -> None:
    bind = op.get_bind()
    is_mysql = bind.dialect.name == "mysql"

    # ── Widen existing enum columns (MySQL only; other dialects use VARCHAR checks) ──
    if is_mysql:
        _modify_enum("notifications", "type", NOTIFICATION_TYPES_NEW)
        _modify_enum("transactions", "type", TX_TYPES_NEW)
        _modify_enum("transactions", "initiated_via", INITIATED_VIA_NEW)
        _modify_enum("transaction_drafts", "initiated_via", INITIATED_VIA_NEW)

    # ── scheduled_payments ────────────────────────────────────────────────
    op.create_table(
        "scheduled_payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reference_id", sa.String(length=36), nullable=False),
        sa.Column("creator_id", sa.Integer(), nullable=False),
        sa.Column("receiver_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "frequency",
            sa.Enum("one_time", "weekly", "monthly", "yearly", name="schedulefrequency"),
            nullable=False,
        ),
        sa.Column("specific_date", sa.Date(), nullable=True),
        sa.Column("day_of_week", sa.Integer(), nullable=True),
        sa.Column("day_of_month", sa.Integer(), nullable=True),
        sa.Column("month_of_year", sa.Integer(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("reminder_days_before", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("reminder_on_due_day", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "status",
            sa.Enum("active", "paused", "cancelled", "completed", name="schedulestatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("next_payment_date", sa.Date(), nullable=True),
        sa.Column("last_paid_at", sa.DateTime(), nullable=True),
        sa.Column("last_reminder_sent_date", sa.Date(), nullable=True),
        sa.Column("total_paid_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["receiver_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference_id"),
    )
    op.create_index("ix_scheduled_payments_creator_id", "scheduled_payments", ["creator_id"])
    op.create_index(
        "idx_sched_due_date", "scheduled_payments", ["next_payment_date", "status"]
    )

    op.create_table(
        "scheduled_payment_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scheduled_payment_id", sa.Integer(), nullable=False),
        sa.Column("cycle_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "reminder_sent", "paid", "missed", "skipped", name="scheduledpaymentlogstatus"
            ),
            nullable=False,
        ),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["scheduled_payment_id"], ["scheduled_payments.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduled_payment_logs_scheduled_payment_id",
        "scheduled_payment_logs",
        ["scheduled_payment_id"],
    )
    op.create_index("ix_scheduled_payment_logs_cycle_date", "scheduled_payment_logs", ["cycle_date"])

    # ── group_payments ───────────────────────────────────────────────────
    op.create_table(
        "group_payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reference_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("creator_id", sa.Integer(), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("per_person_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("creator_included", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "collected_amount",
            sa.Numeric(precision=15, scale=2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("open", "completed", "cancelled", "expired", name="grouppaymentstatus"),
            nullable=False,
            server_default="open",
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference_id"),
    )
    op.create_index("ix_group_payments_creator_id", "group_payments", ["creator_id"])
    op.create_index("ix_group_payments_status", "group_payments", ["status"])
    op.create_index("idx_group_expires", "group_payments", ["expires_at", "status"])

    # group_payment_members — debt_id FK added after member_debts exists (circular).
    op.create_table(
        "group_payment_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_payment_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("amount_owed", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "agreed_paid", "agreed_debt", "declined", "expired",
                "debt_cancelled", "refunded", name="groupmemberstatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("debt_id", sa.Integer(), nullable=True),
        sa.Column("agreed_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.Column("last_reminder_sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["group_payment_id"], ["group_payments.id"]),
        sa.ForeignKeyConstraint(["member_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_payment_id", "member_id", name="uq_group_member"),
    )
    op.create_index("idx_member_status", "group_payment_members", ["member_id", "status"])

    op.create_table(
        "member_debts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reference_id", sa.String(length=36), nullable=False),
        sa.Column("group_payment_id", sa.Integer(), nullable=False),
        sa.Column("group_payment_member_id", sa.Integer(), nullable=False),
        sa.Column("debtor_id", sa.Integer(), nullable=False),
        sa.Column("creditor_id", sa.Integer(), nullable=False),
        sa.Column("original_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("remaining_amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "partially_paid", "fully_paid", "cancelled", name="memberdebtstatus"
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("pre_authorized", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_reason", sa.String(length=255), nullable=True),
        sa.Column("fully_paid_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["group_payment_id"], ["group_payments.id"]),
        sa.ForeignKeyConstraint(["group_payment_member_id"], ["group_payment_members.id"]),
        sa.ForeignKeyConstraint(["debtor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["creditor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference_id"),
    )
    op.create_index("idx_debt_debtor", "member_debts", ["debtor_id", "status"])
    op.create_index("idx_debt_creditor", "member_debts", ["creditor_id", "status"])

    op.create_foreign_key(
        "fk_gpm_debt", "group_payment_members", "member_debts", ["debt_id"], ["id"]
    )

    op.create_table(
        "debt_payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("debt_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("remaining_after", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column(
            "payment_type",
            sa.Enum("auto_deduction", "manual", name="debtpaymenttype"),
            nullable=False,
            server_default="auto_deduction",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["debt_id"], ["member_debts.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_debt_payments_debt_id", "debt_payments", ["debt_id"])


def downgrade() -> None:
    bind = op.get_bind()
    is_mysql = bind.dialect.name == "mysql"

    op.drop_index("ix_debt_payments_debt_id", table_name="debt_payments")
    op.drop_table("debt_payments")

    op.drop_constraint("fk_gpm_debt", "group_payment_members", type_="foreignkey")
    op.drop_index("idx_debt_creditor", table_name="member_debts")
    op.drop_index("idx_debt_debtor", table_name="member_debts")
    op.drop_table("member_debts")

    op.drop_index("idx_member_status", table_name="group_payment_members")
    op.drop_table("group_payment_members")

    op.drop_index("idx_group_expires", table_name="group_payments")
    op.drop_index("ix_group_payments_status", table_name="group_payments")
    op.drop_index("ix_group_payments_creator_id", table_name="group_payments")
    op.drop_table("group_payments")

    op.drop_index("ix_scheduled_payment_logs_cycle_date", table_name="scheduled_payment_logs")
    op.drop_index(
        "ix_scheduled_payment_logs_scheduled_payment_id", table_name="scheduled_payment_logs"
    )
    op.drop_table("scheduled_payment_logs")

    op.drop_index("idx_sched_due_date", table_name="scheduled_payments")
    op.drop_index("ix_scheduled_payments_creator_id", table_name="scheduled_payments")
    op.drop_table("scheduled_payments")

    for enum_name in (
        "debtpaymenttype", "memberdebtstatus", "groupmemberstatus", "grouppaymentstatus",
        "scheduledpaymentlogstatus", "schedulestatus", "schedulefrequency",
    ):
        sa.Enum(name=enum_name).drop(bind, checkfirst=True)

    if is_mysql:
        _modify_enum("transaction_drafts", "initiated_via", INITIATED_VIA_OLD)
        _modify_enum("transactions", "initiated_via", INITIATED_VIA_OLD)
        _modify_enum("transactions", "type", TX_TYPES_OLD)
        _modify_enum("notifications", "type", NOTIFICATION_TYPES_OLD)
