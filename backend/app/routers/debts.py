from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.group_payment import DebtHistoryResponse, MyDebtsResponse, OwedToMeResponse
from app.services import group_payment_service as svc

router = APIRouter(prefix="/api/v1/debts", tags=["debts"])


@router.get("/my-debts", response_model=MyDebtsResponse)
async def my_debts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.my_debts(db, current_user)


@router.get("/owed-to-me", response_model=OwedToMeResponse)
async def owed_to_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.owed_to_me(db, current_user)


@router.get("/{debt_id}/history", response_model=DebtHistoryResponse)
async def debt_history(
    debt_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.debt_history(db, current_user, debt_id)
