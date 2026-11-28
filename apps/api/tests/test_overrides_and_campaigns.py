# ruff: noqa: F811
"""Per-organisation entitlement overrides and bulk coupon campaigns."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from a11y_core import billing
from a11y_core.ai import LLMGateway
from a11y_core.db import admin_session, tenant_session

from .conftest import make_org, sql, super_admin_headers
from .test_billing import auth, reserve
from .test_public_api import bearer, new_key


@pytest.fixture(autouse=True)
async def _clean():
    yield
    await sql(
        "DELETE FROM coupon_redemptions WHERE coupon_id IN (SELECT id FROM coupons WHERE campaign LIKE 'Tcamp%')"
    )
    await sql(
        "UPDATE subscriptions SET applied_coupon_id=NULL WHERE applied_coupon_id IN (SELECT id FROM coupons WHERE campaign LIKE 'Tcamp%')"
    )
    await sql("DELETE FROM coupons WHERE campaign LIKE 'Tcamp%'")


async def override(client, org, feature, **body):
    body = {"enabled": True, "reason": "negotiated with the customer", **body}
    return await client.put(
        f"/admin/tenants/{org}/overrides/{feature}", headers=super_admin_headers(), json=body
    )


# -- overrides --------------------------------------------------------------------------------------
async def test_only_platform_administrators_manage_overrides(client):
    org, user, _ = await make_org()
    for method, url, kw in (
        ("get", f"/admin/tenants/{org}/overrides", {}),
        ("put", f"/admin/tenants/{org}/overrides/seats", {"json": {"reason": "x"}}),
        ("delete", f"/admin/tenants/{org}/overrides/seats?reason=x", {}),
    ):
        assert (
            await getattr(client, method)(url, headers=auth(org, user), **kw)
        ).status_code == 403
        assert (await getattr(client, method)(url, **kw)).status_code == 401


async def test_a_raised_limit_applies_to_that_organisation_only(client):
    org, user, _ = await make_org(plan="TRIAL", trial_days=5)  # plan: 10 scans a month
    other, ouser, _ = await make_org(plan="TRIAL", trial_days=5)
    r = await override(client, org, "urls_monthly", limit_value=12)
    assert r.status_code == 200
    for i in range(12):
        await reserve(org, "urls_monthly", f"a{i}")
    with pytest.raises(billing.QuotaExceeded) as e:
        await reserve(org, "urls_monthly", "a12")
    assert e.value.extra["limit"] == 12
    for i in range(10):
        await reserve(other, "urls_monthly", f"b{i}")
    with pytest.raises(billing.QuotaExceeded) as e2:
        await reserve(other, "urls_monthly", "b10")
    assert e2.value.extra["limit"] == 10  # the neighbour on the same plan is untouched


async def test_an_override_can_lower_switch_off_or_open_up_a_feature(client):
    org, user, _ = await make_org(plan="GROWTH")
    # lower: only 1 scan this month
    await override(client, org, "urls_monthly", limit_value=1)
    await reserve(org, "urls_monthly", "x1")
    with pytest.raises(billing.QuotaExceeded):
        await reserve(org, "urls_monthly", "x2")
    # switch off API access although the plan includes it
    key = await new_key(client, org, user, ["scans:read"])
    assert (await client.get("/v1/me", headers=bearer(key["key"]))).status_code == 200
    await override(client, org, "api_access", enabled=False)
    off = await client.get("/v1/me", headers=bearer(key["key"]))
    assert off.status_code == 403 and off.json()["code"] == "api_not_in_plan"
    # open up a feature the plan does not have: own AI accounts on a non-Enterprise plan
    gw = LLMGateway()
    assert await gw.byok_entitled(org) is False
    await override(client, org, "byok_ai", enabled=True)
    assert await gw.byok_entitled(org) is True


async def test_seats_override_changes_the_seat_guard(client):
    org, user, _ = await make_org(plan="STARTER")  # 3 seats
    await override(client, org, "seats", limit_value=1)
    r = await client.post(
        "/invites",
        headers=auth(org, user),
        json={"email": f"x{uuid.uuid4().hex[:8]}@example.com", "role": "STANDARD_USER"},
    )
    assert r.status_code in (402, 409), r.text  # the one seat is taken
    await override(client, org, "seats", limit_value=None)  # unlimited
    assert (
        await client.post(
            "/invites",
            headers=auth(org, user),
            json={"email": f"y{uuid.uuid4().hex[:8]}@example.com", "role": "STANDARD_USER"},
        )
    ).status_code == 202


async def test_expiry_returns_the_plans_value_and_is_flagged(client):
    org, user, _ = await make_org(plan="TRIAL", trial_days=5)
    assert (
        await override(
            client,
            org,
            "urls_monthly",
            limit_value=500,
            expires_at=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
        )
    ).status_code == 200
    async with tenant_session(org) as db:
        sub = await billing.load_subscription(db)
        assert (await billing.entitlement(db, sub.plan_id, "urls_monthly")).limit == 500
    await sql(
        "UPDATE entitlement_overrides SET expires_at = now() - interval '1 minute' WHERE organization_id=$1",
        org,
    )  # time passes
    async with tenant_session(org) as db:
        e = await billing.entitlement(db, "TRIAL", "urls_monthly")
        assert (e.limit, e.custom) == (10, False)  # back to the plan, with no cron needed
    listed = (
        await client.get(f"/admin/tenants/{org}/overrides", headers=super_admin_headers())
    ).json()
    assert listed[0]["expired"] is True and listed[0]["reason"] == "negotiated with the customer"


async def test_the_organisations_plan_page_shows_a_custom_limit_and_any_opened_feature(client):
    org, user, _ = await make_org(plan="TRIAL", trial_days=5)
    await override(client, org, "urls_monthly", limit_value=77)
    await override(client, org, "byok_ai", enabled=True)  # a switch, not a meter
    meters = {
        m["feature"]: m
        for m in (await client.get("/org/subscription", headers=auth(org, user))).json()["quotas"]
    }
    assert meters["urls_monthly"]["limit"] == 77 and meters["urls_monthly"]["custom"] is True
    assert meters["ai_code_fixes_monthly"]["custom"] is False
    assert (
        "byok_ai" not in meters and "api_access" not in meters
    )  # switches are never shown as usage meters


async def test_validation_audit_and_removal(client):
    org, user, _ = await make_org(plan="GROWTH")
    h = super_admin_headers()
    assert (await override(client, org, "not_a_feature", limit_value=1)).status_code == 404
    assert (await override(client, uuid.uuid4(), "seats", limit_value=1)).status_code == 404
    assert (await override(client, org, "seats", limit_value=-1)).status_code == 422
    assert (
        await override(
            client,
            org,
            "seats",
            limit_value=1,
            expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        )
    ).status_code == 422
    assert (
        await client.put(
            f"/admin/tenants/{org}/overrides/seats",
            headers=h,
            json={"enabled": True, "limit_value": 1},
        )
    ).status_code == 422  # a reason is required
    await override(client, org, "seats", limit_value=2, reason="Pilot extension")
    actions = {
        r["action"] for r in await sql("SELECT action FROM audit_log WHERE organization_id=$1", org)
    }
    assert "entitlement.override_set" in actions  # the organisation's own log shows it too
    assert (
        await client.delete(f"/admin/tenants/{org}/overrides/seats", headers=h)
    ).status_code == 422  # reason required
    assert (
        await client.delete(f"/admin/tenants/{org}/overrides/seats?reason=Pilot%20ended", headers=h)
    ).status_code == 204
    assert (
        await client.delete(f"/admin/tenants/{org}/overrides/seats?reason=again", headers=h)
    ).status_code == 404
    assert "entitlement.override_removed" in {
        r["action"] for r in await sql("SELECT action FROM audit_log WHERE organization_id=$1", org)
    }


async def test_an_organisation_can_read_but_never_write_its_overrides(client):
    org, user, _ = await make_org(plan="GROWTH")
    await override(client, org, "seats", limit_value=2)
    from sqlalchemy import text

    async with tenant_session(org) as db:
        assert (
            await db.execute(text("SELECT count(*) FROM entitlement_overrides"))
        ).scalar_one() == 1
    for stmt in (
        "UPDATE entitlement_overrides SET limit_value = 100000",
        "DELETE FROM entitlement_overrides",
        f"INSERT INTO entitlement_overrides (organization_id, feature_key, enabled, reason) VALUES ('{org}', 'x', true, 'x')",
    ):
        with pytest.raises(Exception, match="permission denied"):
            async with tenant_session(org) as db:
                await db.execute(text(stmt))
    other, _, _ = await make_org(plan="GROWTH")
    async with tenant_session(other) as db:
        assert (
            await db.execute(text("SELECT count(*) FROM entitlement_overrides"))
        ).scalar_one() == 0


async def test_cross_tenant_admin_reads_do_not_pick_up_an_organisations_override(client):
    org, user, _ = await make_org(plan="TRIAL", trial_days=5)
    await override(client, org, "urls_monthly", limit_value=999)
    async with admin_session(actor_user_id=None, reason="test", action="admin.read") as db:
        assert (
            await billing.entitlement(db, "TRIAL", "urls_monthly")
        ).limit == 10  # no organisation context: the plan's value


# -- bulk coupon campaigns ----------------------------------------------------------------------------
BATCH = {
    "campaign": "Tcamp launch",
    "count": 25,
    "prefix": "TLAUNCH",
    "discount_type": "PERCENTAGE",
    "discount_value": 20,
    "max_redemptions": 1,
}


async def test_a_batch_makes_unique_unguessable_single_use_codes(client):
    h = super_admin_headers()
    r = await client.post("/admin/coupons/bulk", headers=h, json=BATCH)
    assert r.status_code == 201 and r.json()["count"] == 25
    codes = r.json()["codes"]
    assert len(set(codes)) == 25 and all(
        re.fullmatch(r"TLAUNCH-[A-HJ-NP-Z2-9]{8}", c) for c in codes
    )  # no 0, O, 1 or I to misread
    rows = await sql(
        "SELECT max_redemptions, discount_value, campaign, is_active FROM coupons WHERE campaign='Tcamp launch'"
    )
    assert len(rows) == 25 and {
        (r["max_redemptions"], r["discount_value"], r["campaign"], r["is_active"]) for r in rows
    } == {(1, 20, "Tcamp launch", True)}
    listed = (await client.get("/admin/coupons?campaign=Tcamp%20launch", headers=h)).json()
    assert len(listed) == 25 and all(c["campaign"] == "Tcamp launch" for c in listed)


async def test_batch_validation(client):
    h = super_admin_headers()
    for bad in (
        {"count": 0},
        {"count": 501},
        {"prefix": "lower"},
        {"prefix": "X"},
        {"campaign": "x"},
        {"discount_value": 101},
        {"discount_type": "BOGUS"},
    ):
        assert (
            await client.post("/admin/coupons/bulk", headers=h, json={**BATCH, **bad})
        ).status_code == 422, bad
    assert (
        await client.post("/admin/coupons/bulk", headers=h, json={**BATCH, "campaign": "Tcamp dup"})
    ).status_code == 201
    dup = await client.post(
        "/admin/coupons/bulk", headers=h, json={**BATCH, "campaign": "Tcamp dup"}
    )
    assert dup.status_code == 409 and dup.json()["field"] == "campaign"
    org, user, _ = await make_org()
    assert (
        await client.post("/admin/coupons/bulk", headers=auth(org, user), json=BATCH)
    ).status_code == 403


async def test_each_code_works_once_and_the_campaign_counts_redemptions(client):
    h = super_admin_headers()
    codes = (
        await client.post(
            "/admin/coupons/bulk", headers=h, json={**BATCH, "campaign": "Tcamp redeem", "count": 3}
        )
    ).json()["codes"]
    a, au, _ = await make_org(plan="STARTER")
    b, bu, _ = await make_org(plan="STARTER")
    ok = await client.post("/org/coupon", headers=auth(a, au), json={"code": codes[0].lower()})
    assert ok.status_code == 200
    reuse = await client.post(
        "/org/coupon", headers=auth(b, bu), json={"code": codes[0]}
    )  # single-use: already spent
    assert reuse.status_code in (409, 422) and "limit" in reuse.json()["detail"]
    assert (
        await client.post("/org/coupon", headers=auth(b, bu), json={"code": codes[1]})
    ).status_code == 200
    camp = {
        c["campaign"]: c for c in (await client.get("/admin/coupons-campaigns", headers=h)).json()
    }["Tcamp redeem"]
    assert (camp["codes"], camp["redeemed"], camp["active"]) == (3, 2, 3)


async def test_a_leaked_campaign_can_be_switched_off_at_once(client):
    h = super_admin_headers()
    codes = (
        await client.post(
            "/admin/coupons/bulk", headers=h, json={**BATCH, "campaign": "Tcamp leak", "count": 4}
        )
    ).json()["codes"]
    r = await client.post("/admin/coupons-campaigns/Tcamp%20leak/deactivate", headers=h)
    assert r.status_code == 200 and r.json() == {"deactivated": 4}
    org, user, _ = await make_org(plan="STARTER")
    bad = await client.post("/org/coupon", headers=auth(org, user), json={"code": codes[0]})
    assert bad.status_code in (409, 422)  # no longer a valid code
    assert (
        await client.post("/admin/coupons-campaigns/Tcamp%20leak/deactivate", headers=h)
    ).status_code == 404  # nothing left to switch off
