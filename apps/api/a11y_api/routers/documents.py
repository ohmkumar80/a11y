"""Customer documents: upload, list, download, delete (ADR 0020).

Upload is the raw file as the request body (`POST /documents?filename=report.pdf`), read in chunks and cut off at the
organisation's size limit, so an oversized or endless body is refused without being buffered. A file is held back
(`status` UPLOADED -> SCANNING) until the worker has virus-scanned and inspected it; only a CLEAN file can be
downloaded or used for anything."""

import uuid

from a11y_core import documents
from a11y_core.db import tenant_session
from a11y_core.models import AuditLog, Document, DocumentStatus
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


def _json(d: Document) -> dict:
    return {
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
        return [_json(d) for d in rows]


async def _get(db, doc_id: uuid.UUID) -> Document:
    d = await documents.get_document(db, doc_id)
    if d is None or d.status == DocumentStatus.DELETED:
        raise _problem(404, "We could not find that document.")
    return d


@router.get("/{doc_id}")
async def get_one(doc_id: uuid.UUID, p: Principal = Depends(current_principal)):
    await ensure_flag("documents", p)
    async with tenant_session(p.org_id) as db:
        return _json(await _get(db, doc_id))


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
