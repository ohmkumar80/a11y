"""Customer documents: upload, list, download, delete (ADR 0020).

Upload is the raw file as the request body (`POST /documents?filename=report.pdf`), read in chunks and cut off at the
organisation's size limit, so an oversized or endless body is refused without being buffered. A file is held back
(`status` UPLOADED -> SCANNING) until the worker has virus-scanned and inspected it; only a CLEAN file can be
downloaded or used for anything."""

import uuid

from a11y_core import document_audits, document_fixes, documents
from a11y_core.db import tenant_session
from a11y_core.doc_fix import FixPlan
from a11y_core.models import (
    AuditLog,
    Document,
    DocumentAudit,
    DocumentFinding,
    DocumentFix,
    DocumentStatus,
)
from a11y_core.storage import StorageError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select

from ..deps import current_principal, ensure_flag
from ..security import Principal

router = APIRouter(prefix="/documents", tags=["documents"])
MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "epub": "application/epub+zip",
}
SYSTEM_FAULT = "We could not store your file because of a problem on our side. Nothing was charged. Please try again."


def _problem(http_status: int, detail: str, field: str | None = None, **extra) -> HTTPException:
    return HTTPException(http_status, detail={"detail": detail, "field": field, **extra})


def _audit_json(a: DocumentAudit) -> dict:
    return {
        "id": str(a.id),
        "document_id": str(a.document_id),
        "standard": a.standard,
        "status": a.status,
        "pages": a.pages,
        "summary": a.summary,
        "error_code": a.error_code,
        "error_detail": a.error_detail,
        "created_at": a.created_at,
        "finished_at": a.finished_at,
    }


def _finding_json(f: DocumentFinding) -> dict:
    return {
        "id": str(f.id),
        "rule_id": f.rule_id,
        "source": f.source,
        "severity": f.severity,
        "title": f.title,
        "explanation": f.explanation,
        "how_to_fix": f.how_to_fix,
        "wcag": f.wcag,
        "needs_human": f.needs_human,
        "count": f.count,
        "pages": f.pages,
        "pages_total": f.pages_total,
        "examples": f.examples,
        "explained": f.explained,
    }


async def _latest_audits(db, doc_ids: list[uuid.UUID]) -> dict[uuid.UUID, DocumentAudit]:
    if not doc_ids:
        return {}
    rows = (
        await db.execute(
            select(DocumentAudit)
            .where(DocumentAudit.document_id.in_(doc_ids))
            .order_by(DocumentAudit.created_at.desc())
        )
    ).scalars()
    latest: dict[uuid.UUID, DocumentAudit] = {}
    for a in rows:  # newest first: the first one seen for a document is its latest
        latest.setdefault(a.document_id, a)
    return latest


def _json(d: Document, audit: DocumentAudit | None = None) -> dict:
    return {
        "latest_audit": _audit_json(audit) if audit else None,
        "id": str(d.id),
        "filename": d.filename,
        "kind": d.kind,
        "size_bytes": d.size_bytes,
        "status": d.status,
        "reject_code": d.reject_code,
        "reject_detail": d.reject_detail,
        "page_count": d.page_count,
        "created_at": d.created_at,
        "scanned_at": d.scanned_at,
        "expires_at": d.expires_at,
        "ready": d.status == DocumentStatus.CLEAN,
        "derived_from": str(d.derived_from) if d.derived_from else None,
    }


@router.get("/policy")
async def policy(p: Principal = Depends(current_principal)):
    """What this organisation may upload: used by the upload form to explain the limits before anything is sent."""
    await ensure_flag("documents", p)
    up = await documents.upload_policy(p.org_id)
    return {
        "enabled": up.enabled,
        "kinds": [{"kind": k, "max_mb": getattr(up, f"max_mb_{k}")} for k in up.kinds()],
        "max_pages": up.max_pages,
        "retention_days": await documents.retention_days(p.org_id),
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload(request: Request, filename: str, p: Principal = Depends(current_principal)):
    await ensure_flag("documents", p)
    up = await documents.upload_policy(p.org_id)
    if not up.enabled:
        raise _problem(
            403, "Document uploads are switched off at the moment.", code="uploads_disabled"
        )
    cap = max((up.max_bytes(k) for k in up.kinds()), default=0)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > cap:
        raise _problem(
            413, f"That file is larger than the {cap // 1048576} MB limit.", code="too_large"
        )
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > cap:
            raise _problem(
                413, f"That file is larger than the {cap // 1048576} MB limit.", code="too_large"
            )
    try:
        doc = await documents.accept_upload(p.org_id, p.user_id, filename, bytes(buf))
    except documents.UploadRefused as r:
        headers = {"Retry-After": str(r.extra["retry_after"])} if "retry_after" in r.extra else None
        raise HTTPException(
            r.http_status,
            detail={"detail": r.message, "code": r.code, "field": "file"},
            headers=headers,
        ) from None
    except StorageError:
        raise _problem(503, SYSTEM_FAULT, code="storage_unavailable") from None
    return _json(doc)


@router.get("")
async def list_documents(limit: int = 50, p: Principal = Depends(current_principal)):
    await ensure_flag("documents", p)
    async with tenant_session(p.org_id) as db:
        rows = (
            await db.execute(
                select(Document)
                .where(Document.status != DocumentStatus.DELETED)
                .order_by(Document.created_at.desc())
                .limit(max(1, min(limit, 200)))
            )
        ).scalars()
        docs = list(rows)
        latest = await _latest_audits(db, [d.id for d in docs])
        return [_json(d, latest.get(d.id)) for d in docs]


async def _get(db, doc_id: uuid.UUID) -> Document:
    d = await documents.get_document(db, doc_id)
    if d is None or d.status == DocumentStatus.DELETED:
        raise _problem(404, "We could not find that document.")
    return d


@router.get("/{doc_id}")
async def get_one(doc_id: uuid.UUID, p: Principal = Depends(current_principal)):
    await ensure_flag("documents", p)
    async with tenant_session(p.org_id) as db:
        d = await _get(db, doc_id)
        return _json(d, (await _latest_audits(db, [d.id])).get(d.id))


@router.get("/{doc_id}/download")
async def download(doc_id: uuid.UUID, p: Principal = Depends(current_principal)):
    await ensure_flag("documents", p)
    async with tenant_session(p.org_id) as db:
        d = await _get(db, doc_id)
        if d.status != DocumentStatus.CLEAN:
            raise _problem(
                409,
                "This file has not passed our safety checks, so it cannot be downloaded.",
                code="not_ready",
            )
        try:
            data = await documents.load_clean(db, d)
        except (documents.NotReadable, StorageError, ValueError):
            raise _problem(503, SYSTEM_FAULT, code="storage_unavailable") from None
        name, kind = d.filename, d.kind
    safe = name.replace('"', "")
    return Response(
        data,
        media_type=MIME[kind],
        headers={
            "Content-Disposition": f'attachment; filename="{safe}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(doc_id: uuid.UUID, p: Principal = Depends(current_principal)):
    """Erase the file now (the customer's right to deletion). Members may delete their own uploads; administrators any."""
    await ensure_flag("documents", p)
    async with tenant_session(p.org_id) as db:
        d = await _get(db, doc_id)
        if p.role != "COMPANY_ADMIN" and d.created_by != p.user_id:
            raise _problem(
                403, "Only an administrator or the person who uploaded this file can delete it."
            )
        try:
            await documents.erase(db, d, "customer")
        except StorageError:
            raise _problem(503, SYSTEM_FAULT, code="storage_unavailable") from None
        db.add(
            AuditLog(
                organization_id=p.org_id,
                actor_user_id=p.user_id,
                action="document.deleted",
                detail={"document_id": str(doc_id)},
            )
        )
    return Response(status_code=204)


# --- accessibility audits ----------------------------------------------------------------------------


@router.post("/{doc_id}/audits", status_code=status.HTTP_202_ACCEPTED)
async def start_audit(doc_id: uuid.UUID, p: Principal = Depends(current_principal)):
    """Check a PDF against PDF/UA. Reserves the document's pages from the plan quota (a quota or locked-plan problem
    is reported with an upgrade link); the pages are given back if the failure was ours."""
    await ensure_flag("documents", p)
    try:
        a = await document_audits.start_audit(p.org_id, p.user_id, doc_id)
    except document_audits.AuditRefused as r:
        raise HTTPException(r.http_status, detail={"detail": r.message, "code": r.code}) from None
    return _audit_json(a)


@router.get("/{doc_id}/audits")
async def list_audits(doc_id: uuid.UUID, p: Principal = Depends(current_principal)):
    await ensure_flag("documents", p)
    async with tenant_session(p.org_id) as db:
        await _get(db, doc_id)
        rows = (
            await db.execute(
                select(DocumentAudit)
                .where(DocumentAudit.document_id == doc_id)
                .order_by(DocumentAudit.created_at.desc())
                .limit(50)
            )
        ).scalars()
        return [_audit_json(a) for a in rows]


@router.get("/{doc_id}/audits/{audit_id}")
async def get_audit(
    doc_id: uuid.UUID, audit_id: uuid.UUID, p: Principal = Depends(current_principal)
):
    await ensure_flag("documents", p)
    async with tenant_session(p.org_id) as db:
        d = await _get(db, doc_id)
        a = (
            await db.execute(
                select(DocumentAudit).where(
                    DocumentAudit.id == audit_id, DocumentAudit.document_id == doc_id
                )
            )
        ).scalar_one_or_none()
        if a is None:
            raise _problem(404, "We could not find that check.")
        findings = (
            await db.execute(
                select(DocumentFinding)
                .where(DocumentFinding.audit_id == audit_id)
                .order_by(DocumentFinding.ordinal)
            )
        ).scalars()
        return {
            **_audit_json(a),
            "document": {
                "id": str(d.id),
                "filename": d.filename,
                "kind": d.kind,
                "page_count": d.page_count,
            },
            "findings": [_finding_json(f) for f in findings],
        }


# --- guided fix ----------------------------------------------------------------------------------------


def _fix_json(f: DocumentFix | None) -> dict | None:
    if f is None:
        return None
    return {
        "id": str(f.id),
        "status": f.status,
        "plan": f.plan,
        "pages": f.pages,
        "result": f.result,
        "result_document_id": str(f.result_document_id) if f.result_document_id else None,
        "error_code": f.error_code,
        "error_detail": f.error_detail,
        "created_at": f.created_at,
        "finished_at": f.finished_at,
    }


def _refuse(r: document_fixes.FixRefused) -> HTTPException:
    return HTTPException(r.http_status, detail={"detail": r.message, "code": r.code})


@router.get("/{doc_id}/fix")
async def get_fix(doc_id: uuid.UUID, p: Principal = Depends(current_principal)):
    """What the fix editor needs: the figures and headings that can be changed, the plan in progress, and the latest build."""
    await ensure_flag("documents", p)
    try:
        s = await document_fixes.get_state(p.org_id, doc_id)
    except document_fixes.FixRefused as r:
        raise _refuse(r) from None
    doc, audit, fix = s["document"], s["audit"], s["fix"]
    return {
        "document": {"id": str(doc.id), "filename": doc.filename, "page_count": doc.page_count},
        "audit_id": str(audit.id),
        "structure": audit.structure,
        "fix": _fix_json(fix),
    }


@router.put("/{doc_id}/fix")
async def save_fix(doc_id: uuid.UUID, plan: FixPlan, p: Principal = Depends(current_principal)):
    """Save the plan being edited. Nothing is changed in the file and nothing is charged until you build."""
    await ensure_flag("documents", p)
    try:
        return _fix_json(await document_fixes.save_plan(p.org_id, p.user_id, doc_id, plan))
    except document_fixes.FixRefused as r:
        raise _refuse(r) from None


@router.post("/{doc_id}/fix/build", status_code=status.HTTP_202_ACCEPTED)
async def build_fix(doc_id: uuid.UUID, p: Principal = Depends(current_principal)):
    """Build a fixed COPY and check it again. Uses the document's pages from the plan allowance (given back if we fail)."""
    await ensure_flag("documents", p)
    try:
        return _fix_json(await document_fixes.start_build(p.org_id, doc_id))
    except document_fixes.FixRefused as r:
        raise _refuse(r) from None
