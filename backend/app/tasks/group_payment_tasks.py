"""Celery Beat — group-payment expiry sweep.

Runs every 30 minutes. Marks pending member invites as ``expired`` once the 72h
window has passed, and marks the whole group ``expired`` if no member ever agreed.
Debts that already exist keep auto-settling — only the invite window closes.
"""

from app.celery_app import celery_app
from app.services import group_payment_service as svc
from app.tasks._run import run_with_session


@celery_app.task(name="app.tasks.group_payment_tasks.expire_group_payments")
def expire_group_payments() -> dict:
    return run_with_session(svc.expire_group_payments)
