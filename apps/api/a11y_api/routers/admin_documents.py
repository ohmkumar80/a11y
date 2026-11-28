"""Super Admin: the Documents module (Phase 3, ADR 0020).

Shows whether the virus scanner and file store are reachable, what is in the pipeline, why files are being refused,
and which files failed on OUR side, and lets an administrator retry those or run the retention sweep now. Limits,
file types, retention and the safety policy are not edited here: they are ordinary settings (documents.uploads,
documents.safety, documents.retention) with the same versioning, scopes and audit as every other setting.
Every cross-tenant read is audit-logged. File CONTENT is never exposed here, only metadata."""

import asyncio
import uuid

from a11y_core import clamav, documents
from a11y_core.db import admin_session, tenant_session
from a11y_core.models import DocumentStatus
from a11y_core.settings import get_settings
from a11y_core.storage import StorageError, regions, store_for
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from ..deps import require_super_admin
from ..security import Principal

router = APIRouter(prefix="/admin/documents", tags=["admin"])


async def _health() -> dict[str, str]:
    s = get_settings()
    out = {}
    out["scanner"] = (
        "ok" if await clamav.ping(host=s.clamd_host, port=s.clamd_port, timeout=3) else "down"
    )
    regs, _ = await regions()
    out["regions"] = {}
    for r in regs.values():
        if not r.is_active:
            continue
        try:
            await asyncio.wait_for((await store_for(r.id)).exists("healthcheck/none"), 5)
            out["regions"][r.id] = "ok"
        except (StorageError, TimeoutError):
            out["regions"][r.id] = "down"
    out["storage"] = "ok" if all(v == "ok" for v in out["regions"].values()) else "down"
    return out


@router.get("/overview")
async def overview(p: Principal = Depends(require_super_admin)):
    health = await _health()
    known = set((await regions())[0])
    async with admin_session(
        actor_user_id=p.user_id, reason="documents overview", action="admin.read"
    ) as db:
        by_status = {
            r.status: r.n
            for r in (
                await db.execute(
                    text("SELECT status, count(*) AS n FROM documents GROUP BY status")
                )
            ).all()
        }
        rejections = [
            {"code": r.reject_code, "count": r.n}
            for r in (
                await db.execute(
                    text(
                        "SELECT reject_code, count(*) AS n FROM documents WHERE status IN ('REJECTED', 'FAILED') "
                        "AND created_at > now() - interval '30 days' GROUP BY reject_code ORDER BY n DESC"
                    )
                )
            ).all()
        ]
        region_rows = (
            await db.execute(
                text(
                    "SELECT region, count(*) AS n FROM documents WHERE storage_key IS NOT NULL GROUP BY region ORDER BY region"
                )
            )
        ).all()
        stored = (
            await db.execute(
                text(
                    "SELECT coalesce(sum(size_bytes), 0) FROM documents WHERE storage_key IS NOT NULL"
                )
            )
        ).scalar_one()
        due = (
            await db.execute(
                text(
                    "SELECT count(*) FROM documents WHERE status <> 'DELETED' AND expires_at < now()"
                )
            )
        ).scalar_one()
        stuck = (
            await db.execute(
                text(
                    "SELECT count(*) FROM documents WHERE status IN ('UPLOADED', 'SCANNING') "
                    "AND created_at < now() - interval '15 minutes'"
                )
            )
        ).scalar_one()
        failed = [
            {
                "id": str(r.id),
                "organization": r.name,
                "kind": r.kind,
                "size_bytes": r.size_bytes,
                "created_at": r.created_at,
                "attempts": r.attempts,
                "why": (r.inspection or {}).get("system_fault"),
            }
            for r in (
                await db.execute(
                    text(
                        "SELECT d.id, o.name, d.kind, d.size_bytes, d.created_at, d.attempts, d.inspection "
                        "FROM documents d JOIN organizations o ON o.id = d.organization_id "
                        "WHERE d.status = 'FAILED' ORDER BY d.created_at DESC LIMIT 50"
                    )
                )
            ).all()
        ]
    by_region = [
        {"region": r.region, "files": r.n, "configured": r.region in known} for r in region_rows
    ]
    return {
        "by_region": by_region,
        "health": health,
        "by_status": {s.value: by_status.get(s.value, 0) for s in DocumentStatus},
        "rejections_30d": rejections,
        "stored_bytes": int(stored),
        "expired_waiting": due,
        "stuck": stuck,
        "failed": failed,
    }


@router.post("/{doc_id}/rescan")
async def rescan(doc_id: uuid.UUID, p: Principal = Depends(require_super_admin)):
    """Give a file that FAILED on our side another full check (after the scanner or store is fixed). It still has to
    pass every check before anyone can read it."""
    async with admin_session(
        actor_user_id=p.user_id, reason="re-scan document", action="admin.document_rescan"
    ) as db:
        r = (
            await db.execute(
                text("SELECT organization_id, status FROM documents WHERE id = :i"), {"i": doc_id}
            )
        ).first()
    if r is None or r.status != DocumentStatus.FAILED:
        raise HTTPException(404, detail={"detail": "There is no failed document with that id."})
    async with tenant_session(r.organization_id) as db:
        d = await documents.get_document(db, doc_id)
        d.status, d.attempts = DocumentStatus.UPLOADED, 0
        d.reject_code = d.reject_detail = None
        d.inspection = {}
    queued = documents.enqueue_scan(r.organization_id, doc_id)
    return {"status": "UPLOADED", "queued": queued}


@router.post("/purge")
async def purge(p: Principal = Depends(require_super_admin)):
    """Run the retention sweep now (it also runs every hour)."""
    async with admin_session(
        actor_user_id=p.user_id, reason="manual retention sweep", action="admin.document_purge"
    ) as db:
        await db.execute(text("SELECT 1"))
    return await documents.purge_expired()
