"""Scan job housekeeping that must not depend on the browser image: the stuck-scan sweeper.

Reliability layer 0 (PROJECT_PLAN 3.15): a worker that dies mid-scan must not leave a scan RUNNING
forever or credits reserved. The sweeper finds scans whose heartbeat stopped, fails them with a
reason, and releases the credit (it was a system fault, not the customer's)."""

import asyncio
import logging
import uuid
from datetime import timedelta

from sqlalchemy import text

from . import billing
from .celery_app import celery_app
from .db import admin_session, tenant_session

log = logging.getLogger(__name__)
USAGE_FEATURE = "urls_monthly"
STALE_AFTER = timedelta(minutes=5)  # RUNNING with no heartbeat this long = worker lost
QUEUED_STALE_AFTER = timedelta(minutes=30)  # never picked up (queue down?)


async def fail_scan(
    org_id: uuid.UUID, scan_id: uuid.UUID, code: str, detail: str, *, system_fault: bool
) -> bool:
    """Mark a scan FAILED exactly once. System faults give the credit back; customer faults keep it."""
    async with tenant_session(org_id) as db:
        row = (
            await db.execute(
                text(
                    "UPDATE scan_jobs SET status='FAILED', error_code=:c, error_detail=:d, finished_at=now() "
                    "WHERE id=:i AND status IN ('QUEUED','RUNNING') RETURNING id"
                ),
                {"c": code, "d": detail, "i": scan_id},
            )
        ).first()
        if row is None:
            return False  # already finished (idempotent)
        if system_fault:
            await billing.release_usage(db, USAGE_FEATURE, str(scan_id))
        else:
            await billing.commit_usage(db, USAGE_FEATURE, str(scan_id))
    return True


async def sweep_stuck_scans() -> int:
    async with admin_session(
        actor_user_id=None, reason="stuck scan sweep", action="system.sweep_scans"
    ) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, organization_id, status FROM scan_jobs WHERE "
                    "(status='RUNNING' AND coalesce(heartbeat_at, started_at) < now() - CAST(:run AS interval)) OR "
                    "(status='QUEUED' AND created_at < now() - CAST(:queued AS interval))"
                ),
                {"run": STALE_AFTER, "queued": QUEUED_STALE_AFTER},
            )
        ).all()
    n = 0
    for r in rows:
        why = (
            "The scan worker stopped responding."
            if r.status == "RUNNING"
            else "The scan was never started."
        )
        if await fail_scan(
            r.organization_id,
            r.id,
            "worker_lost",
            why + " Your credit was returned.",
            system_fault=True,
        ):
            n += 1
    if n:
        log.warning("failed %s stuck scan(s)", n)
    return n


@celery_app.task(name="scans.sweep_stuck")
def sweep_stuck_task() -> int:
    from .db import dispose_engines

    async def run() -> int:
        try:
            return await sweep_stuck_scans()
        finally:
            await dispose_engines()

    return asyncio.run(run())


celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    "sweep-stuck-scans": {"task": "scans.sweep_stuck", "schedule": 120.0},
}
