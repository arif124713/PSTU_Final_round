from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, decode_token
from app.database import get_db
from app.models.user import OtpPurpose
from app.redis_client import get_redis
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    SendOtpRequest,
    SendOtpResponse,
    UserSummary,
    VerifyOtpRequest,
    VerifyOtpResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/send-otp", response_model=SendOtpResponse)
async def send_otp(body: SendOtpRequest, db: AsyncSession = Depends(get_db)):
    expires_in = await auth_service.send_otp(db, body.mobile_number, OtpPurpose.registration)
    return SendOtpResponse(message="OTP sent", otp_expires_in=expires_in)


@router.post("/verify-otp", response_model=VerifyOtpResponse)
async def verify_otp(body: VerifyOtpRequest, db: AsyncSession = Depends(get_db)):
    temp_token = await auth_service.verify_otp(db, body.mobile_number, body.otp_code, OtpPurpose.registration)
    return VerifyOtpResponse(verified=True, temp_token=temp_token)


@router.post("/register", response_model=RegisterResponse)
async def register(
    body: RegisterRequest,
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    temp_token = authorization.removeprefix("Bearer ").strip()
    user = await auth_service.register(db, temp_token, body)
    access_token, _jti = create_access_token(user.id, user.role.value)
    refresh_token, _ = create_access_token(user.id, user.role.value, expires_minutes=60 * 24 * 30)
    return RegisterResponse(
        user_id=user.id,
        access_token=access_token,
        refresh_token=refresh_token,
        balance=float(user.balance),
    )


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user, access_token, refresh_token, _jti = await auth_service.login(
        db, body.mobile_number, body.password, request.client.host if request.client else None
    )
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserSummary(id=user.id, full_name=user.full_name, balance=float(user.balance), role=user.role.value),
    )


@router.post("/logout")
async def logout(authorization: str = Header(...)):
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_token(token)
    jti = payload["jti"]
    exp = payload["exp"]
    import time

    ttl = max(int(exp - time.time()), 1)
    redis = await get_redis()
    await redis.setex(f"jwt:blocklist:{jti}", ttl, "1")
    return {"message": "Logged out"}
