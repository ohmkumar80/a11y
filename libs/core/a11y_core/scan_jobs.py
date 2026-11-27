"""Scan job housekeeping that must not depend on the browser image: the stuck-scan sweeper.

Reliability layer 0 (PROJECT_PLAN 3.15): a worker that dies mid-scan must not leave a scan RUNNING
forever or credits reserved. The sweeper finds scans whose heartbeat stopped, fails them with a
reason, and releases the credit (it was a system fault, not the customer's)."""

import asyncio
import logging
import uuid
from datetime import timedelta

from sqlalchemy import text

from . import billing, notify
from .celery_app import celery_app
from .db import admin_session, tenant_session

log = logging.getLogger(__name__)
USAGE_FEATURE = "urls_monthly"
STALE_AFTER = timedelta(minutes=5)  # RUNNING with no heartbeat this long = worker lost
QUEUED_STALE_AFTER = timedelta(minutes=30)  # never picked up (queue down?)
ORPHAN_AFTER = timedelta(
    hours=1
)  # a reservation this old whose scan already ended was missed by its job

# Errors on the START page that are the customer's doing: the credit is kept.
CUSTOMER_FAULTS = {
    "dns_failed",
    "private_address",
    "invalid_url",
    "invalid_scheme",
    "port_not_allowed",
    "credentials_in_url",
    "not_html",
    "tls_error",
    "unreachable",
    "timeout",
    "blocked_redirect",
    "navigation_failed",
    "robots",
}


def is_customer_fault(code: str | None) -> bool:
    return bool(code) and (code in CUSTOMER_FAULTS or code.startswith("http_"))


async def fail_scan(
    org_id: uuid.UUID,
    scan_id: uuid.UUID,
    code: str,
    detail: str,
    *,
    system_fault: bool,
    email: bool = True,
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
    if email:
        await notify.notify_scan_failed(org_id, scan_id, detail, credit_returned=system_fault)
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


async def sweep_orphaned_reservations() -> dict[str, int]:
    """Settle credits whose job ended without settling them (reliability layer 0, PROJECT_PLAN 3.15).

    A reservation normally becomes COMMITTED or RELEASED when its scan ends. If the worker died between ending the
    scan and settling, or the scan row is gone, the credit would sit RESERVED for ever. Same rules as a live scan:
    a finished scan, or one that failed for a customer reason, keeps the credit; a platform failure, a cancelled
    scan or a scan that no longer exists gives it back. Scans still QUEUED or RUNNING are left to the stuck-scan
    sweeper. Safe to run any time and as often as you like: settling is idempotent."""
    async with admin_session(
        actor_user_id=None, reason="orphaned reservation sweep", action="system.sweep_reservations"
    ) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT r.organization_id, r.job_id, s.status AS scan_status, s.error_code "
                    "FROM usage_reservations r LEFT JOIN scan_jobs s ON s.id::text = r.job_id "
                    "WHERE r.status = 'RESERVED' AND r.feature_key = :f AND r.created_at < now() - CAST(:age AS interval) "
                    "AND (s.id IS NULL OR s.status IN ('SUCCEEDED', 'FAILED', 'CANCELLED'))"
                ),
                {"f": USAGE_FEATURE, "age": ORPHAN_AFTER},
            )
        ).all()
    out = {"committed": 0, "released": 0}
    for r in rows:
        keep = r.scan_status == "SUCCEEDED" or (
            r.scan_status == "FAILED" and is_customer_fault(r.error_code)
        )
        async with tenant_session(r.organization_id) as db:
            if keep:
                ok = await billing.commit_usage(db, USAGE_FEATURE, r.job_id)
            else:
                ok = await billing.release_usage(db, USAGE_FEATURE, r.job_id)
        if ok:
            out["committed" if keep else "released"] += 1
    if any(out.values()):
        log.warning("settled orphaned reservations: %s", out)
    return out


@celery_app.task(name="scans.sweep_stuck")
def sweep_stuck_task() -> int:
    from .db import dispose_engines

    async def run() -> int:
        try:
            return await sweep_stuck_scans()
        finally:
            await dispose_engines()

    return asyncio.run(run())


@celery_app.task(name="scans.sweep_reservations")
def sweep_reservations_task() -> dict[str, int]:
    from .db import dispose_engines

    async def run() -> dict[str, int]:
        try:
            return await sweep_orphaned_reservations()
        finally:
            await dispose_engines()

    return asyncio.run(run())


celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    "sweep-stuck-scans": {"task": "scans.sweep_stuck", "schedule": 120.0},
    "sweep-orphaned-reservations": {"task": "scans.sweep_reservations", "schedule": 600.0},
}
