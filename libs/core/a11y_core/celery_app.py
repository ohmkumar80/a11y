"""Celery wiring. Workers are tenant-aware: every task carries ``org_id`` and opens a
``tenant_session`` with it; there is no way to query without one."""

import asyncio
import uuid

from celery import Celery
from sqlalchemy import text

from .db import tenant_session
from .settings import get_settings

# Separate queues now so separate worker images can consume them later (PROJECT_PLAN 3.9).
QUEUES = ("web", "docs", "media", "mobile", "ai")

celery_app = Celery("a11y", broker=get_settings().redis_url, include=["a11y_core.billing_jobs"])
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Must exceed the longest job (video) or Redis redelivers it mid-run.
    broker_transport_options={"visibility_timeout": 6 * 60 * 60},
    task_default_queue="web",
    task_serializer="json",
    accept_content=["json"],
)


@celery_app.task(name="system.ping")
def ping(org_id: str) -> str:
    """Smoke test: proves a worker can open a tenant-scoped session."""

    async def run() -> str:
        async with tenant_session(uuid.UUID(org_id)) as s:
            return (await s.execute(text("SELECT current_setting('app.org_id')"))).scalar_one()

    return asyncio.run(run())
