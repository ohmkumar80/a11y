"""Celery wiring. Workers are tenant-aware: every task carries ``org_id`` and opens a
``tenant_session`` with it; there is no way to query without one."""

import asyncio
import importlib.util
import uuid

from celery import Celery
from sqlalchemy import text

from .db import tenant_session
from .settings import get_settings

# Separate queues now so separate worker images can consume them later (PROJECT_PLAN 3.9).
QUEUES = ("system", "web", "docs", "media", "mobile", "ai")

# Task modules a worker loads. The browser scanner only exists in the web-worker image.
_include = [
    "a11y_core.billing_jobs",
    "a11y_core.scan_jobs",
    "a11y_core.notify",
    "a11y_core.webhooks",
]
if importlib.util.find_spec("a11y_web_audit"):
    _include.append("a11y_web_audit.tasks")
if importlib.util.find_spec("a11y_documents"):
    _include.append("a11y_documents.tasks")

celery_app = Celery("a11y", broker=get_settings().redis_url, include=_include)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Must exceed the longest job (video) or Redis redelivers it mid-run.
    broker_transport_options={"visibility_timeout": 6 * 60 * 60},
    task_default_queue="system",
    # Browser work needs the Playwright image, so it has its own queue and worker (PROJECT_PLAN 3.9).
    task_routes={
        "web.*": {"queue": "web"},
        "docs.*": {"queue": "docs"},
        "billing.*": {"queue": "system"},
        "scans.*": {"queue": "system"},
    },
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
