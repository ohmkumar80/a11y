"""The ``docs.build_fix`` task: apply a person's plan to a copy of their PDF, re-check the copy, and store it (ADR 0022).

The gate (PROJECT_PLAN 2.5, "never deliver an unvalidated file"): the copy is produced only if it opens, has the same number
of pages, and the re-check shows no NEW critical or serious problem. A copy that still has problems is delivered, labelled
with exactly what was fixed and what remains: the point is "better, and honest about it", not a claim of conformance.
Pages are settled once: charged when a copy was produced, given back otherwise."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

from a11y_core import document_audits as da
from a11y_core import documents
from a11y_core.celery_app import celery_app
from a11y_core.db import dispose_engines, tenant_session
from a11y_core.doc_fix import FixPlan
from a11y_core.models import Document, DocumentAudit, DocumentFinding, DocumentFix, DocumentStatus
from a11y_core.storage import StorageError, object_key, seal_bytes, store_for
from a11y_core.upload_checks import sanitize_filename
from sqlalchemy import select

from .audit_task import _structure, write_result
from .pdf_audit import AuditError, audit_pdf
from .pdf_fix import FixError, apply_plan

log = logging.getLogger(__name__)
SYSTEM_FAULT = "We could not finish this because of a problem on our side. Your pages were not used. Please try again later."
SERIOUS = ("critical", "serious")


def fixed_name(name: str) -> str:
    stem = re.sub(r"\.pdf$", "", name, flags=re.I)
    return sanitize_filename(f"{stem} (fixed).pdf")


def _brief(findings) -> list[dict]:
    return [
        {"rule_id": f["rule_id"], "title": f["title"], "severity": f["severity"]} for f in findings
    ]


async def _fail(org_id, fix_id, code: str, detail: str) -> str:
    async with tenant_session(org_id) as db:
        f = await db.get(DocumentFix, fix_id)
        if f is None or f.status in ("READY", "FAILED"):
            return f.status if f else "GONE"
        f.status, f.error_code, f.error_detail = "FAILED", code, detail
        f.finished_at = f.updated_at = datetime.now(UTC)
        await da.settle(db, fix_id, charge=False)
    return "FAILED"


async def run_fix(org_id: uuid.UUID, fix_id: uuid.UUID) -> str:
    async with tenant_session(org_id) as db:
        f = await db.get(DocumentFix, fix_id)
        if f is None or f.status in ("READY", "FAILED"):
            return f.status if f else "GONE"
        f.status, f.started_at = "RUNNING", datetime.now(UTC)
        doc = await documents.get_document(db, f.document_id)
        plan_raw, pages, created_by = f.plan, f.pages or 1, f.created_by
        basis = await db.get(DocumentAudit, f.audit_id) if f.audit_id else None
        before_findings = []
        if basis is not None:
            before_findings = [
                {"rule_id": x.rule_id, "title": x.title, "severity": x.severity}
                for x in (
                    await db.execute(
                        select(DocumentFinding).where(DocumentFinding.audit_id == basis.id)
                    )
                ).scalars()
            ]
        data, source_name, source_id, source_region = None, "", None, "default"
        if doc is not None and doc.status == DocumentStatus.CLEAN:
            source_name, source_id, source_region = doc.filename, doc.id, doc.region
            try:
                data = await documents.load_clean(db, doc)
            except (documents.NotReadable, StorageError, ValueError) as e:
                log.error("fix %s could not read its document: %s", fix_id, e)
                data = b""
    if data is None:
        return await _fail(
            org_id, fix_id, "document_gone", "The file was deleted before the fix could be built."
        )
    if data == b"":
        return await _fail(org_id, fix_id, "system_fault", SYSTEM_FAULT)
    try:
        plan = FixPlan(**plan_raw)
        out = await asyncio.to_thread(apply_plan, data, plan)
        result = await asyncio.to_thread(audit_pdf, out, page_count=pages)
        structure = await asyncio.to_thread(_structure, out)
    except FixError as e:
        return await _fail(
            org_id,
            fix_id,
            e.code,
            e.message + " Open the fix page again to start from the file as it is now.",
        )
    except AuditError as e:
        return await _fail(org_id, fix_id, e.code, SYSTEM_FAULT)
    except Exception:  # noqa: BLE001
        log.exception("fix %s crashed", fix_id)
        return await _fail(org_id, fix_id, "system_fault", SYSTEM_FAULT)

    after = _brief(result.findings)
    before_ids = {x["rule_id"] for x in before_findings}
    after_ids = {x["rule_id"] for x in after}
    new = [x for x in after if x["rule_id"] not in before_ids]
    if (
        result.summary["facts"]["pages"] != pages
        and pages != 1
        or any(x["severity"] in SERIOUS for x in new)
    ):
        return await _fail(
            org_id,
            fix_id,
            "regressed",
            "We could not make these changes without making something else worse, so we did not produce a file. Your pages were not used.",
        )
    summary = {
        "edits": plan.edit_count(),
        "before": {"findings": len(before_findings), "by_severity": _count(before_findings)},
        "after": {"findings": len(after), "by_severity": _count(after)},
        "resolved": [x for x in before_findings if x["rule_id"] not in after_ids],
        "remaining": after,
    }
    new_id = uuid.uuid4()
    key = object_key(org_id, new_id)
    blob, wrapped = seal_bytes(out, key)
    retention = await documents.retention_days(org_id)
    store = await store_for(source_region)  # the copy stays in the region of the file it was made from
    try:
        await store.put(key, blob)
    except StorageError:
        return await _fail(org_id, fix_id, "system_fault", SYSTEM_FAULT)
    try:
        async with tenant_session(org_id) as db:
            f = await db.get(DocumentFix, fix_id)
            if f.status in ("READY", "FAILED"):
                await store.delete(key)
                return f.status
            now = datetime.now(UTC)
            db.add(
                Document(
                    id=new_id,
                    organization_id=org_id,
                    filename=fixed_name(source_name),
                    kind="pdf",
                    size_bytes=len(out),
                    sha256=hashlib.sha256(out).hexdigest(),
                    storage_key=key,
                    wrapped_key=wrapped,
                    status=DocumentStatus.CLEAN,
                    page_count=result.summary["facts"]["pages"],
                    inspection={
                        "derived": True,
                        "malware_scan": "not needed: made by us from a clean file",
                    },
                    created_by=created_by,
                    scanned_at=now,
                    expires_at=now + timedelta(days=retention),
                    derived_from=source_id,
                    region=source_region,
                )
            )
            await db.flush()
            audit = DocumentAudit(
                id=uuid.uuid4(),
                organization_id=org_id,
                document_id=new_id,
                pages=pages,
                created_by=created_by,
                started_at=now,
            )
            db.add(audit)
            await db.flush()
            write_result(db, org_id, audit.id, audit, result, structure)
            f.status, f.result, f.result_document_id = "READY", summary, new_id
            f.finished_at = f.updated_at = now
            await da.settle(db, fix_id, charge=True)
    except BaseException:
        try:
            await store.delete(key)
        except StorageError:
            log.exception("could not remove orphaned object %s", key)
        raise
    return "READY"


def _count(items) -> dict:
    return {
        s: sum(1 for x in items if x["severity"] == s)
        for s in ("critical", "serious", "moderate", "minor")
    }


@celery_app.task(name="docs.build_fix")
def build_fix_task(org_id: str, fix_id: str) -> str:
    async def run() -> str:
        try:
            return await run_fix(uuid.UUID(org_id), uuid.UUID(fix_id))
        finally:
            await dispose_engines()

    return asyncio.run(run())
