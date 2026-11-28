"""Guided fixes for PDFs: save the plan a person is editing, then queue the build (ADR 0022).

The build reads the ORIGINAL (only if CLEAN), applies the plan to a copy, re-checks the copy and stores it as a new
document linked to the original. Pages are reserved when the build is requested (one reservation covers the build and its
re-check) and settled once, like an audit."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from . import billing
from .celery_app import celery_app
from .db import admin_session, dispose_engines, tenant_session
from .doc_fix import FixPlan, check_against
from .document_audits import FEATURE
from .models import Document, DocumentAudit, DocumentFix, DocumentStatus

log = logging.getLogger(__name__)
STALE = timedelta(minutes=5)


class FixRefused(Exception):
    def __init__(self, http_status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.http_status, self.code, self.message = http_status, code, message


async def _editable(db, doc_id: uuid.UUID):
    """(document, the audit whose structure the plan is written against). Raises FixRefused."""
    doc = (
        await db.execute(select(Document).where(Document.id == doc_id).with_for_update())
    ).scalar_one_or_none()
    if doc is None or doc.status == DocumentStatus.DELETED:
        raise FixRefused(404, "not_found", "We could not find that document.")
    if doc.kind != "pdf":
        raise FixRefused(
            422, "unsupported_kind", "Guided fixes are available for PDF files so far."
        )
    if doc.status != DocumentStatus.CLEAN:
        raise FixRefused(409, "not_ready", "This file has not passed our safety checks yet.")
    audit = (
        await db.execute(
            select(DocumentAudit)
            .where(DocumentAudit.document_id == doc_id, DocumentAudit.status == "SUCCEEDED")
            .order_by(DocumentAudit.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if audit is None or not audit.structure:
        raise FixRefused(
            409,
            "needs_audit",
            "Check this document's accessibility first, then you can fix what was found.",
        )
    return doc, audit


async def get_state(org_id: uuid.UUID, doc_id: uuid.UUID) -> dict:
    """What the fix editor shows: the editable structure, the plan in progress and the latest fix."""
    async with tenant_session(org_id) as db:
        doc, audit = await _editable(db, doc_id)
        fix = (
            await db.execute(
                select(DocumentFix)
                .where(DocumentFix.document_id == doc_id)
                .order_by(DocumentFix.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return {"document": doc, "audit": audit, "fix": fix}


async def _reserved_for_review(db, doc_id: uuid.UUID) -> None:
    """While a reviewer holds a document, the customer cannot change its plan underneath them."""
    held = (
        await db.execute(
            text("SELECT 1 FROM document_reviews WHERE document_id = :d AND status = 'IN_REVIEW'"),
            {"d": doc_id},
        )
    ).first()
    if held:
        raise FixRefused(
            409,
            "in_review",
            "A reviewer is working on this document. You will be told when they finish.",
        )


async def save_plan(
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    doc_id: uuid.UUID,
    plan: FixPlan,
    *,
    by_reviewer: bool = False,
) -> DocumentFix:
    async with tenant_session(org_id) as db:
        doc, audit = await _editable(db, doc_id)
        if not by_reviewer:
            await _reserved_for_review(db, doc_id)
        if problems := check_against(plan, audit.structure):
            raise FixRefused(422, "invalid_plan", problems[0])
        fix = (
            await db.execute(
                select(DocumentFix)
                .where(
                    DocumentFix.document_id == doc_id,
                    DocumentFix.status.in_(("DRAFT", "QUEUED", "RUNNING")),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if fix is not None and fix.status != "DRAFT":
            raise FixRefused(
                409,
                "fix_running",
                "A fixed copy of this document is being built. Wait for it to finish.",
            )
        if fix is None:
            fix = DocumentFix(
                id=uuid.uuid4(), organization_id=org_id, document_id=doc_id, created_by=user_id
            )
            db.add(fix)
        fix.audit_id, fix.plan, fix.updated_at = (
            audit.id,
            plan.model_dump(exclude_none=True),
            datetime.now(UTC),
        )
        await db.flush()
        return fix


def enqueue_build(org_id: uuid.UUID, fix_id: uuid.UUID) -> bool:
    try:
        celery_app.send_task("docs.build_fix", args=[str(org_id), str(fix_id)], queue="docs")
        return True
    except Exception:  # noqa: BLE001
        log.warning("could not enqueue fix %s; the sweeper will retry", fix_id)
        return False


async def start_build(
    org_id: uuid.UUID, doc_id: uuid.UUID, *, charge_pages: bool = True, by_reviewer: bool = False
) -> DocumentFix:
    """Queue the build. A person's own build reserves the document's pages; a reviewer's build does not, because the
    customer already paid for the review (ADR 0023)."""
    async with tenant_session(org_id) as db:
        doc, _ = await _editable(db, doc_id)
        if not by_reviewer:
            await _reserved_for_review(db, doc_id)
        fix = (
            await db.execute(
                select(DocumentFix).where(
                    DocumentFix.document_id == doc_id, DocumentFix.status == "DRAFT"
                )
            )
        ).scalar_one_or_none()
        if fix is None:
            running = (
                await db.execute(
                    text(
                        "SELECT 1 FROM document_fixes WHERE document_id = :d AND status IN ('QUEUED', 'RUNNING')"
                    ),
                    {"d": doc_id},
                )
            ).first()
            raise FixRefused(
                409,
                "fix_running" if running else "no_plan",
                "A fixed copy is already being built." if running else "Choose what to fix first.",
            )
        plan = FixPlan(**fix.plan)
        if plan.is_empty():
            raise FixRefused(422, "no_plan", "Choose at least one thing to fix first.")
        fix.pages = max(1, doc.page_count or 1)
        fix.status, fix.updated_at = "QUEUED", datetime.now(UTC)
        await db.flush()
        if charge_pages:
            await billing.reserve(
                db, org_id, FEATURE, str(fix.id), fix.pages
            )  # raises QuotaExceeded
    enqueue_build(org_id, fix.id)
    return fix


# --- background sweep ---------------------------------------------------------------------------------


async def requeue_stale_fixes() -> int:
    async with admin_session(
        actor_user_id=None, reason="fix queue sweep", action="system.requeue_fixes"
    ) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, organization_id FROM document_fixes WHERE status IN ('QUEUED', 'RUNNING') "
                    "AND coalesce(started_at, updated_at) < now() - CAST(:age AS interval) LIMIT 200"
                ),
                {"age": STALE},
            )
        ).all()
    return sum(1 for r in rows if enqueue_build(r.organization_id, r.id))


@celery_app.task(name="documents.requeue_fixes")
def requeue_fixes_task() -> int:
    import asyncio

    async def run() -> int:
        try:
            return await requeue_stale_fixes()
        finally:
            await dispose_engines()

    return asyncio.run(run())


celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    "requeue-stale-fixes": {"task": "documents.requeue_fixes", "schedule": 300.0},
}
