"""The ``docs.scan_upload`` task: hold a new upload until it has been virus-scanned and inspected (ADR 0020).

Fails CLOSED. A file becomes CLEAN only when every enabled check has positively passed. If the scanner or the store
is down the task retries with back-off, and after the configured attempts the file becomes FAILED (our fault, never
readable, never charged) - it is never waved through. Idempotent: a document that is no longer waiting is left alone,
so a redelivered task cannot change an outcome."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from a11y_core import documents
from a11y_core.celery_app import celery_app
from a11y_core.clamav import ScannerUnavailable, scan_bytes
from a11y_core.config import get_config
from a11y_core.db import dispose_engines, tenant_session
from a11y_core.models import DocumentStatus
from a11y_core.settings import get_settings
from a11y_core.storage import ObjectNotFound, StorageError
from a11y_core.upload_checks import Refusal
from sqlalchemy import text

from .inspect import DANGEROUS, inspect_document

log = logging.getLogger(__name__)
SYSTEM_FAULT = "We could not finish checking this file because of a problem on our side. Nothing was charged. Please try again later."


class Retry(Exception):  # noqa: N818
    def __init__(self, countdown: int) -> None:
        self.countdown = countdown


async def scan_document(org_id: uuid.UUID, doc_id: uuid.UUID) -> str:
    """Returns the resulting status (or 'RETRY'). Raises Retry for the Celery wrapper."""
    cfg = get_config()
    async with tenant_session(org_id) as db:
        sub_plan = (
            await db.execute(text("SELECT plan_id FROM subscriptions"))
        ).scalar_one_or_none()
        doc = await documents.get_document(db, doc_id)
        if doc is None or doc.status not in (DocumentStatus.UPLOADED, DocumentStatus.SCANNING):
            return doc.status if doc else "GONE"
        doc.status = DocumentStatus.SCANNING
        doc.attempts += 1
        attempts, kind = doc.attempts, doc.kind
    safety = (await cfg.effective("documents.safety")).value
    up = (await cfg.effective("documents.uploads", org_id=org_id, plan_id=sub_plan)).value
    ret = (await cfg.effective("documents.retention", org_id=org_id, plan_id=sub_plan)).value

    async def fail_ours(why: str) -> str:
        async with tenant_session(org_id) as db:
            d = await documents.get_document(db, doc_id)
            d.status, d.reject_code, d.reject_detail = (
                DocumentStatus.FAILED,
                "system_fault",
                SYSTEM_FAULT,
            )
            d.inspection = {"system_fault": why}
            d.expires_at = datetime.now(UTC) + timedelta(days=ret.rejected_retention_days)
        log.error("document %s could not be scanned: %s", doc_id, why)
        return DocumentStatus.FAILED

    try:
        async with tenant_session(org_id) as db:
            d = await documents.get_document(db, doc_id)
            data = await documents.load_for_scan(db, d)
    except ObjectNotFound:
        return await fail_ours("stored object missing")
    except StorageError:
        if attempts >= safety.max_attempts:
            return await fail_ours("object store unavailable")
        raise Retry(30 * attempts) from None
    except (documents.NotReadable, ValueError) as e:
        return await fail_ours(f"stored file unreadable: {e}")

    signature = None
    try:
        if safety.malware_scan == "required":
            s = get_settings()
            verdict = await scan_bytes(
                data, host=s.clamd_host, port=s.clamd_port, timeout=safety.scan_timeout_seconds
            )
            if not verdict.clean:
                signature = verdict.signature
                raise Refusal(
                    "malware", "That file contains a virus or other harmful code, so we deleted it."
                )
        found = await asyncio.to_thread(
            inspect_document,
            data,
            kind,
            max_pages=up.max_pages,
            reject_encrypted=safety.reject_encrypted,
            reject_active=safety.reject_active_content,
        )
    except ScannerUnavailable as e:
        if attempts >= safety.max_attempts:
            return await fail_ours(f"virus scanner unavailable: {e}")
        raise Retry(30 * attempts) from None
    except Refusal as r:
        async with tenant_session(org_id) as db:
            d = await documents.get_document(db, doc_id)
            d.status, d.reject_code, d.reject_detail = DocumentStatus.REJECTED, r.code, r.message
            d.scanned_at = datetime.now(UTC)
            d.expires_at = datetime.now(UTC) + timedelta(days=ret.rejected_retention_days)
            if signature:
                d.inspection = {"signature": signature}
            if r.code in DANGEROUS:
                await documents.scrub_bytes(d)
        return DocumentStatus.REJECTED

    async with tenant_session(org_id) as db:
        d = await documents.get_document(db, doc_id)
        d.status, d.scanned_at = DocumentStatus.CLEAN, datetime.now(UTC)
        d.page_count = found.page_count
        d.inspection = {**found.facts, "malware_scan": safety.malware_scan}
    return DocumentStatus.CLEAN


@celery_app.task(name="docs.scan_upload", bind=True, max_retries=None)
def scan_upload_task(self, org_id: str, doc_id: str) -> str:
    async def run() -> str:
        try:
            return await scan_document(uuid.UUID(org_id), uuid.UUID(doc_id))
        finally:
            await dispose_engines()

    try:
        return asyncio.run(run())
    except Retry as r:
        raise self.retry(countdown=r.countdown) from None
