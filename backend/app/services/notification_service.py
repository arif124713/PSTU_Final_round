from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType

# Same note as audit_service: spec routes this through Celery. Same shape,
# direct write for now, swappable to a task later.


async def send_notification(
    db: AsyncSession,
    user_id: int,
    type_: NotificationType,
    title: str,
    body: str,
    reference_id: str | None = None,
) -> None:
    db.add(
        Notification(
            user_id=user_id,
            type=type_,
            title=title,
            body=body,
            reference_id=reference_id,
        )
    )
    await db.commit()
