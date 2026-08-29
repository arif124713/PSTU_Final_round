from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.notification import Notification
from app.models.user import User

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class MarkReadBody(BaseModel):
    notification_ids: list[int] | None = None
    all_read: bool = False


@router.get("")
async def list_notifications(
    unread_only: bool = False,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conditions = [Notification.user_id == current_user.id]
    if unread_only:
        conditions.append(Notification.is_read.is_(False))

    rows = (
        await db.execute(
            select(Notification)
            .where(*conditions)
            .order_by(Notification.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).scalars().all()

    unread_count = (
        await db.execute(
            select(func.count()).where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        )
    ).scalar_one()

    return {
        "unread_count": unread_count,
        "notifications": [
            {
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "type": n.type.value,
                "reference_id": n.reference_id,
                "is_read": n.is_read,
                "created_at": n.created_at,
            }
            for n in rows
        ],
    }


@router.post("/mark-read")
async def mark_read(
    body: MarkReadBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = update(Notification).where(Notification.user_id == current_user.id)
    if not body.all_read:
        if not body.notification_ids:
            return {"updated": 0}
        stmt = stmt.where(Notification.id.in_(body.notification_ids))
    stmt = stmt.values(is_read=True)
    result = await db.execute(stmt)
    await db.commit()
    return {"updated": result.rowcount}
