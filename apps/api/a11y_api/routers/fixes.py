"""AI code-fix suggestions for findings (PROJECT_PLAN 3.13).

Asking for a fix queues a job on the browser worker (the re-scan oracle needs a browser). The answer is READY only
when the fix passed our checks; otherwise NEEDS_REVIEW with the reason, and no code."""

import hashlib
import uuid

from a11y_core import billing
from a11y_core.celery_app import celery_app
from a11y_core.config import get_config
from a11y_core.db import tenant_session
from a11y_core.models import FixSuggestion
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, text, update

from ..deps import current_principal
from ..security import Principal
from .scans import _rate_limit

router = APIRouter(tags=["fixes"])


class FixIn(BaseModel):
    retry: bool = False


def _problem(http_status: int, detail: str, **extra) -> HTTPException:
    return HTTPException(http_status, detail={"detail": detail, **extra})


def fix_json(r: FixSuggestion, credit_used: bool = False) -> dict:
    return {
        "id": str(r.id),
        "finding_id": str(r.finding_id),
        "rule": r.rule,
        "status": r.status,
        "rung": r.rung,
        "original_html": r.original_html,
        "fixed_html": r.fixed_html if r.status == "READY" else None,
        "explanation": r.explanation,
        "notes": r.notes,
        "checks": r.checks,
        "reason": r.reason,
        "detail": r.error_detail,
        "model_id": r.model_id,
        "attempts": r.attempts,
        "from_cache": r.from_cache,
        "credit_used": credit_used,
        "created_at": r.created_at,
        "finished_at": r.finished_at,
    }


async def _reserve_credit(db, org_id: uuid.UUID, fix_id: uuid.UUID, attempt: int) -> bool:
    """Hold one AI code-fix credit for this job. Inside a savepoint so a refusal leaves no half-made reservation. False =
    no credit available: the job still runs, but only ready-made recipes may answer (they cost nothing)."""
    job = str(fix_id) if attempt == 0 else f"{fix_id}:r{attempt}"
    try:
        async with db.begin_nested():
            await billing.reserve(db, org_id, billing.FIX_FEATURE, job)
        return True
    except billing.QuotaExceeded:
        return False


async def _credit_used(db, fix_id: uuid.UUID) -> bool:
    return bool(
        (
            await db.execute(
                text(
                    "SELECT 1 FROM usage_reservations WHERE feature_key=:f AND job_id LIKE :p AND status='COMMITTED' LIMIT 1"
                ),
                {"f": billing.FIX_FEATURE, "p": f"{fix_id}%"},
            )
        ).first()
    )


async def _enqueue(org_id: uuid.UUID, fix_id: uuid.UUID) -> None:
    try:
        celery_app.send_task("web.suggest_fix", args=[str(org_id), str(fix_id)], queue="web")
    except Exception:  # noqa: BLE001
        async with tenant_session(org_id) as db:
            await db.execute(
                update(FixSuggestion)
                .where(FixSuggestion.id == fix_id)
                .values(
                    status="FAILED",
                    error_detail="We could not start this just now. Please try again in a minute.",
                )
            )


@router.post("/scans/{scan_id}/findings/{finding_id}/fix", status_code=status.HTTP_202_ACCEPTED)
async def request_fix(
    scan_id: uuid.UUID,
    finding_id: uuid.UUID,
    body: FixIn | None = None,
    p: Principal = Depends(current_principal),
):
    """Idempotent: asking again returns the existing suggestion. ``retry`` re-runs one that failed or needed review
    (for example after an admin configured a model)."""
    cfg = get_config()
    async with tenant_session(p.org_id) as db:
        plan_id = (await db.execute(text("SELECT plan_id FROM subscriptions"))).scalar_one_or_none()
        f = (
            await db.execute(
                text(
                    "SELECT id, canonical_rule_id, html, kind FROM scan_findings WHERE id=:f AND scan_id=:s"
                ),
                {"f": finding_id, "s": scan_id},
            )
        ).first()
    if f is None:
        raise _problem(404, "We could not find that finding.")
    policy = (await cfg.effective("ai.code_fix", org_id=p.org_id, plan_id=plan_id)).value
    if not policy.enabled:
        raise _problem(
            403, "Fix suggestions are turned off for your account.", code="fixes_disabled"
        )
    if f.kind == "best_practice":
        raise _problem(422, "Best practices have no automated fix.", code="not_fixable")

    async with tenant_session(p.org_id) as db:
        cur = (
            await db.execute(select(FixSuggestion).where(FixSuggestion.finding_id == finding_id))
        ).scalar_one_or_none()
        if cur is not None:
            if not (body and body.retry) or cur.status not in ("FAILED", "NEEDS_REVIEW"):
                return fix_json(cur)
            await _rate_limit(p.org_id, policy.per_minute, bucket="fix", what="fixes")
            await db.execute(
                update(FixSuggestion)
                .where(FixSuggestion.id == cur.id)
                .values(
                    status="PENDING",
                    fixed_html=None,
                    rung=None,
                    reason=None,
                    error_detail=None,
                    checks=[],
                    notes=[],
                    explanation="",
                    attempts=0,
                    finished_at=None,
                    from_cache=False,
                )
            )
            fix_id = cur.id
            tries = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM usage_reservations WHERE feature_key=:f AND job_id LIKE :p"
                    ),
                    {"f": billing.FIX_FEATURE, "p": f"{cur.id}%"},
                )
            ).scalar_one()
            await _reserve_credit(db, p.org_id, cur.id, int(tries))
        else:
            await _rate_limit(p.org_id, policy.per_minute, bucket="fix", what="fixes")
            h = hashlib.sha256(f.html.encode()).hexdigest()
            # Rung 1: the same element with the same rule already has a validated fix in this organisation.
            hit = (
                await db.execute(
                    select(FixSuggestion)
                    .where(
                        FixSuggestion.rule == f.canonical_rule_id,
                        FixSuggestion.input_hash == h,
                        FixSuggestion.status == "READY",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            row = FixSuggestion(
                id=uuid.uuid4(),
                organization_id=p.org_id,
                scan_id=scan_id,
                finding_id=finding_id,
                rule=f.canonical_rule_id,
                input_hash=h,
                original_html=f.html,
                created_by=p.user_id,
            )
            if hit is not None:
                row.status, row.rung, row.fixed_html = "READY", hit.rung, hit.fixed_html
                row.explanation, row.notes, row.checks = hit.explanation, hit.notes, hit.checks
                row.model_id, row.from_cache, row.attempts = hit.model_id, True, 0
                db.add(row)
                await db.flush()
                await db.execute(
                    update(FixSuggestion)
                    .where(FixSuggestion.id == row.id)
                    .values(finished_at=text("now()"))
                )
                await db.refresh(row)
                return fix_json(row)
            db.add(row)
            await db.flush()
            fix_id = row.id
            await _reserve_credit(db, p.org_id, row.id, 0)
    await _enqueue(p.org_id, fix_id)
    async with tenant_session(p.org_id) as db:
        row = (
            await db.execute(select(FixSuggestion).where(FixSuggestion.id == fix_id))
        ).scalar_one()
        return fix_json(row, await _credit_used(db, fix_id))


@router.get("/fixes/{fix_id}")
async def get_fix(fix_id: uuid.UUID, p: Principal = Depends(current_principal)):
    async with tenant_session(p.org_id) as db:
        r = (
            await db.execute(select(FixSuggestion).where(FixSuggestion.id == fix_id))
        ).scalar_one_or_none()
    if r is None:
        raise _problem(404, "We could not find that fix.")
    async with tenant_session(p.org_id) as db:
        used = await _credit_used(db, fix_id)
    return fix_json(r, used)
