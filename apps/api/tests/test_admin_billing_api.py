import uuid

from .conftest import TEST_PREFIX, make_org, sql, super_admin_headers
from .test_billing import _coupon_cleanup, auth, reserve  # noqa: F401  (autouse cleanup)


async def test_admin_endpoints_reject_tenants(client):
    org, user, _ = await make_org()
    for method, url in (
        ("get", "/admin/plans"),
        ("get", "/admin/tenants"),
        ("get", "/admin/coupons"),
        ("get", "/admin/trial-funnel"),
    ):
        assert (await getattr(client, method)(url, headers=auth(org, user))).status_code == 403
        assert (await getattr(client, method)(url)).status_code == 401


async def test_plan_crud_and_launch_plans_present(client):
    h = super_admin_headers()
    plans = {p["id"]: p for p in (await client.get("/admin/plans", headers=h)).json()}
    assert {"TRIAL", "STARTER", "GROWTH", "ENTERPRISE"} <= set(plans)
    assert {e["feature_key"]: e["limit_value"] for e in plans["GROWTH"]["entitlements"]}[
        "seats"
    ] == 10
    body = {
        "name": "Test",
        "comment": "test-plan",
        "entitlements": [
            {"feature_key": "seats", "limit_value": 5},
            {"feature_key": "new_quota_no_migration", "limit_value": 7},
        ],
        "prices": [{"currency": "INR", "cycle": "MONTHLY", "amount_minor": 499900}],
    }
    try:
        r = await client.put("/admin/plans/ZTEST", headers=h, json=body)
        assert r.status_code == 200 and r.json()["prices"][0]["amount_minor"] == 499900
        # a brand-new feature key needs no schema change
        assert {e["feature_key"] for e in r.json()["entitlements"]} == {
            "seats",
            "new_quota_no_migration",
        }
        bad = await client.put("/admin/plans/lower", headers=h, json=body)
        assert bad.status_code == 422
    finally:
        await sql("DELETE FROM plans WHERE id='ZTEST'")


async def test_cannot_lower_a_limit_below_usage_without_confirmation(client):
    h = super_admin_headers()
    await sql("INSERT INTO plans (id, name) VALUES ('ZLOW','Low')")
    await sql(
        "INSERT INTO plan_entitlements (plan_id, feature_key, limit_value) VALUES ('ZLOW','urls_monthly',50)"
    )
    try:
        org, *_ = await make_org(plan="ZLOW")
        for i in range(8):
            await reserve(org, "urls_monthly", f"j{i}")
        body = {
            "name": "Low",
            "comment": "test-lower",
            "entitlements": [{"feature_key": "urls_monthly", "limit_value": 5}],
        }
        r = await client.put("/admin/plans/ZLOW", headers=h, json=body)
        assert r.status_code == 409 and r.json()["code"] == "limit_below_usage"
        assert r.json()["affected"][0] == {
            "organization_id": str(org),
            "feature": "urls_monthly",
            "used": 8,
            "new_limit": 5,
        }
        assert (await sql("SELECT limit_value FROM plan_entitlements WHERE plan_id='ZLOW'"))[0][
            "limit_value"
        ] == 50  # unchanged
        ok = await client.put(
            "/admin/plans/ZLOW", headers=h, json={**body, "confirm_below_usage": True}
        )
        assert ok.status_code == 200
    finally:
        await sql("DELETE FROM subscriptions WHERE plan_id='ZLOW'")
        await sql("DELETE FROM plans WHERE id='ZLOW'")


async def test_coupon_admin_lifecycle(client):
    h = super_admin_headers()
    code = f"TADM{uuid.uuid4().hex[:6]}".upper()
    r = await client.post(
        "/admin/coupons",
        headers=h,
        json={
            "code": code.lower(),
            "discount_type": "PERCENTAGE",
            "discount_value": 25,
            "max_redemptions": 2,
        },
    )
    assert r.status_code == 201 and r.json()["code"] == code  # stored upper-case
    assert (
        await client.post(
            "/admin/coupons",
            headers=h,
            json={"code": code, "discount_type": "PERCENTAGE", "discount_value": 25},
        )
    ).status_code == 409
    assert (
        await client.post(
            "/admin/coupons",
            headers=h,
            json={"code": "TOVER100", "discount_type": "PERCENTAGE", "discount_value": 150},
        )
    ).status_code == 422
    cid = r.json()["id"]
    org, user, _ = await make_org()
    assert (
        await client.post("/org/coupon", headers=auth(org, user), json={"code": code})
    ).status_code == 200
    low = await client.patch(f"/admin/coupons/{cid}", headers=h, json={"max_redemptions": 1})
    assert low.status_code == 200  # == current redemptions is fine
    assert (
        await client.patch(f"/admin/coupons/{cid}", headers=h, json={"is_active": False})
    ).json()["is_active"] is False
    other, ouser, _ = await make_org()
    off = await client.post("/org/coupon", headers=auth(other, ouser), json={"code": code})
    assert off.status_code == 422


async def test_directory_manual_assignment_and_funnel(client):
    h = super_admin_headers()
    org, user, _ = await make_org(plan="TRIAL", trial_days=-1, name=f"{TEST_PREFIX}dir")
    d = {t["id"]: t for t in (await client.get("/admin/tenants", headers=h)).json()}
    assert d[str(org)]["status"] == "LOCKED_READ_ONLY" and d[str(org)]["plan_id"] == "TRIAL"
    r = await client.post(
        f"/admin/tenants/{org}/plan",
        headers=h,
        json={"plan_id": "GROWTH", "comment": "test-invoice #42 paid"},
    )
    assert r.status_code == 200 and r.json()["status"] == "ACTIVE"
    # now writable again
    assert (
        await client.post(
            "/invites",
            headers=auth(org, user),
            json={"email": f"z{uuid.uuid4().hex[:6]}@example.com"},
        )
    ).status_code == 202
    bad = await client.post(
        f"/admin/tenants/{org}/plan", headers=h, json={"plan_id": "NOPE", "comment": "test-x"}
    )
    assert bad.status_code == 422
    assert (
        await client.post(
            f"/admin/tenants/{uuid.uuid4()}/plan",
            headers=h,
            json={"plan_id": "GROWTH", "comment": "test-x"},
        )
    ).status_code == 404
    f = (await client.get("/admin/trial-funnel", headers=h)).json()
    assert f["by_status"].get("ACTIVE", 0) >= 1
    audit = await sql(
        "SELECT detail->>'comment' AS c FROM audit_log WHERE organization_id=$1 AND action='tenant.plan_assigned'",
        org,
    )
    assert [a["c"] for a in audit] == ["test-invoice #42 paid"]
