import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.money_request import MoneyRequest, RequestStatus
from app.models.notification import NotificationType
from app.models.transaction import InitiatedVia
from app.models.user import User
from app.schemas.request import CreateRequestResponse, RequestListItem
from app.services.audit_service import write_audit_log
from app.services.notification_service import send_notification
from app.services.transfer_service import _check_receiver_valid, resolve_receiver, send_money


async def create_request(
    db: AsyncSession,
    requester: User,
    payer_identifier: str,
    amount: float,
    reason: str | None,
    expires_in_hours: int,
) -> CreateRequestResponse:
    payer = await resolve_receiver(db, payer_identifier)
    payer = _check_receiver_valid(payer, requester.id)

    expires_at = (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).replace(tzinfo=None)
    req = MoneyRequest(
        reference_id=str(uuid.uuid4()),
        requester_id=requester.id,
        payer_id=payer.id,
        amount=Decimal(str(amount)),
        reason=reason,
        expires_at=expires_at,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    await send_notification(
        db, payer.id, NotificationType.request_received,
        "Money request",
        f"{requester.full_name} requested ৳{amount:,.2f} from you." + (f" Reason: {reason}" if reason else ""),
        req.reference_id,
    )
    await write_audit_log(db, "REQUEST_CREATED", actor_id=requester.id, target_id=payer.id, entity_type="money_request", entity_id=req.id)

    return CreateRequestResponse(request_id=req.id, reference_id=req.reference_id, status=req.status.value, expires_at=req.expires_at)


async def _get_owned_request(db: AsyncSession, request_id: int, payer_id: int) -> MoneyRequest:
    req = (await db.execute(select(MoneyRequest).where(MoneyRequest.id == request_id))).scalar_one_or_none()
    if not req:
        raise HTTPException(404, "Request not found")
    if req.payer_id != payer_id:
        raise HTTPException(403, "You are not the payer for this request")
    if req.status != RequestStatus.pending:
        raise HTTPException(422, f"Request is already {req.status.value}")
    if req.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        req.status = RequestStatus.expired
        await db.commit()
        raise HTTPException(422, "Request has expired")
    return req


async def accept_request(
    db: AsyncSession, redis: Redis, payer: User, request_id: int, pin: str, background_tasks=None
):
    req = await _get_owned_request(db, request_id, payer.id)
    requester = (await db.execute(select(User).where(User.id == req.requester_id))).scalar_one()

    result = await send_money(
        db, redis, payer,
        idempotency_key=f"request-{req.reference_id}",
        receiver_identifier=str(requester.id),
        amount=float(req.amount),
        pin=pin,
        note=f"Paid request: {req.reason or ''}".strip(),
        extra_confirmed=True,
        initiated_via=InitiatedVia.web,
        background_tasks=background_tasks,
    )

    req.status = RequestStatus.accepted
    req.transaction_id = result.transaction_id
    req.responded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    await send_notification(
        db, req.requester_id, NotificationType.request_accepted,
        "Request paid", f"{payer.full_name} paid your ৳{float(req.amount):,.2f} request", req.reference_id,
    )
    await write_audit_log(db, "REQUEST_ACCEPTED", actor_id=payer.id, target_id=req.requester_id, entity_type="money_request", entity_id=req.id)

    return result


async def decline_request(db: AsyncSession, payer: User, request_id: int):
    req = await _get_owned_request(db, request_id, payer.id)
    req.status = RequestStatus.declined
    req.responded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    await send_notification(
        db, req.requester_id, NotificationType.request_declined,
        "Request declined", f"{payer.full_name} declined your ৳{float(req.amount):,.2f} request", req.reference_id,
    )
    await write_audit_log(db, "REQUEST_DECLINED", actor_id=payer.id, target_id=req.requester_id, entity_type="money_request", entity_id=req.id)
    return req


async def list_requests(db: AsyncSession, user: User) -> list[RequestListItem]:
    rows = (
        await db.execute(
            select(MoneyRequest).where(
                or_(MoneyRequest.requester_id == user.id, MoneyRequest.payer_id == user.id)
            ).order_by(MoneyRequest.created_at.desc())
        )
    ).scalars().all()

    counterparty_ids = {r.payer_id if r.requester_id == user.id else r.requester_id for r in rows}
    counterparties = {}
    if counterparty_ids:
        users = (await db.execute(select(User).where(User.id.in_(counterparty_ids)))).scalars().all()
        counterparties = {u.id: u for u in users}

    items = []
    for r in rows:
        is_requester = r.requester_id == user.id
        counterparty = counterparties.get(r.payer_id if is_requester else r.requester_id)
        items.append(
            RequestListItem(
                request_id=r.id,
                reference_id=r.reference_id,
                amount=float(r.amount),
                reason=r.reason,
                status=r.status.value,
                direction="outgoing" if is_requester else "incoming",
                counterparty_name=counterparty.full_name if counterparty else "Unknown",
                expires_at=r.expires_at,
                created_at=r.created_at,
            )
        )
    return items
