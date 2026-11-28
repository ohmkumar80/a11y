"""The reviewer console API (ADR 0023): the queue, claiming a file, fixing it with the customer's tools, and delivering or declining.

Only platform reviewers (and the platform owner) can use it, checked against the database on every request. A reviewer
sees the queue as counts and times only; the file's name, note and content appear only after they claim it, and each open
and download is written to the customer's audit log."""

import uuid

from a11y_core import document_reviews
from a11y_core.doc_fix import FixPlan
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ..deps import require_reviewer
from ..security import Principal
from .documents import _audit_json, _finding_json, _fix_json

router = APIRouter(prefix="/review", tags=["review"])


def _refuse(r: document_reviews.ReviewRefused) -> HTTPException:
    return HTTPException(r.http_status, detail={"detail": r.message, "code": r.code})


class SubmitIn(BaseModel):
    outcome: str = Field(
        pattern="^(deliver|decline)$",
        description="`deliver` the fixed copy, or `decline` with a reason",
    )
    message: str | None = Field(None, max_length=2000, description="What the customer is told")
    minutes: int | None = Field(
        None,
        ge=0,
        le=1440,
        description="Minutes you spent; defaults to the time since you took the file",
    )


@router.get("/queue")
async def queue(p: Principal = Depends(require_reviewer)):
    items = await document_reviews.queue(p.user_id)
    return {"items": items, "max_claims": document_reviews.MAX_CLAIMS}


@router.post("/{review_id}/claim")
async def claim(review_id: uuid.UUID, p: Principal = Depends(require_reviewer)):
    try:
        return await document_reviews.claim(p.user_id, review_id)
    except document_reviews.ReviewRefused as r:
        raise _refuse(r) from None


@router.post("/{review_id}/release", status_code=204)
async def release(review_id: uuid.UUID, p: Principal = Depends(require_reviewer)):
    try:
        await document_reviews.release(p.user_id, review_id)
    except document_reviews.ReviewRefused as r:
        raise _refuse(r) from None
    return Response(status_code=204)


@router.get("/{review_id}")
async def get_review(review_id: uuid.UUID, p: Principal = Depends(require_reviewer)):
    try:
        s = await document_reviews.reviewer_state(p.user_id, review_id)
    except (document_reviews.ReviewRefused, document_reviews.document_fixes.FixRefused) as r:
        if isinstance(r, document_reviews.ReviewRefused):
            raise _refuse(r) from None
        raise HTTPException(r.http_status, detail={"detail": r.message, "code": r.code}) from None
    rev, doc, audit = s["review"], s["document"], s["audit"]
    return {
        "review": {
            "id": str(rev.id),
            "status": rev.status,
            "requested_at": rev.requested_at,
            "due_at": rev.due_at,
            "claimed_at": rev.claimed_at,
            "note": rev.note,
            "pages": rev.pages,
        },
        "document": {"id": str(doc.id), "filename": doc.filename, "page_count": doc.page_count},
        "audit": _audit_json(audit),
        "findings": [_finding_json(f) for f in s["findings"]],
        "structure": audit.structure,
        "fix": _fix_json(s["fix"]),
    }


@router.get("/{review_id}/original")
async def original(review_id: uuid.UUID, p: Principal = Depends(require_reviewer)):
    try:
        data, name = await document_reviews.original(p.user_id, review_id)
    except document_reviews.ReviewRefused as r:
        raise _refuse(r) from None
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{name.replace(chr(34), "")}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{review_id}/result")
async def result(review_id: uuid.UUID, p: Principal = Depends(require_reviewer)):
    try:
        data, name = await document_reviews.result_file(p.user_id, review_id)
    except document_reviews.ReviewRefused as r:
        raise _refuse(r) from None
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{name.replace(chr(34), "")}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put("/{review_id}/fix")
async def save_fix(review_id: uuid.UUID, plan: FixPlan, p: Principal = Depends(require_reviewer)):
    try:
        return _fix_json(await document_reviews.save_plan(p.user_id, review_id, plan))
    except document_reviews.ReviewRefused as r:
        raise _refuse(r) from None


@router.post("/{review_id}/fix/build", status_code=202)
async def build_fix(review_id: uuid.UUID, p: Principal = Depends(require_reviewer)):
    try:
        return _fix_json(await document_reviews.build(p.user_id, review_id))
    except document_reviews.ReviewRefused as r:
        raise _refuse(r) from None


@router.post("/{review_id}/submit")
async def submit(review_id: uuid.UUID, body: SubmitIn, p: Principal = Depends(require_reviewer)):
    try:
        r = await document_reviews.submit(
            p.user_id, review_id, body.outcome, body.message, body.minutes
        )
    except document_reviews.ReviewRefused as e:
        raise _refuse(e) from None
    return {"id": str(r.id), "status": r.status}
