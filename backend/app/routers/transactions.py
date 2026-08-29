from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.transaction import InitiatedVia
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.transaction import (
    ConfirmDraftRequest,
    ConfirmDraftResponse,
    SendMoneyRequest,
    SendMoneyResponse,
    TransactionDetailResponse,
    TransactionHistoryResponse,
    ValidateReceiverRequest,
    ValidateReceiverResponse,
)
from app.services import transfer_service

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


@router.post("/validate-receiver", response_model=ValidateReceiverResponse)
async def validate_receiver(
    body: ValidateReceiverRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await transfer_service.validate_receiver(db, current_user.id, body.receiver_identifier)


@router.post("/send", response_model=SendMoneyResponse)
async def send_money(
    body: SendMoneyRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    redis = await get_redis()
    return await transfer_service.send_money(
        db,
        redis,
        current_user,
        body.idempotency_key,
        body.receiver_identifier,
        body.amount,
        body.pin,
        body.note,
        body.extra_confirmed,
        InitiatedVia.web,
        background_tasks=background_tasks,
    )


@router.post("/confirm", response_model=ConfirmDraftResponse)
async def confirm_draft(
    body: ConfirmDraftRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    redis = await get_redis()
    result = await transfer_service.confirm_draft(
        db, redis, current_user, body.draft_id, body.pin, background_tasks
    )
    return ConfirmDraftResponse(status=result.status, reference_id=result.reference_id, new_balance=result.new_balance)


@router.get("/history", response_model=TransactionHistoryResponse)
async def history(
    type: str = Query("all", pattern="^(sent|received|all)$"),
    status: str = Query("all", pattern="^(completed|pending|failed|disputed|all)$"),
    from_date: str | None = None,
    to_date: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await transfer_service.get_history(db, current_user, type, status, from_date, to_date, page, per_page)


@router.get("/{reference_id}", response_model=TransactionDetailResponse)
async def detail(
    reference_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await transfer_service.get_detail(db, current_user, reference_id)
