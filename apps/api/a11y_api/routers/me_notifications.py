"""A member's own notifications and email preferences. Everything here is filtered to the signed-in person: other members
of the same organisation never see each other's items (row-level security isolates organisations; these queries isolate people)."""

from __future__ import annotations

import uuid
from datetime import datetime

from a11y_core.db import tenant_session
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..deps import current_principal, ensure_flag
from ..security import Principal

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/notifications")
async def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    unread: bool = False,
    before: datetime | None = None,
    p: Principal = Depends(current_principal),
):
    await ensure_flag("notification_center", p)
    async with tenant_session(p.org_id) as db:
        count = (
            await db.execute(
                text(
                    "SELECT count(*) FROM user_notifications WHERE user_id=:u AND read_at IS NULL"
                ),
                {"u": p.user_id},
            )
        ).scalar_one()
        rows = (
            await db.execute(
                text(
                    "SELECT id, event, title, body, link, created_at, read_at FROM user_notifications WHERE user_id=:u "
                    "AND (NOT :unread OR read_at IS NULL) AND (CAST(:b AS timestamptz) IS NULL OR created_at < :b) "
                    "ORDER BY created_at DESC LIMIT :l"
                ),
                {"u": p.user_id, "unread": unread, "b": before, "l": limit + 1},
            )
        ).all()
    page = rows[:limit]
    return {
        "unread": count,
        "items": [
            {
                "id": str(r.id),
                "event": r.event,
                "title": r.title,
                "body": r.body,
                "link": r.link,
                "created_at": r.created_at,
                "read": r.read_at is not None,
            }
            for r in page
        ],
        "next_before": page[-1].created_at if len(rows) > limit and page else None,
    }


class ReadIn(BaseModel):
    ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    all: bool = False


@router.post("/notifications/read")
async def mark_read(body: ReadIn, p: Principal = Depends(current_principal)):
    await ensure_flag("notification_center", p)
    async with tenant_session(p.org_id) as db:
        if body.all:
            await db.execute(
                text(
                    "UPDATE user_notifications SET read_at=now() WHERE user_id=:u AND read_at IS NULL"
                ),
                {"u": p.user_id},
            )
        elif body.ids:
            await db.execute(
                text(
                    "UPDATE user_notifications SET read_at=now() WHERE user_id=:u AND read_at IS NULL AND id = ANY(:i)"
                ),
                {"u": p.user_id, "i": body.ids},
            )
        left = (
            await db.execute(
                text(
                    "SELECT count(*) FROM user_notifications WHERE user_id=:u AND read_at IS NULL"
                ),
                {"u": p.user_id},
            )
        ).scalar_one()
    return {"unread": left}


class PrefsIn(BaseModel):
    email_scan: bool


@router.get("/notification-preferences")
async def get_prefs(p: Principal = Depends(current_principal)):
    async with tenant_session(p.org_id) as db:
        v = (
            await db.execute(
                text("SELECT email_scan FROM user_preferences WHERE user_id=:u"), {"u": p.user_id}
            )
        ).scalar_one_or_none()
    return {"email_scan": True if v is None else v}


@router.put("/notification-preferences")
async def put_prefs(body: PrefsIn, p: Principal = Depends(current_principal)):
    """Only optional email is a choice. Account, security and billing emails are not: people need them."""
    async with tenant_session(p.org_id) as db:
        await db.execute(
            text(
                "INSERT INTO user_preferences (user_id, organization_id, email_scan) VALUES (:u, :o, :v) "
                "ON CONFLICT (user_id) DO UPDATE SET email_scan = :v, updated_at = now()"
            ),
            {"u": p.user_id, "o": p.org_id, "v": body.email_scan},
        )
    return {"email_scan": body.email_scan}
