# ruff: noqa: F811
"""In-app notifications and the per-person email opt-out."""

import uuid

import pytest
from a11y_core import notify
from a11y_core.config import Scope, get_config
from a11y_core.mail import OutboxMailer
from a11y_web_audit.tasks import run_scan

from .conftest import make_org, sql
from .test_billing import auth
from .test_reports_api import add_member
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


async def member_of(org):
    """A second person in the organisation: (user id, email)."""
    uid = await add_member(org)
    return uid, (await sql("SELECT email FROM users WHERE id=$1", uid))[0]["email"]


async def quota(org, emails, key="q"):
    return await notify.emit(
        "quota.reached",
        org_id=org,
        recipients=emails,
        variables={"used": "10", "limit": "10"},
        dedupe_key=key,
    )


async def test_an_event_creates_an_item_for_each_recipient_with_a_link(client, dev):
    org, admin, email = await make_org(plan="GROWTH")
    await quota(org, [email])
    got = (await client.get("/me/notifications", headers=auth(org, admin))).json()
    assert got["unread"] == 1 and len(got["items"]) == 1
    item = got["items"][0]
    assert item["title"] == "You have used all your scans this month" and "10 of 10" in item["body"]
    assert (
        item["link"] == "/org#plan" and item["read"] is False and item["event"] == "quota.reached"
    )


async def test_people_only_see_their_own_items_and_other_organisations_see_nothing(client, dev):
    org, admin, email = await make_org(plan="GROWTH")
    member, memail = await member_of(org)
    await quota(org, [email])  # only the administrator is a recipient
    assert (await client.get("/me/notifications", headers=auth(org, admin))).json()["unread"] == 1
    assert (
        await client.get("/me/notifications", headers=auth(org, member, "STANDARD_USER"))
    ).json() == {"unread": 0, "items": [], "next_before": None}
    other, ouser, _ = await make_org(plan="GROWTH")
    assert (await client.get("/me/notifications", headers=auth(other, ouser))).json()["items"] == []
    assert (await client.get("/me/notifications")).status_code == 401
    # nobody can mark someone else's item read
    nid = (await client.get("/me/notifications", headers=auth(org, admin))).json()["items"][0]["id"]
    after = await client.post(
        "/me/notifications/read", headers=auth(org, member, "STANDARD_USER"), json={"ids": [nid]}
    )
    assert (
        after.status_code == 200
        and (await client.get("/me/notifications", headers=auth(org, admin))).json()["unread"] == 1
    )


async def test_emitting_twice_gives_one_item_and_reading_updates_the_count(client, dev):
    org, admin, email = await make_org(plan="GROWTH")
    for _ in range(3):
        await quota(org, [email], key="same")
    await quota(org, [email], key="other")
    h = auth(org, admin)
    got = (await client.get("/me/notifications", headers=h)).json()
    assert got["unread"] == 2
    one = got["items"][0]["id"]
    assert (await client.post("/me/notifications/read", headers=h, json={"ids": [one]})).json() == {
        "unread": 1
    }
    assert (await client.post("/me/notifications/read", headers=h, json={"ids": [one]})).json() == {
        "unread": 1
    }  # idempotent
    only = (await client.get("/me/notifications?unread=true", headers=h)).json()
    assert len(only["items"]) == 1 and only["items"][0]["id"] != one
    assert (await client.post("/me/notifications/read", headers=h, json={"all": True})).json() == {
        "unread": 0
    }
    assert all(
        i["read"] for i in (await client.get("/me/notifications", headers=h)).json()["items"]
    )


async def test_pages_through_a_long_list_newest_first(client, dev):
    org, admin, email = await make_org(plan="GROWTH")
    for i in range(5):
        await quota(org, [email], key=f"k{i}")
    h = auth(org, admin)
    first = (await client.get("/me/notifications?limit=3", headers=h)).json()
    assert len(first["items"]) == 3 and first["next_before"] is not None
    rest = (
        await client.get(
            "/me/notifications", headers=h, params={"limit": 3, "before": first["next_before"]}
        )
    ).json()
    assert len(rest["items"]) == 2 and rest["next_before"] is None
    assert {i["id"] for i in first["items"]}.isdisjoint({i["id"] for i in rest["items"]})


async def test_the_admins_wording_is_used_for_the_item_too(client, dev):
    org, admin, email = await make_org(plan="GROWTH")
    await get_config().save(
        "notify.templates",
        Scope.GLOBAL,
        "",
        {
            "items": [
                {
                    "event": "quota.reached",
                    "subject": "Out of scans",
                    "intro": "Used {used} of {limit}.",
                }
            ]
        },
        comment="test-tpl",
        actor=None,
    )
    await quota(org, [email])
    item = (await client.get("/me/notifications", headers=auth(org, admin))).json()["items"][0]
    assert item["title"] == "Out of scans" and item["body"] == "Used 10 of 10."


async def test_a_switched_off_email_creates_no_item(client, dev):
    org, admin, email = await make_org(plan="GROWTH")
    await get_config().save(
        "notify.templates",
        Scope.GLOBAL,
        "",
        {"items": [{"event": "quota.reached", "enabled": False}]},
        comment="test-off",
        actor=None,
    )
    await quota(org, [email])
    assert (await client.get("/me/notifications", headers=auth(org, admin))).json()["items"] == []


async def test_the_centre_can_be_switched_off(client, dev):
    org, admin, email = await make_org(plan="GROWTH")
    await get_config().save(
        "flags", Scope.ORG, str(org), {"notification_center": False}, comment="test-fl", actor=None
    )
    await quota(org, [email])
    r = await client.get("/me/notifications", headers=auth(org, admin))
    assert r.status_code == 403 and r.json()["feature"] == "notification_center"
    assert (
        await sql("SELECT count(*) AS n FROM user_notifications WHERE organization_id=$1", org)
    )[0]["n"] == 0
    assert (await sql("SELECT count(*) AS n FROM notification_log WHERE organization_id=$1", org))[
        0
    ]["n"] == 1  # email still goes


async def test_preferences_default_on_and_only_optional_email_can_be_turned_off(client, dev):
    org, admin, email = await make_org(plan="GROWTH")
    h = auth(org, admin)
    assert (await client.get("/me/notification-preferences", headers=h)).json() == {
        "email_scan": True
    }
    assert (
        await client.put("/me/notification-preferences", headers=h, json={"email_scan": False})
    ).json() == {"email_scan": False}
    assert (await client.get("/me/notification-preferences", headers=h)).json() == {
        "email_scan": False
    }
    assert (
        await client.put("/me/notification-preferences", headers=h, json={"email_scan": "maybe"})
    ).status_code == 422
    # billing emails are not optional: the opt-out does not touch them
    await quota(org, [email])
    row = (
        await sql(
            "SELECT status FROM notification_log WHERE organization_id=$1 AND event='quota.reached'",
            org,
        )
    )[0]
    assert row["status"] == "QUEUED"


async def test_opting_out_stops_scan_emails_but_keeps_the_in_app_item(client, site, dev):
    org, user, email = await make_org(plan="GROWTH")
    h = auth(org, user)
    await client.put("/me/notification-preferences", headers=h, json={"email_scan": False})
    sid = uuid.UUID((await create(client, h, f"{site}/good.html")).json()["id"])
    await run_scan(org, sid, opts_override=FAST)
    row = (
        await sql(
            "SELECT status, error FROM notification_log WHERE organization_id=$1 AND event='scan.completed'",
            org,
        )
    )[0]
    assert row["status"] == "SKIPPED" and "chose not to get" in row["error"]
    box = OutboxMailer()
    nid = (await sql("SELECT id FROM notification_log WHERE organization_id=$1", org))[0]["id"]
    assert (
        await notify.deliver(org, nid, box) == "SKIPPED" and box.sent == []
    )  # nothing is ever sent
    item = (await client.get("/me/notifications", headers=h)).json()["items"][0]
    assert item["event"] == "scan.completed" and item["link"] == f"/workspace/scan?id={sid}"
    await client.put("/me/notification-preferences", headers=h, json={"email_scan": True})
    sid2 = uuid.UUID((await create(client, h, f"{site}/good.html")).json()["id"])
    await run_scan(org, sid2, opts_override=FAST)
    rows = await sql(
        "SELECT status FROM notification_log WHERE organization_id=$1 AND event='scan.completed' ORDER BY created_at",
        org,
    )
    assert [r["status"] for r in rows] == [
        "SKIPPED",
        "QUEUED",
    ]  # opting back in takes effect for the next scan


async def test_an_item_cannot_be_edited_only_marked_read(client, dev):
    org, admin, email = await make_org(plan="GROWTH")
    await quota(org, [email])
    from a11y_core.db import tenant_session
    from sqlalchemy import text

    with pytest.raises(Exception, match="permission denied"):
        async with tenant_session(org) as db:
            await db.execute(
                text("UPDATE user_notifications SET title='Your account is suspended: click here'")
            )
