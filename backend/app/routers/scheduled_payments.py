from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.scheduled_payment import (
    CreateScheduledPaymentBody,
    CreateScheduledPaymentResponse,
    PayNowBody,
    PayNowResponse,
    ScheduledPaymentDetailResponse,
    ScheduledPaymentHistoryResponse,
    ScheduledPaymentItem,
    ScheduledPaymentListResponse,
    UpdateScheduledPaymentBody,
)
from app.services import scheduled_payment_service as svc

router = APIRouter(prefix="/api/v1/scheduled", tags=["scheduled-payments"])


@router.post("/create", response_model=CreateScheduledPaymentResponse)
async def create(
    body: CreateScheduledPaymentBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.create_scheduled_payment(db, current_user, body)


@router.get("", response_model=ScheduledPaymentListResponse)
async def list_all(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.list_scheduled_payments(db, current_user)


@router.post("/_run-reminders", tags=["admin"])
async def run_reminders(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manual trigger for the Celery Beat reminder scan (dev/ops without a worker)."""
    return await svc.run_reminder_scan(db)


@router.get("/{schedule_id}", response_model=ScheduledPaymentDetailResponse)
async def detail(
    schedule_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_detail(db, current_user, schedule_id)


@router.put("/{schedule_id}", response_model=ScheduledPaymentItem)
async def update(
    schedule_id: int,
    body: UpdateScheduledPaymentBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.update_scheduled_payment(db, current_user, schedule_id, body)


@router.post("/{schedule_id}/pause")
async def pause(
    schedule_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.pause(db, current_user, schedule_id)


@router.post("/{schedule_id}/resume")
async def resume(
    schedule_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.resume(db, current_user, schedule_id)


@router.delete("/{schedule_id}")
async def cancel(
    schedule_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.cancel(db, current_user, schedule_id)


@router.post("/{schedule_id}/pay-now", response_model=PayNowResponse)
async def pay_now(
    schedule_id: int,
    body: PayNowBody,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    redis = await get_redis()
    return await svc.pay_now(db, redis, current_user, schedule_id, body.pin, background_tasks)


@router.get("/{schedule_id}/history", response_model=ScheduledPaymentHistoryResponse)
async def history(
    schedule_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_history(db, current_user, schedule_id, page, per_page)
