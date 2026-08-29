"""Bridge for running the async service layer from sync Celery tasks."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.database import AsyncSessionLocal

T = TypeVar("T")


def run_with_session(coro_fn: Callable[..., Awaitable[T]]) -> T:
    """Open a fresh AsyncSession, run ``coro_fn(db)`` to completion, close the session."""

    async def _wrapped() -> T:
        async with AsyncSessionLocal() as db:
            try:
                return await coro_fn(db)
            except Exception:
                await db.rollback()
                raise

    return asyncio.run(_wrapped())
