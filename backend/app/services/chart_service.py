import base64
import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User


def _generate_chart_base64(monthly_data: dict[str, float]) -> str:
    fig, ax = plt.subplots(figsize=(8, 4))
    months = list(monthly_data.keys())
    amounts = list(monthly_data.values())

    bars = ax.bar(months, amounts, color="#459af8", alpha=0.9)
    ax.set_title("Monthly Spending (BDT)", fontsize=14, fontweight="bold")
    ax.set_ylabel("Amount (৳)")
    ax.set_xlabel("Month")

    for bar, amount in zip(bars, amounts):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height(),
            f"৳{amount:,.0f}", ha="center", va="bottom", fontsize=9,
        )

    plt.tight_layout()
    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


async def generate_spending_summary(db: AsyncSession, user: User, month: str) -> dict:
    year, mon = (int(x) for x in month.split("-"))
    start = datetime(year, mon, 1)
    end = datetime(year + 1, 1, 1) if mon == 12 else datetime(year, mon + 1, 1)

    total_sent = (
        await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.sender_id == user.id,
                Transaction.status == TransactionStatus.completed,
                Transaction.created_at >= start,
                Transaction.created_at < end,
            )
        )
    ).scalar_one()
    total_received = (
        await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.receiver_id == user.id,
                Transaction.status == TransactionStatus.completed,
                Transaction.created_at >= start,
                Transaction.created_at < end,
            )
        )
    ).scalar_one()

    chart_base64 = _generate_chart_base64({month: float(total_sent)})

    return {
        "summary_text": f"In {month}, you sent ৳{float(total_sent):,.2f} and received ৳{float(total_received):,.2f}.",
        "chart_base64": chart_base64,
        "total_sent": float(total_sent),
        "total_received": float(total_received),
    }
