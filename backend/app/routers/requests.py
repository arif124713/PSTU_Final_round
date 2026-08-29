from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.request import (
    AcceptRequestBody,
    CreateRequestBody,
    CreateRequestResponse,
    RequestListItem,
)
from app.schemas.transaction import SendMoneyResponse
from app.services import request_service

router = APIRouter(prefix="/api/v1/requests", tags=["requests"])


@router.post("/create", response_model=CreateRequestResponse)
async def create(
    body: CreateRequestBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await request_service.create_request(
        db, current_user, body.payer_identifier, body.amount, body.reason, body.expires_in_hours
    )


@router.get("", response_model=list[RequestListItem])
async def list_all(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await request_service.list_requests(db, current_user)


@router.post("/{request_id}/accept", response_model=SendMoneyResponse)
async def accept(
    request_id: int,
    body: AcceptRequestBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    redis = await get_redis()
    return await request_service.accept_request(db, redis, current_user, request_id, body.pin)


@router.post("/{request_id}/decline")
async def decline(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    req = await request_service.decline_request(db, current_user, request_id)
    return {"request_id": req.id, "status": req.status.value}
