"""Customer documents: accept an upload safely, hold it until it is scanned, erase it on schedule (ADR 0020).

The one rule everything here serves: **no code may read a customer file's bytes unless the document is CLEAN.**
`load_clean` is the only reader for normal use; the scan task uses `load_for_scan`, which is the only other one.

Life of a file: accept_upload -> UPLOADED -> (worker) SCANNING -> CLEAN, or REJECTED (the customer's file), or
FAILED (our fault: scanner or store down). Any status can become DELETED (retention sweep, or the customer asks)."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from . import billing
from .celery_app import celery_app
from .config import get_config
from .config.definitions import DocumentUploads
from .db import admin_session, dispose_engines, tenant_session
from .models import Document, DocumentStatus
from .storage import StorageError, get_store, object_key, open_bytes, seal_bytes
from .upload_checks import (
    Refusal,
    ZipLimits,
    check_size,
    detect_kind,
    kind_from_name,
    sanitize_filename,
)

log = logging.getLogger(__name__)
STALE_AFTER = timedelta(minutes=5)


class UploadRefused(Exception):
    """The upload was not accepted. `http_status` and `code` are for the API; `message` is for the person."""

    def __init__(self, http_status: int, code: str, message: str, **extra) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.message = message
        self.extra = extra


class NotReadable(Exception):
    """The document is not CLEAN (or its bytes are gone), so its content may not be read."""


async def _limits(org_id: uuid.UUID, plan_id: str) -> tuple[DocumentUploads, ZipLimits, object]:
    cfg = get_config()
    up = (await cfg.effective("documents.uploads", org_id=org_id, plan_id=plan_id)).value
    sf = (await cfg.effective("documents.safety")).value
    ret = (await cfg.effective("documents.retention", org_id=org_id, plan_id=plan_id)).value
    zl = ZipLimits(sf.zip_max_entries, sf.zip_max_uncompressed_mb * 1024 * 1024, sf.zip_max_ratio)
    return up, zl, ret


async def upload_policy(org_id: uuid.UUID) -> DocumentUploads:
    """The upload limits that apply to this organisation right now (plan and organisation overrides included)."""
    async with tenant_session(org_id) as db:
        plan_id = (await billing.load_subscription(db)).plan_id
    return (await get_config().effective("documents.uploads", org_id=org_id, plan_id=plan_id)).value


async def retention_days(org_id: uuid.UUID) -> int:
    """How long this organisation's new files are kept, for telling people up front."""
    async with tenant_session(org_id) as db:
        plan_id = (await billing.load_subscription(db)).plan_id
    ret = (await get_config().effective("documents.retention", org_id=org_id, plan_id=plan_id)).value
    return ret.retention_days


async def accept_upload(
    org_id: uuid.UUID, user_id: uuid.UUID | None, filename: str, data: bytes
) -> Document:
    """Validate, encrypt, store and enqueue. Raises UploadRefused (customer's problem) or StorageError (ours)."""
    async with tenant_session(org_id) as db:
        sub = await billing.load_subscription(db)
        await billing.require_writable(db)
        plan_id = sub.plan_id
    up, zl, ret = await _limits(org_id, plan_id)
    if not up.enabled:
        raise UploadRefused(
            403, "uploads_disabled", "Document uploads are switched off at the moment."
        )

    name = sanitize_filename(filename)
    claimed = kind_from_name(name)
    if claimed is None or claimed not in up.kinds():
        allowed = ", ".join(k.upper() for k in up.kinds()) or "none"
        raise UploadRefused(
            415,
            "unsupported_type",
            f"That file type is not accepted for your account. Accepted types: {allowed}.",
        )
    try:
        check_size(claimed, len(data), up.max_bytes(claimed))
        kind = detect_kind(data, name, zl)
    except Refusal as r:
        code = 413 if r.code == "too_large" else 422
        raise UploadRefused(code, r.code, r.message) from None

    doc_id = uuid.uuid4()
    key = object_key(org_id, doc_id)
    blob, wrapped = seal_bytes(data, key)
    store = get_store()
    stored = False
    try:
        async with tenant_session(org_id) as db:
            # Serialise per organisation so the rate and count limits cannot be raced past.
            await billing.require_writable(db, lock=True)
            last_hour = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM documents WHERE created_at > now() - interval '1 hour'"
                    )
                )
            ).scalar_one()
            if last_hour >= up.max_files_per_hour:
                raise UploadRefused(
                    429,
                    "rate_limited",
                    "You are uploading too quickly. Wait a few minutes and try again.",
                    retry_after=300,
                )
            active = (
                await db.execute(text("SELECT count(*) FROM documents WHERE status <> 'DELETED'"))
            ).scalar_one()
            if active >= up.max_active_files:
                raise UploadRefused(
                    409,
                    "too_many_files",
                    "You are storing the most files your plan allows. Delete some and try again.",
                )
            doc = Document(
                id=doc_id,
                organization_id=org_id,
                filename=name,
                kind=kind,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                storage_key=key,
                wrapped_key=wrapped,
                status=DocumentStatus.UPLOADED,
                created_by=user_id,
                expires_at=datetime.now(UTC) + timedelta(days=ret.retention_days),
            )
            db.add(doc)
            await db.flush()
            await store.put(
                key, blob
            )  # inside the transaction: if the store fails, no row is committed
            stored = True
    except BaseException:
        if stored:  # the commit itself failed: do not leave an orphaned object behind
            try:
                await store.delete(key)
            except StorageError:
                log.exception("could not remove orphaned object %s", key)
        raise
    enqueue_scan(org_id, doc_id)
    return doc


def enqueue_scan(org_id: uuid.UUID, doc_id: uuid.UUID) -> bool:
    """False when the broker is down; the sweeper re-enqueues anything left UPLOADED."""
    try:
        celery_app.send_task("docs.scan_upload", args=[str(org_id), str(doc_id)], queue="docs")
        return True
    except Exception:  # noqa: BLE001
        log.warning("could not enqueue scan for document %s; the sweeper will retry", doc_id)
        return False


async def _read(db: AsyncSession, doc: Document) -> bytes:
    if not doc.storage_key or not doc.wrapped_key:
        raise NotReadable("the file's bytes are gone")
    blob = await get_store().get(doc.storage_key)
    data = open_bytes(blob, doc.wrapped_key, doc.storage_key)
    if hashlib.sha256(data).hexdigest() != doc.sha256:
        raise NotReadable("the stored file does not match its checksum")
    return data


async def load_clean(db: AsyncSession, doc: Document) -> bytes:
    """Plain bytes of a document, only if it passed every check."""
    if doc.status != DocumentStatus.CLEAN:
        raise NotReadable(f"document is {doc.status}, not CLEAN")
    return await _read(db, doc)


async def load_for_scan(db: AsyncSession, doc: Document) -> bytes:
    """For the scan task ONLY: the one place that may read a file that has not been cleared yet."""
    if doc.status not in (DocumentStatus.UPLOADED, DocumentStatus.SCANNING):
        raise NotReadable(f"document is {doc.status}, not waiting for a scan")
    return await _read(db, doc)


async def scrub_bytes(doc: Document) -> None:
    """Delete the stored bytes but keep the row's status, so a customer can still see WHY a file was refused."""
    if doc.storage_key:
        await get_store().delete(doc.storage_key)
    doc.storage_key = None
    doc.wrapped_key = None


async def erase(db: AsyncSession, doc: Document, reason: str) -> None:
    """Delete the bytes, then blank the row to a tombstone. Idempotent. `reason`: retention | customer | rejected."""
    if doc.storage_key:
        await get_store().delete(doc.storage_key)
    doc.storage_key = None
    doc.wrapped_key = None
    doc.filename = "deleted"
    doc.status = DocumentStatus.DELETED
    doc.deleted_at = datetime.now(UTC)
    doc.deleted_reason = reason
    await db.flush()


async def get_document(db: AsyncSession, doc_id: uuid.UUID) -> Document | None:
    return (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()


# --- background sweeps (beat) ---------------------------------------------------------------------------


async def purge_expired() -> dict[str, int]:
    """Erase files past their retention (and refused files past theirs). Safe to run any time, as often as you like."""
    cfg = get_config()
    batch = (await cfg.effective("documents.retention")).value.purge_batch
    async with admin_session(
        actor_user_id=None, reason="document retention sweep", action="system.purge_documents"
    ) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, organization_id, status FROM documents "
                    "WHERE status <> 'DELETED' AND expires_at < now() ORDER BY expires_at LIMIT :n"
                ),
                {"n": batch},
            )
        ).all()
    out = {"erased": 0, "errors": 0}
    for r in rows:
        try:
            async with tenant_session(r.organization_id) as db:
                doc = await get_document(db, r.id)
                if doc is not None and doc.status != DocumentStatus.DELETED:
                    await erase(
                        db, doc, "rejected" if doc.status in ("REJECTED", "FAILED") else "retention"
                    )
                    out["erased"] += 1
        except StorageError:
            out["errors"] += 1  # leave it; the next sweep tries again
            log.exception("could not erase document %s", r.id)
    return out


async def requeue_stale() -> int:
    """Re-enqueue files stuck in UPLOADED or SCANNING (broker was down, or a worker died mid-scan)."""
    async with admin_session(
        actor_user_id=None, reason="document scan sweep", action="system.requeue_documents"
    ) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, organization_id FROM documents WHERE status IN ('UPLOADED', 'SCANNING') "
                    "AND created_at < now() - CAST(:age AS interval) AND coalesce(scanned_at, created_at) < now() - CAST(:age AS interval) "
                    "LIMIT 500"
                ),
                {"age": STALE_AFTER},
            )
        ).all()
    n = sum(1 for r in rows if enqueue_scan(r.organization_id, r.id))
    return n


@celery_app.task(name="documents.purge_expired")
def purge_expired_task() -> dict[str, int]:
    import asyncio

    async def run() -> dict[str, int]:
        try:
            return await purge_expired()
        finally:
            await dispose_engines()

    return asyncio.run(run())


@celery_app.task(name="documents.requeue_stale")
def requeue_stale_task() -> int:
    import asyncio

    async def run() -> int:
        try:
            return await requeue_stale()
        finally:
            await dispose_engines()

    return asyncio.run(run())


celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    "purge-expired-documents": {"task": "documents.purge_expired", "schedule": 3600.0},
    "requeue-stale-documents": {"task": "documents.requeue_stale", "schedule": 300.0},
}
