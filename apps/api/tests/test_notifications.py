# ruff: noqa: F811
"""Email events: catalog integrity, admin-editable wording, idempotent logged delivery, and the product's triggers."""

import uuid

import pytest
from a11y_core import billing, notify
from a11y_core.billing_jobs import expire_trials, send_trial_reminders
from a11y_core.config import Scope, get_config
from a11y_core.config.registry import GuardrailError
from a11y_core.db import tenant_session
from a11y_core.mail import Mailer, OutboxMailer
from a11y_core.scan_jobs import fail_scan
from a11y_web_audit.tasks import run_scan
from sqlalchemy import text

from .conftest import make_org, sql
from .test_billing import auth
from .test_scans_api import FAST, _cfg_reset, create, dev, high_ports, site  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
async def _clean():
    async def wipe():
        await sql("DELETE FROM setting_versions WHERE comment LIKE 'test-%'")
        r = get_config()._r()
        for k in await r.keys("cfg:*"):
            await r.delete(k)

    await wipe()
    yield
    await wipe()


async def save_templates(items, comment="test-tpl"):
    await get_config().save(
        "notify.templates", Scope.GLOBAL, "", {"items": items}, comment=comment, actor=None
    )


async def log_rows(org, event=None):
    q = "SELECT event, to_email, status, attempts, dedupe_key, subject FROM notification_log WHERE organization_id=$1"
    rows = await sql(
        q + (" AND event=$2" if event else "") + " ORDER BY created_at",
        org,
        *([event] if event else []),
    )
    return rows


# -- the catalog ----------------------------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(notify.EVENTS))
def test_every_event_is_complete_and_renders_an_accessible_email(key):
    ev = notify.EVENTS[key]
    for label, value in (
        ("subject", ev.subject),
        ("intro", ev.intro),
        ("outro", ev.outro),
        ("action_label", ev.action_label),
        ("action_path", ev.action_path or ""),
    ):
        notify.check_placeholders(ev, label, value)  # no placeholder the event cannot fill
    assert set(ev.sample) == set(ev.variables), (
        "a sample value for every variable, so the preview is real"
    )
    r = notify.render_event(key, ev.sample)
    assert notify.check_email_html(r.html) == []
    assert (
        "{" not in r.subject + r.text and "{" not in r.html.split("</head>")[1]
    )  # nothing left unfilled
    assert "http" in r.text and r.subject
    if ev.action_path:
        assert (
            r.text.count("http") >= 1 and "copy this address" in r.html
        )  # a visible address as well as the link


def test_the_accessibility_check_really_catches_problems():
    bad = '<html><head></head><body><h1>a</h1><h1>b</h1><img src="x"><a href="/x">click here</a><table></table></body></html>'
    problems = " ".join(notify.check_email_html(bad))
    for expect in (
        "language",
        "title",
        "exactly one main heading",
        "text alternative",
        "tables",
        "click here",
    ):
        assert expect in problems


# -- admin-editable wording -----------------------------------------------------------------------
async def test_an_admin_can_change_the_wording_and_variables_are_escaped():
    await save_templates(
        [
            {
                "event": "scan.completed",
                "subject": "Done: {url}",
                "intro": "Finished. {summary}",
                "action_label": "Open the results",
            }
        ]
    )
    o, _ = await notify.override_for("scan.completed")
    r = notify.render_event(
        "scan.completed",
        {"url": "https://x.example/<b>", "summary": "No problems.", "scan_id": "1"},
        o,
    )
    assert r.subject == "Done: https://x.example/<b>" and r.edited
    assert (
        "&lt;b&gt;" in r.html and "<b>" not in r.html.split("<main")[1]
    )  # a hostile value cannot inject markup
    assert (
        "Open the results" in r.html and "Automated tests find only some" in r.html
    )  # unedited parts keep their defaults
    assert notify.check_email_html(r.html) == []


def test_placeholders_cannot_reach_attributes_or_code():
    ev = notify.EVENTS["auth.invite"]
    o = notify.TemplateOverride(event="auth.invite", intro="{org_name.__class__} {0} {token}")
    r = notify.render_event("auth.invite", {"token": "t", "org_name": "Acme"}, o)
    assert (
        "{org_name.__class__}" in r.text and "Acme" not in r.text.split("\n")[2]
    )  # left as plain text, never evaluated
    assert ev.required


@pytest.mark.parametrize(
    "item,why",
    [
        ({"event": "scan.completed", "subject": "Hi {nope}"}, "not available"),
        ({"event": "scan.completed", "action_label": "Click here"}, "does not say where"),
        ({"event": "auth.verify_email", "enabled": False}, "cannot be switched off"),
        (
            {"event": "trial.ending", "intro": "Ends {days_left}"},
            "days_left_text",
        ),  # the message lists what is allowed
    ],
)
async def test_bad_wording_is_refused_with_a_helpful_reason(item, why):
    with pytest.raises(GuardrailError, match=why):
        await save_templates([item])


async def test_each_email_can_be_changed_only_once():
    with pytest.raises(GuardrailError):
        await save_templates(
            [{"event": "quota.reached"}, {"event": "quota.reached", "subject": "x"}]
        )


async def test_auth_emails_use_the_admins_wording():
    from a11y_api import mail as m

    await save_templates([{"event": "auth.reset_password", "subject": "Reset your a11y password"}])
    mail = await m.reset_password_mail("a@example.com", "tok123")
    assert mail.subject == "Reset your a11y password" and "tok123" in mail.text


# -- delivery -------------------------------------------------------------------------------------
class Failing(Mailer):
    async def send(self, mail, *, raise_errors=False):
        raise ConnectionError("smtp down")


async def test_emit_is_idempotent_and_delivery_sends_once(dev):
    org, user, email = await make_org()
    for _ in range(3):  # a retried job or repeated schedule
        await notify.emit(
            "quota.reached",
            org_id=org,
            recipients=[email, email.upper()],
            variables={"used": "10", "limit": "10"},
            dedupe_key="quota.reached:2026-11-01",
        )
    rows = await log_rows(org)
    assert len(rows) == 1 and rows[0]["status"] == "QUEUED"
    assert [d[0] for d in dev] == ["notify.deliver"] and dev[0][2] == "system"

    box = OutboxMailer()
    nid = (await sql("SELECT id FROM notification_log WHERE organization_id=$1", org))[0]["id"]
    assert await notify.deliver(org, nid, box) == "SENT"
    assert await notify.deliver(org, nid, box) == "SENT"  # redelivery of the task changes nothing
    assert len(box.sent) == 1 and box.sent[0].to == email.lower()
    assert "10 of 10" in box.sent[0].text
    row = (await log_rows(org))[0]
    assert row["status"] == "SENT" and row["subject"] == box.sent[0].subject


async def test_failed_sends_are_retried_then_marked_failed_and_never_resent(dev):
    org, user, email = await make_org()
    await notify.emit(
        "quota.reached",
        org_id=org,
        recipients=[email],
        variables={"used": "1", "limit": "1"},
        dedupe_key="k",
    )
    nid = (await sql("SELECT id FROM notification_log WHERE organization_id=$1", org))[0]["id"]
    for attempt in range(1, notify.MAX_ATTEMPTS):
        with pytest.raises(notify.DeliveryError):
            await notify.deliver(org, nid, Failing())
        assert (await log_rows(org))[0]["attempts"] == attempt and (await log_rows(org))[0][
            "status"
        ] == "QUEUED"
    assert await notify.deliver(org, nid, Failing()) == "FAILED"
    box = OutboxMailer()
    assert await notify.deliver(org, nid, box) == "FAILED" and box.sent == []
    assert (
        "ConnectionError"
        in (await sql("SELECT error FROM notification_log WHERE id=$1", nid))[0]["error"]
    )


async def test_a_switched_off_email_is_logged_not_sent(dev):
    org, user, email = await make_org()
    await save_templates([{"event": "quota.reached", "enabled": False}])
    await notify.emit(
        "quota.reached",
        org_id=org,
        recipients=[email],
        variables={"used": "1", "limit": "1"},
        dedupe_key="k",
    )
    assert (await log_rows(org))[0]["status"] == "SKIPPED" and dev == []
    # switched off AFTER it was queued
    await save_templates([], comment="test-on")
    await notify.emit(
        "quota.reached",
        org_id=org,
        recipients=[email],
        variables={"used": "1", "limit": "1"},
        dedupe_key="k2",
    )
    await save_templates([{"event": "quota.reached", "enabled": False}], comment="test-off")
    nid = (
        await sql(
            "SELECT id FROM notification_log WHERE organization_id=$1 AND dedupe_key='k2'", org
        )
    )[0]["id"]
    box = OutboxMailer()
    assert await notify.deliver(org, nid, box) == "SKIPPED" and box.sent == []


async def test_the_log_is_private_to_the_organisation_and_its_keys_cannot_be_edited():
    org, user, email = await make_org()
    org2, _, _ = await make_org()
    await notify.emit(
        "quota.reached",
        org_id=org,
        recipients=[email],
        variables={"used": "1", "limit": "1"},
        dedupe_key="k",
    )
    async with tenant_session(org2) as db:
        assert (await db.execute(text("SELECT count(*) FROM notification_log"))).scalar_one() == 0
    with pytest.raises(Exception, match="permission denied"):
        async with tenant_session(org) as db:
            await db.execute(text("UPDATE notification_log SET to_email='x@example.com'"))


# -- the product's triggers -----------------------------------------------------------------------
async def test_a_finished_scan_emails_the_person_who_started_it(client, site, dev):
    org, user, email = await make_org(plan="GROWTH")
    h = auth(org, user)
    sid = uuid.UUID((await create(client, h, f"{site}/bad.html")).json()["id"])
    dev.clear()
    assert await run_scan(org, sid, opts_override=FAST) == "SUCCEEDED"
    assert [d[0] for d in dev] == ["notify.deliver"]
    box = OutboxMailer()
    nid = (await sql("SELECT id FROM notification_log WHERE organization_id=$1", org))[0]["id"]
    await notify.deliver(org, nid, box)
    m = box.sent[0]
    assert m.to == email.lower() and f"{site}/bad.html" in m.subject
    assert "problems" in m.text and f"/workspace/scan?id={sid}" in m.text
    assert notify.check_email_html(m.html) == []
    assert (
        await run_scan(org, sid, opts_override=FAST) == "SUCCEEDED"
    )  # redelivered scan task: no second email
    assert len(await log_rows(org, "scan.completed")) == 1


async def test_a_failed_scan_says_whether_the_credit_came_back(client, site, dev):
    org, user, email = await make_org(plan="GROWTH")
    h = auth(org, user)
    ours = uuid.UUID((await create(client, h, f"{site}/good.html")).json()["id"])
    theirs = uuid.UUID((await create(client, h, f"{site}/good.html")).json()["id"])
    assert await fail_scan(
        org, ours, "worker_lost", "The scan worker stopped responding.", system_fault=True
    )
    assert await fail_scan(
        org, theirs, "timeout", "The page took too long to load.", system_fault=False
    )
    assert not await fail_scan(
        org, ours, "worker_lost", "again", system_fault=True
    )  # already finished: no second email
    box = OutboxMailer()
    for r in await sql(
        "SELECT id FROM notification_log WHERE organization_id=$1 ORDER BY created_at", org
    ):
        await notify.deliver(org, r["id"], box)
    assert len(box.sent) == 2
    texts = {("returned" in m.text): m.text for m in box.sent}
    assert (
        "stopped responding" in texts[True]
        and "took too long" in texts[False]
        and "was used" in texts[False]
    )


async def test_hitting_the_monthly_limit_emails_the_admins_once(client, site, dev):
    org, user, email = await make_org(plan="TRIAL", trial_days=5)
    h = auth(org, user)
    lim = (
        await sql(
            "SELECT limit_value FROM plan_entitlements WHERE plan_id='TRIAL' AND feature_key='urls_monthly'"
        )
    )[0]["limit_value"]
    async with tenant_session(org) as db:
        for i in range(lim):
            await billing.reserve(db, org, "urls_monthly", f"seed-{i}")
    for _ in range(3):
        assert (await create(client, h, f"{site}/good.html")).status_code == 402
    rows = await log_rows(org, "quota.reached")
    assert len(rows) == 1 and rows[0]["to_email"] == email.lower()  # three refusals, one email


async def test_trial_reminders_and_expiry_each_email_once(dev):
    ending, u1, e1 = await make_org(plan="TRIAL", trial_days=2)
    far, _, _ = await make_org(plan="TRIAL", trial_days=10)
    expired, u3, e3 = await make_org(plan="TRIAL", trial_days=-1)
    await send_trial_reminders()
    await send_trial_reminders()
    rows = await log_rows(ending, "trial.ending")
    assert (
        len(rows) == 1
        and rows[0]["to_email"] == e1.lower()
        and rows[0]["dedupe_key"] == "trial.ending:3"
    )
    assert await log_rows(far, "trial.ending") == []
    box = OutboxMailer()
    await notify.deliver(
        ending,
        (await sql("SELECT id FROM notification_log WHERE organization_id=$1", ending))[0]["id"],
        box,
    )
    assert "ends in 2 days" in box.sent[0].subject and "read-only" in box.sent[0].text

    await expire_trials()
    await expire_trials()
    got = await log_rows(expired, "trial.expired")
    assert len(got) == 1 and got[0]["to_email"] == e3.lower()
