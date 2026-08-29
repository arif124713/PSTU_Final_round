"""Celery application + Beat schedule.

Run the worker + beat together:

    celery -A app.celery_app.celery_app worker --beat --loglevel=info

Both features degrade gracefully without a running worker: the reminder scan and
the expiry sweep are also exposed as admin endpoints
(`POST /api/v1/scheduled/_run-reminders`, `POST /api/v1/group-payments/_run-expiry`)
and the debt auto-deduction runs inline as a FastAPI BackgroundTask.
"""

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "moneymove",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.scheduled_payment_tasks",
        "app.tasks.group_payment_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Dhaka",
    enable_utc=False,
    beat_schedule={
        # Scheduled-payment reminders — every day at 08:00 Asia/Dhaka.
        "check-scheduled-payment-reminders": {
            "task": "app.tasks.scheduled_payment_tasks.check_scheduled_reminders",
            "schedule": crontab(hour=8, minute=0),
        },
        # Group-payment expiry sweep — every 30 minutes.
        "expire-group-payments": {
            "task": "app.tasks.group_payment_tasks.expire_group_payments",
            "schedule": crontab(minute="*/30"),
        },
    },
)
