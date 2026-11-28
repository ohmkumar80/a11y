"""Super Admin: the email events, a live preview of draft wording, a test send to yourself, and the delivery log.

The wording itself is saved through the normal settings screen (``notify.templates``), so it is versioned, audited and
can be rolled back like every other setting. Previewing a draft never saves anything."""

from a11y_core import notify
from a11y_core.config.registry import GuardrailError
from a11y_core.db import admin_session
from a11y_core.mail import Mail
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..deps import require_super_admin
from ..mail import Mailer, get_mailer
from ..security import Principal

router = APIRouter(prefix="/admin/notifications", tags=["admin"])


def _event(key: str) -> notify.EventDef:
    ev = notify.EVENTS.get(key)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such email.")
    return ev


@router.get("/events")
async def events(_: Principal = Depends(require_super_admin)):
    out = []
    for ev in notify.EVENTS.values():
        o, _ref = await notify.override_for(ev.key)
        out.append(
            {
                "key": ev.key,
                "label": ev.label,
                "audience": ev.audience,
                "category": ev.category,
                "required": ev.required,
                "variables": ev.variables,
                "has_link": ev.action_path is not None,
                "default": {
                    "subject": ev.subject,
                    "intro": ev.intro,
                    "action_label": ev.action_label,
                    "outro": ev.outro,
                },
                "enabled": o.enabled if o else True,
                "edited": bool(o and (o.subject or o.intro or o.action_label or o.outro)),
            }
        )
    return out


class PreviewIn(BaseModel):
    event: str = Field(max_length=40)
    enabled: bool = True
    subject: str = Field("", max_length=150)
    intro: str = Field("", max_length=600)
    action_label: str = Field("", max_length=60)
    outro: str = Field("", max_length=400)


@router.post("/preview")
async def preview(body: PreviewIn, _: Principal = Depends(require_super_admin)):
    """Render DRAFT wording with sample data, running the same checks as saving. Nothing is stored or sent."""
    ev = _event(body.event)
    draft = notify.TemplateOverride(**body.model_dump())
    try:
        notify._templates_guard(notify.NotifyTemplates(items=[draft]), notify.NotifyTemplates())
    except GuardrailError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"detail": str(e), "field": "wording"}
        ) from None
    r = notify.render_event(ev.key, ev.sample, draft)
    return {
        "subject": r.subject,
        "text": r.text,
        "html": r.html,
        "accessibility_problems": notify.check_email_html(r.html),
    }


class TestIn(BaseModel):
    event: str = Field(max_length=40)


@router.post("/test")
async def test_send(
    body: TestIn, p: Principal = Depends(require_super_admin), mailer: Mailer = Depends(get_mailer)
):
    """Send the SAVED wording, with sample data, to the administrator's own address."""
    ev = _event(body.event)
    if not p.email:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Your account has no email address to send to."
        )
    mail: Mail | None = await notify.build(ev.key, p.email, ev.sample)
    if mail is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This email is switched off, so nothing was sent. Switch it on in Settings first.",
        )
    mail.subject = f"[Test] {mail.subject}"
    async with admin_session(
        actor_user_id=p.user_id, reason=f"test send of {ev.key}", action="notification.test"
    ):
        pass
    await mailer.send(mail, raise_errors=True)
    return {"sent_to": p.email}


@router.get("/log")
async def delivery_log(
    limit: int = Query(50, ge=1, le=200),
    state: str | None = Query(None, pattern="^(QUEUED|SENT|FAILED|SKIPPED)$"),
    p: Principal = Depends(require_super_admin),
):
    """Recent emails across all organisations (cross-tenant, so audit-logged)."""
    async with admin_session(
        actor_user_id=p.user_id, reason="read notification log", action="admin.read"
    ) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT n.id, n.event, n.to_email, n.status, n.attempts, n.error, n.created_at, n.sent_at, o.name AS organisation "
                    "FROM notification_log n JOIN organizations o ON o.id = n.organization_id "
                    "WHERE (CAST(:s AS text) IS NULL OR n.status = :s) ORDER BY n.created_at DESC LIMIT :l"
                ),
                {"s": state, "l": limit},
            )
        ).all()
    return [
        {
            "id": str(r.id),
            "event": r.event,
            "label": notify.EVENTS[r.event].label if r.event in notify.EVENTS else r.event,
            "to": r.to_email,
            "state": r.status,
            "attempts": r.attempts,
            "error": r.error,
            "organisation": r.organisation,
            "created_at": r.created_at,
            "sent_at": r.sent_at,
        }
        for r in rows
    ]
