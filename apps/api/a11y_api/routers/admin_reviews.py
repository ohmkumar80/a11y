"""Super Admin: the reviewers and the review queue (ADR 0023). Create and switch off reviewers, set a new password, see
turnaround against the target and what a review costs, and take a file back from a reviewer who went away. Policy (on or
off, target hours, queue limits, the cost of an hour) is the `documents.review` setting."""

import uuid

from a11y_core import document_reviews
from a11y_core.db import admin_session, login_lookup_session
from a11y_core.models import Role, User
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, text, update

from ..deps import require_super_admin
from ..security import Principal, hash_password, password_problem

router = APIRouter(prefix="/admin", tags=["admin"])


class ReviewerIn(BaseModel):
    email: EmailStr
    password: str = Field(
        min_length=1,
        max_length=200,
        description="Their first password. Pass it on securely; they use it with two-step verification.",
    )


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class ActiveIn(BaseModel):
    active: bool


def _bad(msg: str, code: int = 422, field: str | None = None) -> HTTPException:
    return HTTPException(code, detail={"detail": msg, "field": field})


async def _reviewer(reviewer_id: uuid.UUID, actor: uuid.UUID, reason: str):
    async with admin_session(
        actor_user_id=actor, reason=reason, action="admin.reviewer_change"
    ) as db:
        r = (
            await db.execute(
                text("SELECT id, email FROM users WHERE id = :i AND role = 'REVIEWER'"),
                {"i": reviewer_id},
            )
        ).first()
    if r is None:
        raise _bad("There is no reviewer with that id.", 404)
    return r


@router.get("/reviews/overview")
async def overview(p: Principal = Depends(require_super_admin)):
    return await document_reviews.stats()


@router.post("/reviewers", status_code=201)
async def create_reviewer(body: ReviewerIn, p: Principal = Depends(require_super_admin)):
    email = body.email.strip().lower()
    if problem := password_problem(body.password, email):
        raise _bad(problem, field="password")
    async with admin_session(
        actor_user_id=p.user_id, reason=f"create reviewer {email}", action="admin.reviewer_created"
    ):
        pass
    async with login_lookup_session(email) as db:
        if (await db.execute(select(User.id).where(User.email == email))).first():
            raise _bad("Someone already uses that email address.", 409, "email")
        from datetime import UTC, datetime  # noqa: PLC0415

        u = User(
            organization_id=None,
            email=email,
            hashed_password=hash_password(body.password),
            role=Role.REVIEWER,
            email_verified_at=datetime.now(UTC),
        )
        db.add(u)
        await db.flush()
        return {"id": str(u.id), "email": email}


@router.post("/reviewers/{reviewer_id}/password", status_code=204)
async def set_password(
    reviewer_id: uuid.UUID, body: PasswordIn, p: Principal = Depends(require_super_admin)
):
    r = await _reviewer(reviewer_id, p.user_id, "set a reviewer's password")
    if problem := password_problem(body.password, r.email):
        raise _bad(problem, field="password")
    async with login_lookup_session(r.email) as db:
        await db.execute(
            update(User)
            .where(User.id == reviewer_id)
            .values(hashed_password=hash_password(body.password))
        )


@router.post("/reviewers/{reviewer_id}/active", status_code=204)
async def set_active(
    reviewer_id: uuid.UUID, body: ActiveIn, p: Principal = Depends(require_super_admin)
):
    r = await _reviewer(reviewer_id, p.user_id, "switch a reviewer on or off")
    async with login_lookup_session(r.email) as db:
        await db.execute(update(User).where(User.id == reviewer_id).values(is_active=body.active))


@router.post("/reviews/{review_id}/release", status_code=204)
async def release(review_id: uuid.UUID, p: Principal = Depends(require_super_admin)):
    try:
        await document_reviews.admin_release(p.user_id, review_id)
    except document_reviews.ReviewRefused as r:
        raise HTTPException(r.http_status, detail={"detail": r.message, "code": r.code}) from None
