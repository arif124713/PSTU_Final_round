from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

# Hackathon note: the spec routes audit writes through a Celery worker so the
# API path never blocks on them. We keep that same call-site shape here
# (a single write_audit_log entrypoint) so it's a drop-in swap to
# `write_audit_log_task.delay(...)` once a Celery worker is running; for now
# it writes directly and is called with `asyncio.create_task` so it never
# blocks the response.


async def write_audit_log(
    db: AsyncSession,
    event_type: str,
    actor_id: int | None = None,
    target_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    payload: dict | None = None,
    ip_address: str | None = None,
) -> None:
    db.add(
        AuditLog(
            event_type=event_type,
            actor_id=actor_id,
            target_id=target_id,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            ip_address=ip_address,
        )
    )
    await db.commit()
