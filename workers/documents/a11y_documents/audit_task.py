"""The ``docs.audit_pdf`` task: run the PDF accessibility checks on one clean document and store the findings (ADR 0021).

Reads the file only through `documents.load_clean` (which refuses anything not CLEAN and verifies its checksum).
Settles the page reservation exactly once. Idempotent: a finished audit is never changed by a redelivered task."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from a11y_core import document_audits as da
from a11y_core import documents
from a11y_core.celery_app import celery_app
from a11y_core.db import dispose_engines, tenant_session
from a11y_core.models import DocumentAudit, DocumentFinding, DocumentStatus
from a11y_core.storage import StorageError

from .pdf_audit import AuditError, audit_pdf

log = logging.getLogger(__name__)
SYSTEM_FAULT = "We could not finish checking this file because of a problem on our side. Your pages were not used. Please try again later."


async def _fail(org_id, audit_id, code: str, detail: str, *, charge: bool) -> str:
    async with tenant_session(org_id) as db:
        a = await db.get(DocumentAudit, audit_id)
        if a is None or a.status in ("SUCCEEDED", "FAILED"):
            return a.status if a else "GONE"
        a.status, a.error_code, a.error_detail = "FAILED", code, detail
        a.finished_at = datetime.now(UTC)
        await da.settle(db, audit_id, charge=charge)
    return "FAILED"


async def run_audit(org_id: uuid.UUID, audit_id: uuid.UUID) -> str:
    async with tenant_session(org_id) as db:
        a = await db.get(DocumentAudit, audit_id)
        if a is None or a.status in ("SUCCEEDED", "FAILED"):
            return a.status if a else "GONE"
        a.status, a.started_at = "RUNNING", datetime.now(UTC)
        doc = await documents.get_document(db, a.document_id)
        pages = a.pages
        if doc is None or doc.status != DocumentStatus.CLEAN:
            data = None
        else:
            try:
                data = await documents.load_clean(db, doc)
            except (documents.NotReadable, StorageError, ValueError) as e:
                log.error("audit %s could not read its document: %s", audit_id, e)
                data = b""
    if data is None:
        return await _fail(
            org_id,
            audit_id,
            "document_gone",
            "The file was deleted before it could be checked.",
            charge=False,
        )
    if data == b"":
        return await _fail(org_id, audit_id, "system_fault", SYSTEM_FAULT, charge=False)
    try:
        result = await asyncio.to_thread(audit_pdf, data, page_count=pages)
    except AuditError as e:
        return await _fail(
            org_id,
            audit_id,
            e.code,
            e.message if e.customer_fault else SYSTEM_FAULT,
            charge=e.customer_fault,
        )
    except Exception:  # noqa: BLE001
        log.exception("audit %s crashed", audit_id)
        return await _fail(org_id, audit_id, "system_fault", SYSTEM_FAULT, charge=False)
    async with tenant_session(org_id) as db:
        a = await db.get(DocumentAudit, audit_id)
        if a.status in ("SUCCEEDED", "FAILED"):
            return a.status
        for i, f in enumerate(result.findings):
            db.add(
                DocumentFinding(
                    organization_id=org_id,
                    audit_id=audit_id,
                    ordinal=i,
                    rule_id=f["rule_id"],
                    source=f["source"],
                    severity=f["severity"],
                    title=f["title"],
                    explanation=f["explanation"],
                    how_to_fix=f["how_to_fix"],
                    wcag=f["wcag"],
                    needs_human=f["needs_human"],
                    count=f["count"],
                    pages=f["pages"],
                    pages_total=f["pages_total"],
                    examples=f["examples"],
                    explained=f.get("explained", True),
                )
            )
        a.status, a.summary, a.tool_version = "SUCCEEDED", result.summary, result.tool_version[:40]
        a.finished_at = datetime.now(UTC)
        await da.settle(db, audit_id, charge=True)
    return "SUCCEEDED"


@celery_app.task(name="docs.audit_pdf")
def audit_pdf_task(org_id: str, audit_id: str) -> str:
    async def run() -> str:
        try:
            return await run_audit(uuid.UUID(org_id), uuid.UUID(audit_id))
        finally:
            await dispose_engines()

    return asyncio.run(run())
