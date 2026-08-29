from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from redis.asyncio import Redis

from app.config import settings


def _tomorrow_midnight_ttl() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = datetime.combine(date.today() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    return max(int((tomorrow - now).total_seconds()), 1)


async def check_cooldown(redis: Redis, sender_id: int, receiver_id: int) -> None:
    key = f"cooldown:{sender_id}:{receiver_id}"
    if await redis.get(key):
        ttl = await redis.ttl(key)
        raise HTTPException(429, f"Wait {ttl} seconds before sending to this user again")


async def check_daily_limit(redis: Redis, sender_id: int, amount: float) -> None:
    today = date.today().isoformat()
    key = f"daily_sent:{sender_id}:{today}"
    daily_spent = int(await redis.get(key) or 0)
    if daily_spent + int(amount * 100) > settings.daily_transfer_limit_bdt * 100:
        raise HTTPException(429, "Daily transfer limit exceeded")


async def check_velocity(redis: Redis, sender_id: int) -> bool:
    """Returns True if this transfer should be flagged for review (does not block)."""
    key = f"velocity:{sender_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, settings.velocity_window_seconds)
    return count > settings.velocity_max_transfers


async def check_unusual_amount(redis: Redis, sender_id: int, amount: float, extra_confirmed: bool) -> bool:
    """Returns True if this transfer should be flagged. Raises if extra confirmation was required but missing."""
    if amount <= settings.unusual_amount_threshold:
        return False
    key = f"first_large:{sender_id}"
    is_first = not await redis.get(key)
    if is_first and not extra_confirmed:
        raise HTTPException(422, "Large transfer requires additional confirmation")
    await redis.setex(key, 7 * 86400, "1")
    return is_first


async def check_pin(redis: Redis, user_id: int, pin: str, pin_hash: str, verify_fn) -> None:
    locked = await redis.get(f"pin:locked:{user_id}")
    if locked:
        raise HTTPException(423, "PIN is locked. Try again in 15 minutes")

    if not verify_fn(pin, pin_hash):
        attempts = await redis.incr(f"pin:attempts:{user_id}")
        await redis.expire(f"pin:attempts:{user_id}", settings.pin_lock_seconds)
        if attempts >= settings.pin_max_attempts:
            await redis.setex(f"pin:locked:{user_id}", settings.pin_lock_seconds, "1")
            raise HTTPException(423, "PIN locked after 3 failed attempts")
        raise HTTPException(401, f"Invalid PIN. {settings.pin_max_attempts - attempts} attempts remaining")

    await redis.delete(f"pin:attempts:{user_id}")


async def set_post_transfer_state(redis: Redis, sender_id: int, receiver_id: int, amount: float) -> None:
    cooldown_key = f"cooldown:{sender_id}:{receiver_id}"
    await redis.setex(cooldown_key, settings.cooldown_seconds, "1")

    daily_key = f"daily_sent:{sender_id}:{date.today().isoformat()}"
    await redis.incrby(daily_key, int(amount * 100))
    await redis.expire(daily_key, _tomorrow_midnight_ttl())
