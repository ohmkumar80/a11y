"""Starting and settling PDF audits (ADR 0021).

Quota is counted in document PAGES (`document_pages_monthly`) and reserved when the audit is requested, so a plan limit
can never be raced past. At the end the reservation is settled once: charged when the audit ran (even if it found
problems, or failed because the customer's file is damaged), given back when the failure was ours or the customer
deleted the file first."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import select, text

from . import billing
from .celery_app import celery_app
from .db import admin_session, dispose_engines, tenant_session
from .models import Document, DocumentAudit, DocumentStatus

log = logging.getLogger(__name__)
FEATURE = "document_pages_monthly"
STALE = timedelta(minutes=5)
ORPHAN_AFTER = timedelta(minutes=30)


class AuditRefused(Exception):
    def __init__(self, http_status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.http_status, self.code, self.message = http_status, code, message


def enqueue_audit(org_id: uuid.UUID, audit_id: uuid.UUID) -> bool:
    try:
        celery_app.send_task("docs.audit_pdf", args=[str(org_id), str(audit_id)], queue="docs")
        return True
    except Exception:  # noqa: BLE001
        log.warning("could not enqueue audit %s; the sweeper will retry", audit_id)
        return False


async def start_audit(
    org_id: uuid.UUID, user_id: uuid.UUID | None, doc_id: uuid.UUID
) -> DocumentAudit:
    """Reserve the pages and queue the audit. Raises AuditRefused, or BillingError (quota, locked subscription)."""
    async with tenant_session(org_id) as db:
        doc = (
            await db.execute(select(Document).where(Document.id == doc_id).with_for_update())
        ).scalar_one_or_none()
        if doc is None or doc.status == DocumentStatus.DELETED:
            raise AuditRefused(404, "not_found", "We could not find that document.")
        if doc.kind != "pdf":
            raise AuditRefused(
                422,
                "unsupported_kind",
                "Accessibility checks are available for PDF files so far. Word, PowerPoint and EPUB are coming.",
            )
        if doc.status != DocumentStatus.CLEAN:
            raise AuditRefused(
                409,
                "not_ready",
                "This file has not passed our safety checks yet, so it cannot be audited.",
            )
        busy = (
            await db.execute(
                text(
                    "SELECT 1 FROM document_audits WHERE document_id = :d AND status IN ('QUEUED', 'RUNNING')"
                ),
                {"d": doc_id},
            )
        ).first()
        if busy:
            raise AuditRefused(409, "audit_running", "This document is already being checked.")
        pages = max(1, doc.page_count or 1)
        audit = DocumentAudit(
            id=uuid.uuid4(),
            organization_id=org_id,
            document_id=doc_id,
            pages=pages,
            created_by=user_id,
        )
        db.add(audit)
        await db.flush()
        await billing.reserve(db, org_id, FEATURE, str(audit.id), pages)  # raises QuotaExceeded
    enqueue_audit(org_id, audit.id)
    return audit


async def settle(db, audit_id: uuid.UUID, *, charge: bool) -> None:
    """Charge or give back the reservation, exactly once (idempotent in billing)."""
    fn = billing.commit_usage if charge else billing.release_usage
    await fn(db, FEATURE, str(audit_id))


# --- background sweeps -----------------------------------------------------------------------------


async def requeue_stale_audits() -> int:
    """Audits that were never picked up (broker down) or whose worker died mid-run."""
    async with admin_session(
        actor_user_id=None, reason="audit queue sweep", action="system.requeue_audits"
    ) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, organization_id FROM document_audits WHERE status IN ('QUEUED', 'RUNNING') "
                    "AND coalesce(started_at, created_at) < now() - CAST(:age AS interval) LIMIT 200"
                ),
                {"age": STALE},
            )
        ).all()
    return sum(1 for r in rows if enqueue_audit(r.organization_id, r.id))


async def sweep_audit_reservations() -> dict[str, int]:
    """Give back or charge reservations whose audit ended without settling (a crash between the two writes)."""
    async with admin_session(
        actor_user_id=None,
        reason="orphaned audit reservation sweep",
        action="system.sweep_reservations",
    ) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT r.organization_id, r.job_id, a.status AS audit_status, a.error_code "
                    "FROM usage_reservations r LEFT JOIN document_audits a ON a.id::text = r.job_id "
                    "WHERE r.status = 'RESERVED' AND r.feature_key = :f AND r.created_at < now() - CAST(:age AS interval) "
                    "AND (a.id IS NULL OR a.status IN ('SUCCEEDED', 'FAILED'))"
                ),
                {"f": FEATURE, "age": ORPHAN_AFTER},
            )
        ).all()
    out = {"committed": 0, "released": 0}
    for r in rows:
        keep = r.audit_status == "SUCCEEDED" or (
            r.audit_status == "FAILED" and r.error_code in CUSTOMER_FAULTS
        )
        async with tenant_session(r.organization_id) as db:
            ok = await (billing.commit_usage if keep else billing.release_usage)(
                db, FEATURE, r.job_id
            )
        if ok:
            out["committed" if keep else "released"] += 1
    return out


# Failures that are the customer's file, not our platform: the pages are charged (the work was done).
CUSTOMER_FAULTS = frozenset({"corrupt", "encrypted"})


@celery_app.task(name="documents.requeue_audits")
def requeue_audits_task() -> int:
    import asyncio

    async def run() -> int:
        try:
            return await requeue_stale_audits()
        finally:
            await dispose_engines()

    return asyncio.run(run())


@celery_app.task(name="documents.sweep_audit_reservations")
def sweep_audit_reservations_task() -> dict[str, int]:
    import asyncio

    async def run() -> dict[str, int]:
        try:
            return await sweep_audit_reservations()
        finally:
            await dispose_engines()

    return asyncio.run(run())


celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    "requeue-stale-audits": {"task": "documents.requeue_audits", "schedule": 300.0},
    "sweep-audit-reservations": {"task": "documents.sweep_audit_reservations", "schedule": 600.0},
}
