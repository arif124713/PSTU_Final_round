from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.database import get_db
from app.models.user import User
from app.redis_client import get_redis

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = decode_token(credentials.credentials)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    jti = payload.get("jti")
    user_id = payload.get("sub")
    if not jti or not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    redis = await get_redis()
    if await redis.get(f"jwt:blocklist:{jti}"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session has been revoked")

    user = (await db.execute(select(User).where(User.id == int(user_id)))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    if user.is_frozen:
        raise HTTPException(423, "Your account has been frozen. Contact support.")

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role.value not in ("admin", "support"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return current_user


def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role.value != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super admin access required")
    return current_user
