from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.group_payment import (
    CancelDebtBody,
    CancelGroupBody,
    CancelGroupResponse,
    CreateGroupPaymentBody,
    CreateGroupPaymentResponse,
    GroupMemberBrief,
    GroupPaymentDetailResponse,
    GroupPaymentListResponse,
    MessageResponse,
    RespondGroupPaymentBody,
    RespondGroupPaymentResponse,
)
from app.services import group_payment_service as svc

router = APIRouter(prefix="/api/v1/group-payments", tags=["group-payments"])


@router.post("/create", response_model=CreateGroupPaymentResponse)
async def create(
    body: CreateGroupPaymentBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    redis = await get_redis()
    return await svc.create_group_payment(db, redis, current_user, body)


@router.get("", response_model=GroupPaymentListResponse)
async def list_all(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_group_payments(db, current_user)


@router.post("/_run-expiry", tags=["admin"])
async def run_expiry(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manual trigger for the Celery Beat expiry sweep (dev/ops without a worker)."""
    return await svc.expire_group_payments(db)


@router.get("/{group_id}", response_model=GroupPaymentDetailResponse)
async def detail(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_detail(db, current_user, group_id)


@router.post("/{group_id}/respond", response_model=RespondGroupPaymentResponse)
async def respond(
    group_id: int,
    body: RespondGroupPaymentBody,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    redis = await get_redis()
    return await svc.respond(db, redis, current_user, group_id, body, background_tasks)


@router.post("/{group_id}/members/{member_id}/remind", response_model=MessageResponse)
async def remind(
    group_id: int,
    member_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    redis = await get_redis()
    return await svc.remind(db, redis, current_user, group_id, member_id)


@router.post("/{group_id}/members/{member_id}/cancel-debt", response_model=MessageResponse)
async def cancel_debt(
    group_id: int,
    member_id: int,
    body: CancelDebtBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.cancel_debt(db, current_user, group_id, member_id, body.reason)


@router.post("/{group_id}/cancel", response_model=CancelGroupResponse)
async def cancel_group(
    group_id: int,
    body: CancelGroupBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.cancel_group(db, current_user, group_id, body.reason)


@router.get("/{group_id}/members", response_model=list[GroupMemberBrief])
async def members(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_members(db, current_user, group_id)
