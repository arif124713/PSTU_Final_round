import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import qrcode
import io
import base64
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token, create_temp_token, decode_token, hash_secret, verify_secret
from app.models.user import LoginSession, OtpPurpose, OtpStore, User
from app.services.audit_service import write_audit_log

OTP_CODE = "1234"  # demo mode: OTP is always this fixed code


async def send_otp(db: AsyncSession, mobile_number: str, purpose: OtpPurpose) -> int:
    if purpose == OtpPurpose.registration:
        existing = (
            await db.execute(select(User).where(User.mobile_number == mobile_number))
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, "Mobile number already registered")

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=300)
    db.add(
        OtpStore(
            mobile_number=mobile_number,
            otp_code=OTP_CODE,
            purpose=purpose,
            expires_at=expires_at.replace(tzinfo=None),
        )
    )
    await db.commit()
    return 300


async def verify_otp(db: AsyncSession, mobile_number: str, otp_code: str, purpose: OtpPurpose) -> str:
    otp = (
        await db.execute(
            select(OtpStore)
            .where(
                OtpStore.mobile_number == mobile_number,
                OtpStore.purpose == purpose,
                OtpStore.is_used.is_(False),
            )
            .order_by(OtpStore.created_at.desc())
        )
    ).scalars().first()

    if not otp:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No pending OTP for this mobile number")
    if otp.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OTP expired")
    if otp.otp_code != otp_code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OTP")

    otp.is_used = True
    await db.commit()

    return create_temp_token(mobile_number)


def _generate_qr_base64(user_id: int, mobile_number: str) -> str:
    payload = f"moneymove://pay?user_id={user_id}&mobile={mobile_number[-4:]}"
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


async def register(db: AsyncSession, temp_token: str, data) -> User:
    try:
        payload = decode_token(temp_token)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired registration token")
    if payload.get("scope") != "registration":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token scope")

    mobile_number = payload["sub"]

    nid_hash = hashlib.sha256(data.nid_number.encode("utf-8")).hexdigest()
    existing_nid = (
        await db.execute(select(User).where(User.nid_hash == nid_hash))
    ).scalar_one_or_none()
    if existing_nid:
        raise HTTPException(status.HTTP_409_CONFLICT, "This NID is already registered to an account")

    user = User(
        full_name=data.full_name,
        mobile_number=mobile_number,
        email=data.email,
        nid_hash=nid_hash,
        nid_last4=data.nid_number[-4:],
        password_hash=hash_secret(data.password),
        pin_hash=hash_secret(data.transaction_pin),
        balance=Decimal(str(settings.starter_balance_bdt)),
        mobile_verified=True,
    )
    db.add(user)
    await db.flush()

    user.qr_code = _generate_qr_base64(user.id, user.mobile_number)
    await db.commit()
    await db.refresh(user)

    await write_audit_log(db, "ACCOUNT_CREATED", actor_id=user.id, entity_type="user", entity_id=user.id)

    return user


async def login(db: AsyncSession, mobile_number: str, password: str, ip_address: str | None) -> tuple[User, str, str, str]:
    user = (
        await db.execute(select(User).where(User.mobile_number == mobile_number))
    ).scalar_one_or_none()

    if not user or not verify_secret(password, user.password_hash):
        if user:
            await write_audit_log(db, "LOGIN_FAILED", actor_id=user.id, ip_address=ip_address)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid mobile number or password")

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is not active")
    if user.is_frozen:
        raise HTTPException(423, f"Account frozen: {user.frozen_reason or 'contact support'}")

    access_token, jti = create_access_token(user.id, user.role.value)
    refresh_token, _ = create_access_token(user.id, user.role.value, expires_minutes=settings.refresh_token_expire_days * 1440)

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    db.add(
        LoginSession(
            user_id=user.id,
            jwt_jti=jti,
            ip_address=ip_address,
            expires_at=expires_at.replace(tzinfo=None),
        )
    )
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    await write_audit_log(db, "LOGIN_SUCCESS", actor_id=user.id, ip_address=ip_address)

    return user, access_token, refresh_token, jti
