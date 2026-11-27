import uuid

from a11y_core import notify
from a11y_core.config import get_config
from a11y_core.models import Role

from a11y_api.security import Principal, issue_access_token

from .conftest import make_org, sql, super_admin_headers
from .test_billing import auth
from .test_notifications import _clean, save_templates  # noqa: F401  (autouse cleanup)


def admin_with_email(email="ops@example.com"):
    tok, _ = issue_access_token(Principal(uuid.uuid4(), None, Role.SUPER_ADMIN, email=email))
    return {"authorization": f"Bearer {tok}"}


async def test_only_super_admins_can_use_it(client):
    org, user, _ = await make_org()
    for method, url in (
        ("get", "/admin/notifications/events"),
        ("get", "/admin/notifications/log"),
    ):
        assert (await getattr(client, method)(url, headers=auth(org, user))).status_code == 403
        assert (await getattr(client, method)(url)).status_code == 401
    for url in ("/admin/notifications/preview", "/admin/notifications/test"):
        assert (
            await client.post(url, headers=auth(org, user), json={"event": "quota.reached"})
        ).status_code == 403


async def test_events_lists_the_catalog_with_defaults_and_overrides(client):
    h = super_admin_headers()
    await save_templates([{"event": "quota.reached", "subject": "Out of scans", "enabled": True}])
    ev = {e["key"]: e for e in (await client.get("/admin/notifications/events", headers=h)).json()}
    assert set(ev) == set(notify.EVENTS) and len(ev) >= 9
    q = ev["quota.reached"]
    assert (
        q["edited"] is True and q["enabled"] is True and q["variables"].keys() == {"used", "limit"}
    )
    assert (
        q["default"]["subject"] == "You have used all your scans this month"
    )  # the built-in text stays visible
    assert ev["auth.reset_password"]["required"] is True and ev["scan.completed"]["edited"] is False


async def test_preview_renders_a_draft_without_saving_it(client):
    h = super_admin_headers()
    r = await client.post(
        "/admin/notifications/preview",
        headers=h,
        json={
            "event": "scan.completed",
            "subject": "All done: {url}",
            "action_label": "Open the results",
        },
    )
    assert r.status_code == 200
    b = r.json()
    assert b["subject"] == "All done: https://example.com/" and "Open the results" in b["html"]
    assert b["accessibility_problems"] == [] and "View the results" not in b["html"]
    saved = (await get_config().effective("notify.templates")).value.items
    assert saved == []  # nothing was stored


async def test_preview_refuses_what_saving_would_refuse(client):
    h = super_admin_headers()
    bad = await client.post(
        "/admin/notifications/preview",
        headers=h,
        json={"event": "scan.completed", "subject": "Hi {nope}"},
    )
    assert bad.status_code == 422 and "not available" in bad.json()["detail"]
    generic = await client.post(
        "/admin/notifications/preview",
        headers=h,
        json={"event": "scan.completed", "action_label": "click here"},
    )
    assert generic.status_code == 422
    assert (
        await client.post("/admin/notifications/preview", headers=h, json={"event": "nope"})
    ).status_code == 404


async def test_test_send_goes_only_to_the_admins_own_address_with_the_saved_wording(client, outbox):
    await save_templates([{"event": "quota.reached", "subject": "Out of scans"}])
    r = await client.post(
        "/admin/notifications/test", headers=admin_with_email(), json={"event": "quota.reached"}
    )
    assert r.status_code == 200 and r.json() == {"sent_to": "ops@example.com"}
    assert [(m.to, m.subject) for m in outbox.sent] == [("ops@example.com", "[Test] Out of scans")]
    assert (
        await client.post(
            "/admin/notifications/test",
            headers=super_admin_headers(),
            json={"event": "quota.reached"},
        )
    ).status_code == 422  # no address on the account
    await save_templates([{"event": "quota.reached", "enabled": False}], comment="test-off")
    off = await client.post(
        "/admin/notifications/test", headers=admin_with_email(), json={"event": "quota.reached"}
    )
    assert off.status_code == 409 and len(outbox.sent) == 1


async def test_the_delivery_log_is_visible_to_admins_and_audited(client):
    h = super_admin_headers()
    org, user, email = await make_org()
    await notify.emit(
        "quota.reached",
        org_id=org,
        recipients=[email],
        variables={"used": "1", "limit": "1"},
        dedupe_key="adm",
    )
    rows = (await client.get("/admin/notifications/log?limit=200", headers=h)).json()
    mine = [r for r in rows if r["to"] == email.lower()]
    assert (
        len(mine) == 1
        and mine[0]["state"] == "QUEUED"
        and mine[0]["label"] == "Monthly scan limit reached"
    )
    assert (
        await client.get("/admin/notifications/log?state=SENT&limit=200", headers=h)
    ).status_code == 200
    assert (await client.get("/admin/notifications/log?state=bogus", headers=h)).status_code == 422
    assert (
        await sql(
            "SELECT count(*) AS n FROM audit_log WHERE action='admin.read' AND detail->>'reason'='read notification log'"
        )
    )[0]["n"] >= 1
