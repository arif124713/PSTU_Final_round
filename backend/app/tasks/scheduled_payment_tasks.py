"""Celery Beat — scheduled-payment reminder engine.

Runs every day at 08:00 (Asia/Dhaka). For each active schedule whose due date is
within its reminder window it sends at most one reminder per cycle (Redis-guarded).
Overdue cycles are logged as ``missed`` and advanced. The system never auto-pays.
"""

from app.celery_app import celery_app
from app.services import scheduled_payment_service as svc
from app.tasks._run import run_with_session


@celery_app.task(name="app.tasks.scheduled_payment_tasks.check_scheduled_reminders")
def check_scheduled_reminders() -> dict:
    return run_with_session(svc.run_reminder_scan)
