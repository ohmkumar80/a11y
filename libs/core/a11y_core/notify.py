"""Notification events and email templates (PROJECT_PLAN 3.14, "templates first").

Every email is one of the events below. An event has a permanent default (text, variables, where the button goes) and
the layout is fixed code, so an email is accessible whoever edits its wording: semantic HTML, real text, contrast of
17:1 for body and 8.6:1 for links, a visible address as well as the link, and a plain-text part. Admins change only
the wording (setting ``notify.templates``, versioned and audited like every setting), and a guard refuses unknown
``{placeholders}`` and generic link text, so a typo can never reach a customer.

Delivery is idempotent and logged (table ``notification_log``): one row per recipient and ``dedupe_key``, so a retried
job, a redelivered task or a repeated beat run never sends the same email twice."""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from html import escape
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text

from .config import get_config
from .config.registry import GuardrailError, SettingDef, register
from .db import tenant_session
from .mail import Mail, Mailer, get_mailer
from .settings import get_settings

log = logging.getLogger(__name__)
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
GENERIC_LINK_TEXT = {"click here", "here", "link", "read more", "more", "click", "this link"}
MAX_ATTEMPTS = 4


@dataclass(frozen=True)
class EventDef:
    key: str
    label: str
    audience: Literal["user", "actor", "org_admins"]
    category: Literal["account", "billing", "scan"]
    variables: dict[
        str, str
    ]  # name -> what it holds (shown to admins; the only placeholders allowed)
    subject: str
    intro: str
    action_label: str
    action_path: str | None  # joined to the public web address; may contain {placeholders}
    outro: str
    sample: dict[str, str] = field(default_factory=dict)
    required: bool = False  # people could not use the product without it: cannot be switched off


def _e(**kw) -> EventDef:
    return EventDef(**kw)


EVENTS: dict[str, EventDef] = {
    e.key: e
    for e in [
        _e(
            key="auth.verify_email",
            label="Confirm email address",
            audience="user",
            category="account",
            required=True,
            variables={"token": "The one-time token in the link"},
            subject="Confirm your email address",
            intro="Confirm your email address to finish creating your account.",
            action_label="Confirm email address",
            action_path="/verify-email?token={token}",
            outro="This link works for 24 hours. If you did not sign up, you can ignore this email.",
            sample={"token": "sample-token"},
        ),
        _e(
            key="auth.reset_password",
            label="Reset password",
            audience="user",
            category="account",
            required=True,
            variables={"token": "The one-time token in the link"},
            subject="Reset your password",
            intro="We received a request to reset your password.",
            action_label="Choose a new password",
            action_path="/reset-password?token={token}",
            outro="This link works for 1 hour. If you did not ask for this, you can ignore this email.",
            sample={"token": "sample-token"},
        ),
        _e(
            key="auth.invite",
            label="Team invitation",
            audience="user",
            category="account",
            required=True,
            variables={
                "token": "The one-time token in the link",
                "org_name": "The organisation's name",
            },
            subject="You are invited to join {org_name}",
            intro="{org_name} invited you to join their team.",
            action_label="Accept the invitation",
            action_path="/accept-invite?token={token}",
            outro="This invitation works for 7 days.",
            sample={"token": "sample-token", "org_name": "Example Ltd"},
        ),
        _e(
            key="auth.already_registered",
            label="Sign-up with an existing address",
            audience="user",
            category="account",
            required=True,
            variables={},
            subject="You already have an account",
            intro="Someone tried to sign up with this email address, but an account already exists.",
            action_label="Log in",
            action_path="/login",
            outro="If this was you, log in or reset your password. If not, no action is needed.",
        ),
        _e(
            key="trial.ending",
            label="Trial ending soon",
            audience="org_admins",
            category="billing",
            variables={
                "days_left_text": 'For example "3 days" or "1 day"',
                "ends_on": "The date the trial ends",
                "plan_name": "The plan they are trying",
            },
            subject="Your free trial ends in {days_left_text}",
            intro="Your free trial ends on {ends_on}. After that your account becomes read-only: you can still open your scans and reports, but you cannot start new scans until you choose a plan.",
            action_label="Choose a plan",
            action_path="/org#plan",
            outro="Nothing is deleted when a trial ends.",
            sample={
                "days_left_text": "3 days",
                "ends_on": "30 November 2026",
                "plan_name": "Trial",
            },
        ),
        _e(
            key="trial.expired",
            label="Trial ended",
            audience="org_admins",
            category="billing",
            variables={"plan_name": "The plan they were trying"},
            subject="Your free trial has ended",
            intro="Your account is now read-only. Your scans and reports are still here, but you cannot start new scans until you choose a plan.",
            action_label="Choose a plan",
            action_path="/org#plan",
            outro="Nothing has been deleted.",
            sample={"plan_name": "Trial"},
        ),
        _e(
            key="document.review_done",
            label="A person finished checking a document",
            audience="actor",
            category="scan",
            variables={
                "filename": "The document's name",
                "outcome": "What the reviewer did, in a sentence",
                "document_id": "The document's id",
            },
            subject="A person has checked {filename}",
            intro="{outcome}",
            action_label="Open your documents",
            action_path="/workspace/documents",
            outro="You asked for this check from the documents page. Automated and human checks together still do not make a file a guarantee of conformance.",
            sample={
                "filename": "annual-report.pdf",
                "outcome": "A fixed copy is ready to download.",
                "document_id": "sample-id",
            },
        ),
        _e(
            key="scan.completed",
            label="Scan finished",
            audience="actor",
            category="scan",
            variables={
                "url": "The address that was scanned",
                "summary": 'For example "12 problems, 3 of them critical or serious"',
                "scan_id": "The scan's id",
            },
            subject="Your accessibility scan of {url} is ready",
            intro="The scan of {url} has finished. {summary}",
            action_label="View the results",
            action_path="/workspace/scan?id={scan_id}",
            outro="Automated tests find only some accessibility problems. These results are not a statement of conformance.",
            sample={
                "url": "https://example.com/",
                "summary": "12 problems, 3 of them critical or serious.",
                "scan_id": "00000000-0000-0000-0000-000000000000",
            },
        ),
        _e(
            key="scan.failed",
            label="Scan did not finish",
            audience="actor",
            category="scan",
            variables={
                "url": "The address that was scanned",
                "reason": "Why it failed, in plain words",
                "credit_note": "Whether the scan credit was returned",
                "scan_id": "The scan's id",
            },
            subject="Your accessibility scan of {url} did not finish",
            intro="{reason} {credit_note}",
            action_label="See what happened",
            action_path="/workspace/scan?id={scan_id}",
            outro="You can start the scan again from your workspace.",
            sample={
                "url": "https://example.com/",
                "reason": "The page took too long to load.",
                "credit_note": "Your credit was used because the problem was with the page.",
                "scan_id": "00000000-0000-0000-0000-000000000000",
            },
        ),
        _e(
            key="webhook.disabled",
            label="Webhook switched off",
            audience="org_admins",
            category="account",
            variables={"url": "The webhook address", "reason": "Why it was switched off"},
            subject="A webhook was switched off: {url}",
            intro="We switched off the webhook for {url}. {reason} Events are no longer sent to it.",
            action_label="Review your webhooks",
            action_path="/org/webhooks",
            outro="Fix the receiver, then switch the webhook back on. Events that happened while it was off are not re-sent.",
            sample={
                "url": "https://hooks.example.com/a11y",
                "reason": "20 deliveries in a row failed.",
            },
        ),
        _e(
            key="quota.reached",
            label="Monthly scan limit reached",
            audience="org_admins",
            category="billing",
            variables={"used": "Scans used this month", "limit": "Scans the plan allows"},
            subject="You have used all your scans this month",
            intro="Your organisation has used {used} of {limit} scans this month, so new scans are paused until next month or until you upgrade your plan.",
            action_label="See plans",
            action_path="/org#plan",
            outro="Scans that are already running are not affected.",
            sample={"used": "10", "limit": "10"},
        ),
    ]
}


# --- admin-editable wording ---------------------------------------------------------------------


class TemplateOverride(BaseModel):
    """Empty text = use the built-in default. Only wording can change; the layout cannot."""

    event: Literal[tuple(EVENTS)] = Field(description="Which email this changes")  # type: ignore[valid-type]
    enabled: bool = Field(True, description="Send this email at all")
    subject: str = Field("", max_length=150, description="Empty = default")
    intro: str = Field("", max_length=600, description="Empty = default")
    action_label: str = Field(
        "", max_length=60, description="Link text: say what the link does. Empty = default"
    )
    outro: str = Field("", max_length=400, description="Empty = default")


class NotifyTemplates(BaseModel):
    items: list[TemplateOverride] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self):
        keys = [i.event for i in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("Each email can be changed only once.")
        return self


def check_placeholders(event: EventDef, label: str, value: str) -> None:
    unknown = sorted(set(PLACEHOLDER.findall(value)) - set(event.variables))
    if unknown:
        allowed = ", ".join("{" + v + "}" for v in event.variables) or "none"
        raise GuardrailError(
            f"{event.label}, {label}: {', '.join('{' + u + '}' for u in unknown)} is not available here. "
            f"You can use: {allowed}."
        )


def _templates_guard(new: NotifyTemplates, prev: NotifyTemplates) -> None:
    for item in new.items:
        ev = EVENTS[item.event]
        if ev.required and not item.enabled:
            raise GuardrailError(
                f"{ev.label} cannot be switched off: people could not sign in or join without it."
            )
        for label, value in (
            ("subject", item.subject),
            ("introduction", item.intro),
            ("link text", item.action_label),
            ("closing line", item.outro),
        ):
            check_placeholders(ev, label, value)
        if item.action_label.strip().lower() in GENERIC_LINK_TEXT:
            raise GuardrailError(
                f"{ev.label}: link text such as “{item.action_label}” does not say where the link goes. Describe the action, for example “View the results”."
            )
        if item.action_label and ev.action_path is None:
            raise GuardrailError(f"{ev.label} has no link, so it has no link text.")


register(
    SettingDef(
        key="notify.templates",
        model=NotifyTemplates,
        default=NotifyTemplates(),
        description="Change the wording of an email or switch it off. Leave a field empty to keep the built-in text. "
        "The layout is fixed so every email stays accessible.",
        guard=_templates_guard,
        owner_role="PLATFORM_OWNER",
        tags=("notifications",),
    )
)


# --- rendering ------------------------------------------------------------------------------------


def _fill(template: str, values: dict[str, str], *, html: bool) -> str:
    # Only {name} placeholders, never str.format: admin-edited text must not be able to reach attributes or methods.
    def sub(m: re.Match) -> str:
        v = str(values.get(m.group(1), ""))
        return escape(v) if html else v

    return PLACEHOLDER.sub(sub, template)


@dataclass
class Rendered:
    subject: str
    text: str
    html: str
    enabled: bool
    edited: bool


async def override_for(
    event: str, *, org_id=None, plan_id=None
) -> tuple[TemplateOverride | None, str | None]:
    eff = await get_config().effective("notify.templates", org_id=org_id, plan_id=plan_id)
    item = next((i for i in eff.value.items if i.event == event), None)
    return item, getattr(eff, "ref", None)


def render_event(
    event: str, variables: dict[str, str], override: TemplateOverride | None = None
) -> Rendered:
    ev = EVENTS[event]
    o = override
    subject = o.subject if o and o.subject else ev.subject
    intro = o.intro if o and o.intro else ev.intro
    label = o.action_label if o and o.action_label else ev.action_label
    outro = o.outro if o and o.outro else ev.outro
    base = get_settings().public_web_url.rstrip("/")
    url = base + _fill(ev.action_path, variables, html=False) if ev.action_path else None
    title = _fill(subject, variables, html=False)
    plain = _fill(intro, variables, html=False)
    plain_outro = _fill(outro, variables, html=False)
    action_html = (
        f'<p><a href="{escape(url)}" style="color:#0b4f9e;font-weight:bold;text-decoration:underline">{escape(_fill(label, variables, html=False))}</a></p>\n'
        f"<p>If the link does not work, copy this address into your browser:<br>{escape(url)}</p>\n"
        if url
        else ""
    )
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{escape(title)}</title></head>
<body style="margin:0;padding:24px;background:#ffffff;color:#1a1a1a;font:16px/1.5 Arial,Helvetica,sans-serif">
<main style="max-width:36rem;margin:0 auto">
<h1 style="font-size:24px;line-height:1.3;margin:0 0 16px">{escape(title)}</h1>
<p>{escape(plain)}</p>
{action_html}<p>{escape(plain_outro)}</p>
</main></body></html>"""
    text_body = (
        f"{title}\n\n{plain}\n\n"
        + (f"{_fill(label, variables, html=False)}: {url}\n\n" if url else "")
        + f"{plain_outro}\n"
    )
    return Rendered(title, text_body, html, enabled=o.enabled if o else True, edited=bool(o))


def check_email_html(html: str) -> list[str]:
    """Problems that would make an email inaccessible. The layout is fixed so this should always be empty; it exists so
    tests and the admin preview can say so with proof rather than hope."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.lang = self.charset = self.viewport = False
            self.title = ""
            self.h1 = 0
            self.imgs_without_alt = 0
            self.tables = 0
            self._in = ""
            self._a_text: list[str] = []
            self.links: list[str] = []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "html" and a.get("lang"):
                self.lang = True
            if tag == "meta" and a.get("charset"):
                self.charset = True
            if tag == "meta" and a.get("name") == "viewport":
                self.viewport = True
            if tag == "h1":
                self.h1 += 1
            if tag == "img" and "alt" not in a:
                self.imgs_without_alt += 1
            if tag == "table":
                self.tables += 1
            self._in = tag
            if tag == "a":
                self._a_text = []

        def handle_endtag(self, tag):
            if tag == "a":
                self.links.append("".join(self._a_text).strip())
            self._in = ""

        def handle_data(self, data):
            if self._in == "title":
                self.title += data
            if self._in == "a":
                self._a_text.append(data)

    p = P()
    p.feed(html)
    out = []
    if not p.lang:
        out.append("the page language is not set")
    if not p.title.strip():
        out.append("there is no title")
    if p.h1 != 1:
        out.append(f"there should be exactly one main heading, found {p.h1}")
    if p.imgs_without_alt:
        out.append("an image has no text alternative")
    if p.tables:
        out.append("tables are not used for layout")
    if not (p.charset and p.viewport):
        out.append("charset or viewport is missing")
    out += [
        f"link text {t!r} does not say where it goes"
        for t in p.links
        if t.lower() in GENERIC_LINK_TEXT or not t
    ]
    return out


async def build(
    event: str, to: str, variables: dict[str, str], *, org_id=None, plan_id=None
) -> Mail | None:
    """The finished email for an event, using the admin's wording; None if an admin switched the event off."""
    o, _ = await override_for(event, org_id=org_id, plan_id=plan_id)
    r = render_event(event, variables, o)
    return Mail(to=to, subject=r.subject, text=r.text, html=r.html) if r.enabled else None


# --- delivery (logged, de-duplicated, retried) ---------------------------------------------------


async def org_admin_emails(org_id: uuid.UUID) -> list[str]:
    async with tenant_session(org_id) as db:
        rows = await db.execute(
            text(
                "SELECT email FROM users WHERE role='COMPANY_ADMIN' AND email_verified_at IS NOT NULL AND is_active ORDER BY created_at"
            )
        )
        return [r[0] for r in rows]


async def user_email(org_id: uuid.UUID, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    async with tenant_session(org_id) as db:
        return (
            await db.execute(
                text(
                    "SELECT email FROM users WHERE id=:u AND email_verified_at IS NOT NULL AND is_active"
                ),
                {"u": user_id},
            )
        ).scalar_one_or_none()


async def emit(
    event: str,
    *,
    org_id: uuid.UUID,
    recipients: list[str],
    variables: dict[str, str],
    dedupe_key: str,
) -> list[uuid.UUID]:
    """Record who should get this email and queue the delivery. Calling it again with the same ``dedupe_key`` for the
    same recipient does nothing. Returns the ids that were newly queued."""
    from .celery_app import celery_app

    if event not in EVENTS:
        raise ValueError(f"unknown notification event {event!r}")
    from . import billing, flags  # noqa: PLC0415

    o, _ = await override_for(event, org_id=org_id)
    # Everything that may touch the database or cache is looked up BEFORE the main transaction opens: a request or job
    # must never hold one connection while waiting for another.
    async with tenant_session(org_id) as db:
        plan_id = (await billing.load_subscription(db)).plan_id
    centre_on = await flags.enabled("notification_center", org_id=org_id, plan_id=plan_id)
    ev = EVENTS[event]
    rendered = render_event(event, variables, o)
    link = _fill(ev.action_path, variables, html=False) if ev.action_path else None
    body = _fill(o.intro if o and o.intro else ev.intro, variables, html=False)

    queued: list[uuid.UUID] = []
    async with tenant_session(org_id) as db:
        addresses = list(dict.fromkeys(a.lower() for a in recipients))
        people = {
            r.email.lower(): r.id
            for r in (
                await db.execute(
                    text("SELECT id, email FROM users WHERE lower(email) = ANY(:e) AND is_active"),
                    {"e": addresses},
                )
            ).all()
        }
        quiet = {
            r.user_id
            for r in (
                await db.execute(text("SELECT user_id FROM user_preferences WHERE NOT email_scan"))
            ).all()
        }
        for to in addresses:
            uid = people.get(to)
            if uid is not None and centre_on and rendered.enabled:
                await db.execute(
                    text(
                        "INSERT INTO user_notifications (id, organization_id, user_id, event, title, body, link, dedupe_key) "
                        "VALUES (gen_random_uuid(), :o, :u, :e, :t, :b, :l, :d) ON CONFLICT (user_id, dedupe_key) DO NOTHING"
                    ),
                    {
                        "o": org_id,
                        "u": uid,
                        "e": event,
                        "t": rendered.subject,
                        "b": body,
                        "l": link,
                        "d": dedupe_key,
                    },
                )
            off = bool(o and not o.enabled)
            opted_out = ev.category == "scan" and uid in quiet
            status = "SKIPPED" if (off or opted_out) else "QUEUED"
            reason = (
                "Switched off by an administrator."
                if off
                else "The recipient chose not to get this kind of email."
                if opted_out
                else None
            )
            row = (
                await db.execute(
                    text(
                        "INSERT INTO notification_log (id, organization_id, event, to_email, status, variables, dedupe_key, error) "
                        "VALUES (gen_random_uuid(), :o, :e, :t, :s, CAST(:v AS jsonb), :d, :err) "
                        "ON CONFLICT (organization_id, dedupe_key, to_email) DO NOTHING RETURNING id"
                    ),
                    {
                        "o": org_id,
                        "e": event,
                        "t": to,
                        "s": status,
                        "v": json.dumps(variables),
                        "d": dedupe_key,
                        "err": reason,
                    },
                )
            ).first()
            if row is not None and status == "QUEUED":
                queued.append(row[0])
    for nid in queued:
        try:
            celery_app.send_task("notify.deliver", args=[str(org_id), str(nid)], queue="system")
        except Exception:  # noqa: BLE001 - the row stays QUEUED; the retry sweep picks it up
            log.exception("could not queue notification %s", nid)
    return queued


class DeliveryError(Exception):
    pass


async def deliver(
    org_id: uuid.UUID, notification_id: uuid.UUID, mailer: Mailer | None = None
) -> str:
    """Send one logged notification. Returns SENT, SKIPPED, FAILED, or QUEUED (a retry is due). Idempotent."""
    mailer = mailer or get_mailer()
    async with tenant_session(org_id) as db:
        row = (
            await db.execute(
                text(
                    "SELECT event, to_email, variables, status, attempts FROM notification_log WHERE id=:i FOR UPDATE"
                ),
                {"i": notification_id},
            )
        ).first()
        if row is None or row.status != "QUEUED":
            return row.status if row else "MISSING"
    o, ref = await override_for(row.event, org_id=org_id)
    r = render_event(row.event, dict(row.variables), o)
    if not r.enabled:
        async with tenant_session(org_id) as db:
            await db.execute(
                text(
                    "UPDATE notification_log SET status='SKIPPED', error='Switched off by an administrator.' WHERE id=:i"
                ),
                {"i": notification_id},
            )
        return "SKIPPED"
    try:
        await mailer.send(
            Mail(to=row.to_email, subject=r.subject, text=r.text, html=r.html), raise_errors=True
        )
    except Exception as e:  # noqa: BLE001
        attempts = row.attempts + 1
        final = attempts >= MAX_ATTEMPTS
        async with tenant_session(org_id) as db:
            await db.execute(
                text("UPDATE notification_log SET attempts=:a, status=:s, error=:e WHERE id=:i"),
                {
                    "a": attempts,
                    "s": "FAILED" if final else "QUEUED",
                    "e": f"{type(e).__name__}: {str(e)[:200]}",
                    "i": notification_id,
                },
            )
        if final:
            return "FAILED"
        raise DeliveryError(str(e)) from e
    async with tenant_session(org_id) as db:
        await db.execute(
            text(
                "UPDATE notification_log SET status='SENT', sent_at=now(), subject=:s, config_ref=:c, attempts=attempts+1, error=NULL WHERE id=:i"
            ),
            {"s": r.subject, "c": ref, "i": notification_id},
        )
    return "SENT"


def _register_tasks() -> None:
    import asyncio

    from .celery_app import celery_app
    from .db import dispose_engines

    @celery_app.task(name="notify.deliver", bind=True, max_retries=MAX_ATTEMPTS, acks_late=True)
    def deliver_task(self, org_id: str, notification_id: str) -> str:
        async def run() -> str:
            try:
                return await deliver(uuid.UUID(org_id), uuid.UUID(notification_id))
            finally:
                await dispose_engines()

        try:
            return asyncio.run(run())
        except DeliveryError as e:
            raise self.retry(countdown=60 * 2**self.request.retries, exc=e) from e


_register_tasks()


# --- the events the product raises ---------------------------------------------------------------


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


async def notify_scan_done(org_id: uuid.UUID, scan_id: uuid.UUID) -> None:
    """Tell whoever started the scan that it finished. Never raises: a mail problem must not affect the scan."""
    try:
        async with tenant_session(org_id) as db:
            job = (
                await db.execute(
                    text("SELECT created_by, start_url FROM scan_jobs WHERE id=:i"), {"i": scan_id}
                )
            ).first()
            if job is None:
                return
            n, serious = (
                await db.execute(
                    text(
                        "SELECT count(*), count(*) FILTER (WHERE severity IN ('critical','serious')) "
                        "FROM scan_findings WHERE scan_id=:i AND kind='violation'"
                    ),
                    {"i": scan_id},
                )
            ).one()
        summary = (
            f"{_plural(n, 'problem', 'problems')}, {serious} of them critical or serious."
            if n
            else "We found no failures with our automated tests. Automated tests cover only part of WCAG, so this does not show the site is accessible."
        )
        from . import webhooks  # noqa: PLC0415

        await webhooks.emit_event(
            org_id,
            "scan.completed",
            {
                "scan_id": str(scan_id),
                "url": job.start_url,
                "status": "SUCCEEDED",
                "findings": n,
                "critical_or_serious": serious,
                "api_path": f"/v1/scans/{scan_id}",
            },
        )
        to = await user_email(org_id, job.created_by)
        recipients = [to] if to else await org_admin_emails(org_id)
        await emit(
            "scan.completed",
            org_id=org_id,
            recipients=recipients,
            variables={"url": job.start_url, "summary": summary, "scan_id": str(scan_id)},
            dedupe_key=f"scan.completed:{scan_id}",
        )
    except Exception:  # noqa: BLE001
        log.exception("could not queue the scan-finished email for %s", scan_id)


async def notify_scan_failed(
    org_id: uuid.UUID, scan_id: uuid.UUID, reason: str, *, credit_returned: bool
) -> None:
    try:
        async with tenant_session(org_id) as db:
            job = (
                await db.execute(
                    text("SELECT created_by, start_url FROM scan_jobs WHERE id=:i"), {"i": scan_id}
                )
            ).first()
        if job is None:
            return
        from . import webhooks  # noqa: PLC0415

        await webhooks.emit_event(
            org_id,
            "scan.failed",
            {
                "scan_id": str(scan_id),
                "url": job.start_url,
                "status": "FAILED",
                "reason": reason,
                "credit_returned": credit_returned,
                "api_path": f"/v1/scans/{scan_id}",
            },
        )
        to = await user_email(org_id, job.created_by)
        recipients = [to] if to else await org_admin_emails(org_id)
        await emit(
            "scan.failed",
            org_id=org_id,
            recipients=recipients,
            variables={
                "url": job.start_url,
                "reason": reason,
                "credit_note": "Your scan credit was returned."
                if credit_returned
                else "Your scan credit was used, because the problem was with the address or the page.",
                "scan_id": str(scan_id),
            },
            dedupe_key=f"scan.failed:{scan_id}",
        )
    except Exception:  # noqa: BLE001
        log.exception("could not queue the scan-failed email for %s", scan_id)


async def notify_quota_reached(org_id: uuid.UUID, used: int, limit: int, period: str) -> None:
    """Once per organisation per month, however many scans are refused."""
    try:
        await emit(
            "quota.reached",
            org_id=org_id,
            recipients=await org_admin_emails(org_id),
            variables={"used": str(used), "limit": str(limit)},
            dedupe_key=f"quota.reached:{period}",
        )
    except Exception:  # noqa: BLE001
        log.exception("could not queue the quota email for %s", org_id)


async def notify_trial(
    org_id: uuid.UUID, event: str, variables: dict[str, str], dedupe_key: str
) -> None:
    try:
        await emit(
            event,
            org_id=org_id,
            recipients=await org_admin_emails(org_id),
            variables=variables,
            dedupe_key=dedupe_key,
        )
    except Exception:  # noqa: BLE001
        log.exception("could not queue %s for %s", event, org_id)


async def notify_webhook_disabled(org_id: uuid.UUID, endpoint_id: uuid.UUID, url: str) -> None:
    try:
        async with tenant_session(org_id) as db:
            reason = (
                await db.execute(
                    text("SELECT disabled_reason FROM webhook_endpoints WHERE id=:i"),
                    {"i": endpoint_id},
                )
            ).scalar_one_or_none()
        await emit(
            "webhook.disabled",
            org_id=org_id,
            recipients=await org_admin_emails(org_id),
            variables={"url": url, "reason": reason or ""},
            dedupe_key=f"webhook.disabled:{endpoint_id}:{reason}",
        )
    except Exception:  # noqa: BLE001
        log.exception("could not queue the webhook-disabled email for %s", endpoint_id)
