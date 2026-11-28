"""Human review of a PDF (ADR 0023): a customer asks a person to check it, a platform reviewer claims it, fixes it with the
same tools the customer has, and either delivers a fixed copy or explains why they could not.

The privacy rules that shape everything here:
* A reviewer can open a document only while a review of it is IN_REVIEW and claimed by them. The request is the customer's
  consent; nothing else gives a reviewer access.
* Before a file is claimed the queue shows sizes and counts only: no name, no note, no content.
* A reviewer has no organisation. They get at a customer's data only through an ordinary tenant session for that one
  organisation, opened after the claim is checked, and every open, download and edit leaves a row in the customer's audit log.
* One credit (`document_reviews_monthly`) is reserved at request time: charged when a review is delivered, given back when it
  is declined or cancelled."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from . import billing, data_policy, document_fixes, documents
from .celery_app import celery_app
from .config import get_config
from .db import admin_session, dispose_engines, reviewer_session, tenant_session
from .doc_fix import FixPlan
from .models import (
    AuditLog,
    DocumentFinding,
    DocumentFix,
    DocumentReview,
    DocumentStatus,
)

log = logging.getLogger(__name__)
FEATURE = "document_reviews_monthly"
CONSENT_VERSION = "2026-11-28"
CONSENT_TEXT = (
    "I ask a person on the a11y review team to open this file, see its contents, and try to fix its accessibility problems. "
    "Only a reviewer who has taken this file can open it, every time they do is recorded in your organisation's audit log, "
    "and the original is never changed: any fixes are made to a copy."
)
MAX_CLAIMS = 5
MAX_NOTE = 1000
MAX_MESSAGE = 2000


class ReviewRefused(Exception):
    def __init__(self, http_status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.http_status, self.code, self.message = http_status, code, message


def _from_fix(r: document_fixes.FixRefused) -> ReviewRefused:
    return ReviewRefused(r.http_status, r.code, r.message)


async def _policy(org_id: uuid.UUID, plan_id: str):
    return (await get_config().effective("documents.review", org_id=org_id, plan_id=plan_id)).value


def _audit(org_id, actor, action, **detail) -> AuditLog:
    return AuditLog(organization_id=org_id, actor_user_id=actor, action=action, detail=detail)


# --- the customer's side -----------------------------------------------------------------------------


async def request_review(
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    doc_id: uuid.UUID,
    note: str | None,
    consent: bool,
) -> DocumentReview:
    if not consent:
        raise ReviewRefused(
            422, "consent_required", "Please confirm that you agree to a person opening this file."
        )
    note = " ".join((note or "").split())[:MAX_NOTE] or None
    async with tenant_session(org_id) as db:
        plan_id = (await billing.load_subscription(db)).plan_id
    pol = await _policy(org_id, plan_id)
    if not (await data_policy.effective(org_id, plan_id)).allow_human_review:
        raise ReviewRefused(
            403,
            "review_blocked_by_policy",
            "Your organisation's data policy does not let people on our team open its files. An administrator can change this on the data policy page.",
        )
    if not pol.enabled:
        raise ReviewRefused(
            403,
            "reviews_disabled",
            "Asking a person to check a document is switched off at the moment.",
        )
    async with tenant_session(org_id) as db:
        try:
            doc, audit = await document_fixes._editable(db, doc_id)
        except document_fixes.FixRefused as r:
            raise _from_fix(r) from None
        open_here = (
            await db.execute(
                text(
                    "SELECT count(*) FILTER (WHERE document_id = :d), count(*) FROM document_reviews WHERE status IN ('REQUESTED', 'IN_REVIEW')"
                ),
                {"d": doc_id},
            )
        ).one()
        if open_here[0]:
            raise ReviewRefused(409, "review_open", "A person is already checking this document.")
        if open_here[1] >= pol.max_open_per_org:
            raise ReviewRefused(
                409,
                "too_many_reviews",
                "You already have the most reviews waiting that your plan allows. Wait for one to finish.",
            )
        facts = (audit.summary or {}).get("facts", {})
        snap = {
            "findings": (audit.summary or {}).get("findings", 0),
            "by_severity": (audit.summary or {}).get("by_severity", {}),
            "tagged": facts.get("tagged"),
            "figures": len(audit.structure.get("figures", [])),
            "headings": len(audit.structure.get("headings", [])),
            "image_only_pages": facts.get("image_only_pages", 0),
            "has_note": bool(note),
        }
        now = datetime.now(UTC)
        review = DocumentReview(
            id=uuid.uuid4(),
            organization_id=org_id,
            document_id=doc_id,
            requested_by=user_id,
            consent_version=CONSENT_VERSION,
            note=note,
            requested_at=now,
            due_at=now + timedelta(hours=pol.sla_hours),
            pages=max(1, doc.page_count or 1),
            snapshot=snap,
        )
        db.add(review)
        await db.flush()
        await billing.reserve(db, org_id, FEATURE, str(review.id), 1)  # raises QuotaExceeded
        db.add(
            _audit(
                org_id,
                user_id,
                "review.requested",
                review_id=str(review.id),
                document_id=str(doc_id),
                consent=CONSENT_VERSION,
            )
        )
        return review


async def cancel_review(
    org_id: uuid.UUID, user_id: uuid.UUID, doc_id: uuid.UUID, review_id: uuid.UUID
) -> None:
    async with tenant_session(org_id) as db:
        r = (
            await db.execute(
                select(DocumentReview)
                .where(DocumentReview.id == review_id, DocumentReview.document_id == doc_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            raise ReviewRefused(404, "not_found", "We could not find that review.")
        if r.status != "REQUESTED":
            raise ReviewRefused(
                409,
                "already_started",
                "A reviewer has already taken this file, so it can no longer be cancelled.",
            )
        r.status, r.completed_at, r.updated_at = "CANCELLED", datetime.now(UTC), datetime.now(UTC)
        await billing.release_usage(db, FEATURE, str(review_id))
        db.add(_audit(org_id, user_id, "review.cancelled", review_id=str(review_id)))


async def reviews_for(org_id: uuid.UUID, doc_id: uuid.UUID) -> list[DocumentReview]:
    async with tenant_session(org_id) as db:
        return list(
            (
                await db.execute(
                    select(DocumentReview)
                    .where(DocumentReview.document_id == doc_id)
                    .order_by(DocumentReview.requested_at.desc())
                    .limit(20)
                )
            ).scalars()
        )


# --- the reviewer's side -------------------------------------------------------------------------------


def _queue_row(r, me: uuid.UUID) -> dict:
    """What a reviewer may see BEFORE claiming a file: counts and times, never a name, a note or content."""
    return {
        "id": str(r.id),
        "status": r.status,
        "mine": r.reviewer_id == me,
        "requested_at": r.requested_at,
        "due_at": r.due_at,
        "overdue": r.status in ("REQUESTED", "IN_REVIEW") and r.due_at < datetime.now(UTC),
        "pages": r.pages,
        "snapshot": {k: v for k, v in (r.snapshot or {}).items() if k != "has_note"},
        "claimed_at": r.claimed_at,
    }


async def queue(reviewer_id: uuid.UUID) -> list[dict]:
    async with reviewer_session(reviewer_id) as db:
        rows = (
            await db.execute(
                select(DocumentReview)
                .where(
                    (DocumentReview.status == "REQUESTED")
                    | (
                        (DocumentReview.status == "IN_REVIEW")
                        & (DocumentReview.reviewer_id == reviewer_id)
                    )
                )
                .order_by(DocumentReview.due_at)
                .limit(200)
            )
        ).scalars()
        return [_queue_row(r, reviewer_id) for r in rows]


async def claim(reviewer_id: uuid.UUID, review_id: uuid.UUID) -> dict:
    async with reviewer_session(reviewer_id) as db:
        held = (
            await db.execute(
                text(
                    "SELECT count(*) FROM document_reviews WHERE status = 'IN_REVIEW' AND reviewer_id = :r"
                ),
                {"r": reviewer_id},
            )
        ).scalar_one()
        if held >= MAX_CLAIMS:
            raise ReviewRefused(
                409,
                "too_many_claims",
                f"You are already working on {MAX_CLAIMS} files. Finish or release one first.",
            )
        row = (
            await db.execute(
                text(
                    "UPDATE document_reviews SET status = 'IN_REVIEW', reviewer_id = :r, claimed_at = now(), updated_at = now() "
                    "WHERE id = :i AND status = 'REQUESTED' RETURNING organization_id, document_id"
                ),
                {"r": reviewer_id, "i": review_id},
            )
        ).first()
    if row is None:
        raise ReviewRefused(
            409, "unavailable", "Someone else has taken this file, or the customer cancelled it."
        )
    async with tenant_session(row.organization_id) as db:
        db.add(
            _audit(
                row.organization_id,
                reviewer_id,
                "review.claimed",
                review_id=str(review_id),
                document_id=str(row.document_id),
            )
        )
    return {"id": str(review_id)}


async def release(reviewer_id: uuid.UUID, review_id: uuid.UUID) -> None:
    async with reviewer_session(reviewer_id) as db:
        row = (
            await db.execute(
                text(
                    "UPDATE document_reviews SET status = 'REQUESTED', reviewer_id = NULL, claimed_at = NULL, updated_at = now() "
                    "WHERE id = :i AND status = 'IN_REVIEW' AND reviewer_id = :r RETURNING organization_id"
                ),
                {"r": reviewer_id, "i": review_id},
            )
        ).first()
    if row is None:
        raise ReviewRefused(409, "not_yours", "You are not working on this file.")
    async with tenant_session(row.organization_id) as db:
        db.add(
            _audit(row.organization_id, reviewer_id, "review.released", review_id=str(review_id))
        )


async def held_by(reviewer_id: uuid.UUID, review_id: uuid.UUID) -> DocumentReview:
    """The review, only if this reviewer holds it right now. The one gate in front of every read of a customer's file."""
    async with reviewer_session(reviewer_id) as db:
        r = (
            await db.execute(select(DocumentReview).where(DocumentReview.id == review_id))
        ).scalar_one_or_none()
    if r is None or r.status != "IN_REVIEW" or r.reviewer_id != reviewer_id:
        raise ReviewRefused(403, "not_yours", "You are not working on this file.")
    return r


async def reviewer_state(reviewer_id: uuid.UUID, review_id: uuid.UUID) -> dict:
    r = await held_by(reviewer_id, review_id)
    s = await document_fixes.get_state(r.organization_id, r.document_id)
    async with tenant_session(r.organization_id) as db:
        findings = list(
            (
                await db.execute(
                    select(DocumentFinding)
                    .where(DocumentFinding.audit_id == s["audit"].id)
                    .order_by(DocumentFinding.ordinal)
                )
            ).scalars()
        )
    return {"review": r, **s, "findings": findings}


async def original(reviewer_id: uuid.UUID, review_id: uuid.UUID) -> tuple[bytes, str]:
    r = await held_by(reviewer_id, review_id)
    async with tenant_session(r.organization_id) as db:
        doc = await documents.get_document(db, r.document_id)
        if doc is None or doc.status != DocumentStatus.CLEAN:
            raise ReviewRefused(409, "not_ready", "That file is no longer available.")
        data = await documents.load_clean(db, doc)
        db.add(
            _audit(
                r.organization_id,
                reviewer_id,
                "review.original_downloaded",
                review_id=str(review_id),
                document_id=str(doc.id),
            )
        )
        return data, doc.filename


async def result_file(reviewer_id: uuid.UUID, review_id: uuid.UUID) -> tuple[bytes, str]:
    """The fixed copy built during this review, so the reviewer can check it before delivering it."""
    r = await held_by(reviewer_id, review_id)
    async with tenant_session(r.organization_id) as db:
        fix = (
            await db.execute(
                select(DocumentFix)
                .where(DocumentFix.document_id == r.document_id, DocumentFix.status == "READY")
                .order_by(DocumentFix.finished_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if fix is None or fix.result_document_id is None or fix.finished_at < r.claimed_at:
            raise ReviewRefused(409, "no_result", "Build the fixed copy first.")
        doc = await documents.get_document(db, fix.result_document_id)
        data = await documents.load_clean(db, doc)
        db.add(
            _audit(
                r.organization_id,
                reviewer_id,
                "review.result_downloaded",
                review_id=str(review_id),
                document_id=str(doc.id),
            )
        )
        return data, doc.filename


async def save_plan(reviewer_id: uuid.UUID, review_id: uuid.UUID, plan: FixPlan) -> DocumentFix:
    r = await held_by(reviewer_id, review_id)
    try:
        return await document_fixes.save_plan(
            r.organization_id, reviewer_id, r.document_id, plan, by_reviewer=True
        )
    except document_fixes.FixRefused as e:
        raise _from_fix(e) from None


async def build(reviewer_id: uuid.UUID, review_id: uuid.UUID) -> DocumentFix:
    r = await held_by(reviewer_id, review_id)
    try:
        fix = await document_fixes.start_build(
            r.organization_id, r.document_id, charge_pages=False, by_reviewer=True
        )
    except document_fixes.FixRefused as e:
        raise _from_fix(e) from None
    async with tenant_session(r.organization_id) as db:
        db.add(
            _audit(
                r.organization_id,
                reviewer_id,
                "review.fix_built",
                review_id=str(review_id),
                fix_id=str(fix.id),
            )
        )
    return fix


async def submit(
    reviewer_id: uuid.UUID,
    review_id: uuid.UUID,
    outcome: str,
    message: str | None,
    minutes: int | None,
) -> DocumentReview:
    """`deliver` (a fixed copy made during this review) or `decline` (we could not improve this file, with the reason)."""
    r = await held_by(reviewer_id, review_id)
    message = " ".join((message or "").split())[:MAX_MESSAGE] or None
    result_id = None
    if outcome == "deliver":
        async with tenant_session(r.organization_id) as db:
            fix = (
                await db.execute(
                    select(DocumentFix)
                    .where(DocumentFix.document_id == r.document_id, DocumentFix.status == "READY")
                    .order_by(DocumentFix.finished_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if (
            fix is None
            or fix.result_document_id is None
            or fix.finished_at is None
            or fix.finished_at < r.claimed_at
        ):
            raise ReviewRefused(409, "no_result", "Build the fixed copy first, then deliver it.")
        result_id, status = fix.result_document_id, "COMPLETED"
    elif outcome == "decline":
        if not message or len(message) < 10:
            raise ReviewRefused(
                422,
                "reason_required",
                "Tell the customer why the file could not be improved (at least a sentence).",
            )
        status = "DECLINED"
    else:
        raise ReviewRefused(422, "bad_outcome", "Choose to deliver the fixed copy or to decline.")
    now = datetime.now(UTC)
    elapsed = int((now - r.claimed_at).total_seconds())
    if minutes is not None and not 0 <= minutes <= 1440:
        raise ReviewRefused(422, "bad_minutes", "Minutes spent must be between 0 and 1440.")
    async with reviewer_session(reviewer_id) as db:
        row = (
            await db.execute(
                text(
                    "UPDATE document_reviews SET status = :s, completed_at = now(), updated_at = now(), outcome_note = :m, "
                    "result_document_id = :d, reported_minutes = :min, elapsed_seconds = :e "
                    "WHERE id = :i AND status = 'IN_REVIEW' AND reviewer_id = :r RETURNING id"
                ),
                {
                    "s": status,
                    "m": message,
                    "d": result_id,
                    "min": minutes if minutes is not None else -(-elapsed // 60),
                    "e": elapsed,
                    "i": review_id,
                    "r": reviewer_id,
                },
            )
        ).first()
    if row is None:
        raise ReviewRefused(409, "not_yours", "You are not working on this file.")
    async with tenant_session(r.organization_id) as db:
        await (billing.commit_usage if status == "COMPLETED" else billing.release_usage)(
            db, FEATURE, str(review_id)
        )
        db.add(
            _audit(
                r.organization_id,
                reviewer_id,
                f"review.{status.lower()}",
                review_id=str(review_id),
                document_id=str(r.document_id),
            )
        )
    await notify_review_done(r.organization_id, review_id)
    return await held_or_done(r.organization_id, review_id)


async def held_or_done(org_id: uuid.UUID, review_id: uuid.UUID) -> DocumentReview:
    async with tenant_session(org_id) as db:
        return (
            await db.execute(select(DocumentReview).where(DocumentReview.id == review_id))
        ).scalar_one()


async def notify_review_done(org_id: uuid.UUID, review_id: uuid.UUID) -> None:
    """Tell the person who asked, and fire the webhook. Never raises: a mail problem must not undo the review."""
    try:
        from . import notify, webhooks  # noqa: PLC0415

        async with tenant_session(org_id) as db:
            r = (
                await db.execute(select(DocumentReview).where(DocumentReview.id == review_id))
            ).scalar_one()
            doc = await documents.get_document(db, r.document_id)
        name = doc.filename if doc else "your document"
        if r.status == "COMPLETED":
            outcome = "A fixed copy is ready to download." + (
                f" The reviewer says: {r.outcome_note}" if r.outcome_note else ""
            )
        else:
            outcome = f"We could not improve this file. The reviewer says: {r.outcome_note}"
        await webhooks.emit_event(
            org_id,
            "review.completed",
            {
                "review_id": str(review_id),
                "document_id": str(r.document_id),
                "outcome": "delivered" if r.status == "COMPLETED" else "declined",
                "result_document_id": str(r.result_document_id) if r.result_document_id else None,
                "api_path": f"/v1/documents/{r.document_id}",
            },
        )
        to = await notify.user_email(org_id, r.requested_by)
        recipients = [to] if to else await notify.org_admin_emails(org_id)
        await notify.emit(
            "document.review_done",
            org_id=org_id,
            recipients=recipients,
            variables={"filename": name, "outcome": outcome, "document_id": str(r.document_id)},
            dedupe_key=f"document.review_done:{review_id}",
        )
    except Exception:  # noqa: BLE001
        log.exception("could not announce the finished review %s", review_id)


# --- the owner's side ------------------------------------------------------------------------------------


async def admin_release(actor: uuid.UUID, review_id: uuid.UUID) -> None:
    """Take a file back from a reviewer (they went away) so someone else can pick it up."""
    async with admin_session(
        actor_user_id=actor, reason="release a review claim", action="admin.review_release"
    ) as db:
        r = (
            await db.execute(
                text(
                    "SELECT organization_id FROM document_reviews WHERE id = :i AND status = 'IN_REVIEW'"
                ),
                {"i": review_id},
            )
        ).first()
    if r is None:
        raise ReviewRefused(404, "not_found", "No review in progress has that id.")
    async with tenant_session(r.organization_id) as db:
        await db.execute(
            text(
                "UPDATE document_reviews SET status = 'REQUESTED', reviewer_id = NULL, claimed_at = NULL, updated_at = now() WHERE id = :i"
            ),
            {"i": review_id},
        )
        db.add(
            _audit(r.organization_id, actor, "review.released_by_admin", review_id=str(review_id))
        )


async def stats() -> dict:
    """Queue health, turnaround against the target, and what a review and a page cost, for /admin."""
    cost = (await get_config().effective("documents.review")).value.reviewer_cost_per_hour
    async with admin_session(
        actor_user_id=None, reason="review statistics", action="admin.read"
    ) as db:
        q = (
            await db.execute(
                text(
                    "SELECT count(*) FILTER (WHERE status = 'REQUESTED') AS waiting, count(*) FILTER (WHERE status = 'IN_REVIEW') AS in_review, "
                    "count(*) FILTER (WHERE status IN ('REQUESTED', 'IN_REVIEW') AND due_at < now()) AS overdue FROM document_reviews"
                )
            )
        ).one()
        d = (
            await db.execute(
                text(
                    "SELECT count(*) AS done, count(*) FILTER (WHERE status = 'COMPLETED') AS delivered, "
                    "count(*) FILTER (WHERE completed_at <= due_at) AS on_time, "
                    "coalesce(avg(elapsed_seconds), 0) AS avg_elapsed, coalesce(avg(reported_minutes), 0) AS avg_minutes, "
                    "coalesce(sum(reported_minutes), 0) AS total_minutes, coalesce(sum(pages), 0) AS pages "
                    "FROM document_reviews WHERE status IN ('COMPLETED', 'DECLINED') AND completed_at > now() - interval '30 days'"
                )
            )
        ).one()
        people = [
            {
                "id": str(r.id),
                "email": r.email,
                "role": r.role,
                "active": r.is_active,
                "open": r.open,
                "done_30d": r.done,
                "mfa": r.mfa_enabled_at is not None,
            }
            for r in (
                await db.execute(
                    text(
                        "SELECT u.id, u.email, u.role, u.is_active, u.mfa_enabled_at, "
                        "count(r.*) FILTER (WHERE r.status = 'IN_REVIEW') AS open, "
                        "count(r.*) FILTER (WHERE r.status IN ('COMPLETED', 'DECLINED') AND r.completed_at > now() - interval '30 days') AS done "
                        "FROM users u LEFT JOIN document_reviews r ON r.reviewer_id = u.id "
                        "WHERE u.role = 'REVIEWER' GROUP BY u.id ORDER BY u.email"
                    )
                )
            ).all()
        ]
        in_progress = [
            {"id": str(r.id), "claimed_at": r.claimed_at, "due_at": r.due_at, "reviewer": r.email}
            for r in (
                await db.execute(
                    text(
                        "SELECT r.id, r.claimed_at, r.due_at, u.email FROM document_reviews r JOIN users u ON u.id = r.reviewer_id "
                        "WHERE r.status = 'IN_REVIEW' ORDER BY r.claimed_at"
                    )
                )
            ).all()
        ]
    per_review = float(d.avg_minutes) / 60 * cost
    per_page = (float(d.total_minutes) / 60 * cost) / d.pages if d.pages else 0.0
    return {
        "waiting": q.waiting,
        "in_review": q.in_review,
        "overdue": q.overdue,
        "finished_30d": d.done,
        "delivered_30d": d.delivered,
        "on_time_percent": round(100 * d.on_time / d.done) if d.done else None,
        "avg_elapsed_minutes": round(float(d.avg_elapsed) / 60, 1),
        "avg_reported_minutes": round(float(d.avg_minutes), 1),
        "cost_per_hour": cost,
        "cost_per_review": round(per_review, 2) if cost else None,
        "cost_per_page": round(per_page, 2) if cost else None,
        "reviewers": people,
        "in_progress": in_progress,
    }


# --- background sweeps -----------------------------------------------------------------------------------


async def release_stale_claims() -> int:
    """A reviewer who holds a file past the admin-set timeout loses it: it goes back to the queue."""
    hours = (await get_config().effective("documents.review")).value.claim_timeout_hours
    async with admin_session(
        actor_user_id=None, reason="stale review claim sweep", action="system.release_claims"
    ) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, organization_id, reviewer_id FROM document_reviews WHERE status = 'IN_REVIEW' "
                    "AND claimed_at < now() - CAST(:age AS interval) LIMIT 200"
                ),
                {"age": timedelta(hours=hours)},
            )
        ).all()
    for r in rows:
        async with tenant_session(r.organization_id) as db:
            await db.execute(
                text(
                    "UPDATE document_reviews SET status = 'REQUESTED', reviewer_id = NULL, claimed_at = NULL, updated_at = now() WHERE id = :i AND status = 'IN_REVIEW'"
                ),
                {"i": r.id},
            )
            db.add(
                _audit(
                    r.organization_id,
                    None,
                    "review.claim_expired",
                    review_id=str(r.id),
                    reviewer_id=str(r.reviewer_id),
                )
            )
    return len(rows)


async def sweep_review_reservations() -> dict[str, int]:
    """Settle a review credit whose review ended without it (a crash between two writes)."""
    async with admin_session(
        actor_user_id=None,
        reason="orphaned review credit sweep",
        action="system.sweep_reservations",
    ) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT r.organization_id, r.job_id, v.status AS review_status FROM usage_reservations r "
                    "LEFT JOIN document_reviews v ON v.id::text = r.job_id "
                    "WHERE r.status = 'RESERVED' AND r.feature_key = :f AND r.created_at < now() - interval '30 minutes' "
                    "AND (v.id IS NULL OR v.status IN ('COMPLETED', 'DECLINED', 'CANCELLED'))"
                ),
                {"f": FEATURE},
            )
        ).all()
    out = {"committed": 0, "released": 0}
    for r in rows:
        keep = r.review_status == "COMPLETED"
        async with tenant_session(r.organization_id) as db:
            ok = await (billing.commit_usage if keep else billing.release_usage)(
                db, FEATURE, r.job_id
            )
        if ok:
            out["committed" if keep else "released"] += 1
    return out


@celery_app.task(name="documents.release_stale_claims")
def release_stale_claims_task() -> int:
    import asyncio

    async def run() -> int:
        try:
            return await release_stale_claims()
        finally:
            await dispose_engines()

    return asyncio.run(run())


@celery_app.task(name="documents.sweep_review_reservations")
def sweep_review_reservations_task() -> dict[str, int]:
    import asyncio

    async def run() -> dict[str, int]:
        try:
            return await sweep_review_reservations()
        finally:
            await dispose_engines()

    return asyncio.run(run())


celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    "release-stale-review-claims": {"task": "documents.release_stale_claims", "schedule": 900.0},
    "sweep-review-reservations": {"task": "documents.sweep_review_reservations", "schedule": 600.0},
}
