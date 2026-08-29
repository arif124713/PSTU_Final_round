from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import UserSummary

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me", response_model=UserSummary)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserSummary(
        id=current_user.id,
        full_name=current_user.full_name,
        balance=float(current_user.balance),
        role=current_user.role.value,
    )


@router.get("/search")
async def search_users(
    q: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(User)
            .where(
                User.id != current_user.id,
                or_(User.full_name.ilike(f"%{q}%"), User.mobile_number.ilike(f"%{q}%")),
            )
            .limit(20)
        )
    ).scalars().all()
    return [
        {"id": u.id, "full_name": u.full_name, "mobile_last4": u.mobile_number[-4:], "is_active": u.is_active}
        for u in rows
    ]
