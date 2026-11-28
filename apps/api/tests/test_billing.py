"""SaaS core: trial, seats, quota reservations, coupons - including races."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from a11y_core import billing
from a11y_core.db import tenant_session

from a11y_api.security import Principal, issue_access_token

from .conftest import TEST_PREFIX, make_org, sql


def auth(org, user, role="COMPANY_ADMIN"):
    tok, _ = issue_access_token(Principal(user, org, role))
    return {"authorization": f"Bearer {tok}"}


async def reserve(org, feature, job, n=1):
    async with tenant_session(org) as db:
        return await billing.reserve(db, org, feature, job, n)


async def used(org, feature="urls_monthly"):
    rows = await sql(
        "SELECT used FROM usage_ledger WHERE organization_id=$1 AND feature_key=$2", org, feature
    )
    return rows[0]["used"] if rows else 0


# --- trial ------------------------------------------------------------------------------------


async def test_signup_starts_a_14_day_trial(client, outbox):
    r = await client.post(
        "/auth/signup",
        json={
            "organization_name": f"{TEST_PREFIX}trial",
            "email": f"t{uuid.uuid4().hex[:8]}@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert r.status_code == 202
    rows = await sql(
        "SELECT s.plan_id, s.status, s.trial_ends_at - s.created_at AS len FROM subscriptions s "
        "JOIN organizations o ON o.id = s.organization_id WHERE o.name = $1",
        f"{TEST_PREFIX}trial",
    )
    assert (rows[0]["plan_id"], rows[0]["status"]) == ("TRIAL", "TRIALING")
    assert timedelta(days=13, hours=23) < rows[0]["len"] < timedelta(days=14, minutes=1)


async def test_expired_trial_is_locked_by_the_guard_without_any_cron_run():
    org, user, _ = await make_org(
        plan="TRIAL", trial_days=-1
    )  # ended yesterday, still TRIALING in the DB
    assert (await sql("SELECT status FROM subscriptions WHERE organization_id=$1", org))[0][
        "status"
    ] == "TRIALING"
    with pytest.raises(billing.SubscriptionLocked):
        await reserve(org, "urls_monthly", "j1")


async def test_active_trial_allows_work():
    org, *_ = await make_org(plan="TRIAL", trial_days=5)
    assert (await reserve(org, "urls_monthly", "j1")).created


async def test_expire_trials_job_persists_the_lock_and_is_idempotent():
    from a11y_core.billing_jobs import expire_trials

    expired, _, _ = await make_org(plan="TRIAL", trial_days=-2)
    fresh, _, _ = await make_org(plan="TRIAL", trial_days=3)
    active, _, _ = await make_org(plan="GROWTH")
    await expire_trials()
    assert await expire_trials() == 0  # second run: nothing left to do
    st = {
        r["organization_id"]: r["status"]
        for r in await sql("SELECT organization_id, status FROM subscriptions")
    }
    assert (st[expired], st[fresh], st[active]) == ("LOCKED_READ_ONLY", "TRIALING", "ACTIVE")


async def test_locked_org_cannot_invite_but_can_read(client):
    org, user, _ = await make_org(plan="TRIAL", trial_days=-1)
    h = auth(org, user)
    r = await client.post("/invites", headers=h, json={"email": "x@example.com"})
    assert r.status_code == 403 and r.json()["code"] == "subscription_locked"
    assert (await client.get("/me", headers=h)).status_code == 200
    s = (await client.get("/org/subscription", headers=h)).json()
    assert s["status"] == "LOCKED_READ_ONLY"


# --- seats ------------------------------------------------------------------------------------


async def test_seat_limit_blocks_invites_with_structured_upgrade_prompt(client, outbox):
    org, user, _ = await make_org(plan="STARTER")  # 3 seats; admin takes 1
    h = auth(org, user)
    for i in range(2):
        assert (
            await client.post(
                "/invites", headers=h, json={"email": f"s{i}{uuid.uuid4().hex[:6]}@example.com"}
            )
        ).status_code == 202
    r = await client.post(
        "/invites", headers=h, json={"email": f"s3{uuid.uuid4().hex[:6]}@example.com"}
    )
    assert r.status_code == 402
    assert r.json() == {
        "detail": "All 3 seats are in use. Upgrade your plan to add more people.",
        "code": "seat_limit_reached",
        "used": 3,
        "limit": 3,
        "upgrade_url": "/org#plan",
    }
    s = (await client.get("/org/subscription", headers=h)).json()
    assert s["seats"] == {"used": 3, "limit": 3}


async def test_concurrent_invites_cannot_exceed_the_seat_limit(client, outbox):
    org, user, _ = await make_org(plan="STARTER")  # 3 seats, 1 used -> room for exactly 2
    h = auth(org, user)
    rs = await asyncio.gather(
        *[
            client.post(
                "/invites", headers=h, json={"email": f"c{i}{uuid.uuid4().hex[:6]}@example.com"}
            )
            for i in range(8)
        ]
    )
    codes = sorted(r.status_code for r in rs)
    assert codes == [202, 202] + [402] * 6
    open_invites = await sql(
        "SELECT count(*) AS n FROM auth_tokens WHERE organization_id=$1 AND kind='INVITE'", org
    )
    assert open_invites[0]["n"] == 2


async def test_unlimited_plan_has_no_seat_cap(client, outbox):
    org, user, _ = await make_org(plan="ENTERPRISE")
    h = auth(org, user)
    for i in range(5):
        assert (
            await client.post(
                "/invites", headers=h, json={"email": f"e{i}{uuid.uuid4().hex[:6]}@example.com"}
            )
        ).status_code == 202
    assert (await client.get("/org/subscription", headers=h)).json()["seats"]["limit"] is None


async def test_accepting_an_invite_rechecks_the_limit_after_a_downgrade(client, outbox):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    email = f"d{uuid.uuid4().hex[:6]}@example.com"
    assert (await client.post("/invites", headers=h, json={"email": email})).status_code == 202
    from .test_auth import _token

    raw = _token(outbox, email)
    # Admin moves the org to a 1-seat plan while the invite is open.
    await sql("INSERT INTO plans (id, name) VALUES ('ONESEAT', 'One') ON CONFLICT DO NOTHING")
    await sql(
        "INSERT INTO plan_entitlements (plan_id, feature_key, limit_value) VALUES ('ONESEAT','seats',1) ON CONFLICT DO NOTHING"
    )
    await sql("UPDATE subscriptions SET plan_id='ONESEAT' WHERE organization_id=$1", org)
    try:
        r = await client.post(
            "/invites/accept", json={"token": raw, "password": "correct horse battery staple"}
        )
        assert r.status_code == 402 and r.json()["code"] == "seat_limit_reached"
    finally:
        await sql("UPDATE subscriptions SET plan_id='GROWTH' WHERE organization_id=$1", org)
        await sql("DELETE FROM plans WHERE id='ONESEAT'")


# --- quota reservations ----------------------------------------------------------------------


async def test_reservation_is_idempotent_per_job():
    org, *_ = await make_org(plan="TRIAL", trial_days=5)  # 10 urls/month
    a = await reserve(org, "urls_monthly", "job-1")
    b = await reserve(org, "urls_monthly", "job-1")  # worker retry
    assert (a.created, b.created) == (True, False)
    assert await used(org) == 1


async def test_cannot_overspend_under_parallel_reservations():
    org, *_ = await make_org(plan="TRIAL", trial_days=5)  # limit 10
    results = await asyncio.gather(
        *[reserve(org, "urls_monthly", f"job-{i}") for i in range(40)], return_exceptions=True
    )
    ok = [r for r in results if not isinstance(r, Exception)]
    denied = [r for r in results if isinstance(r, billing.QuotaExceeded)]
    assert len(ok) == 10 and len(denied) == 30
    assert await used(org) == 10
    # failed attempts left no reservation rows behind
    n = await sql("SELECT count(*) AS n FROM usage_reservations WHERE organization_id=$1", org)
    assert n[0]["n"] == 10


async def test_release_returns_credit_commit_keeps_it_and_both_are_idempotent():
    org, *_ = await make_org(plan="TRIAL", trial_days=5)
    for j in ("sys-fail", "user-fail"):
        await reserve(org, "urls_monthly", j)
    async with tenant_session(org) as db:
        assert await billing.release_usage(db, "urls_monthly", "sys-fail") is True
        assert (
            await billing.release_usage(db, "urls_monthly", "sys-fail") is False
        )  # no double refund
        assert await billing.commit_usage(db, "urls_monthly", "user-fail") is True
        assert (
            await billing.release_usage(db, "urls_monthly", "user-fail") is False
        )  # committed is final
    assert await used(org) == 1


async def test_freed_credit_can_be_used_again():
    org, *_ = await make_org(plan="TRIAL", trial_days=5)
    for i in range(10):
        await reserve(org, "urls_monthly", f"j{i}")
    with pytest.raises(billing.QuotaExceeded):
        await reserve(org, "urls_monthly", "j-over")
    async with tenant_session(org) as db:
        await billing.release_usage(db, "urls_monthly", "j3")
    assert (await reserve(org, "urls_monthly", "j-again")).created


async def test_unlimited_and_missing_entitlements():
    ent, *_ = await make_org(plan="ENTERPRISE")
    await asyncio.gather(*[reserve(ent, "urls_monthly", f"j{i}") for i in range(20)])
    org, *_ = await make_org(plan="STARTER")
    with pytest.raises(billing.QuotaExceeded) as e:
        await reserve(org, "video_mins_monthly", "j1")  # not on the plan
    assert e.value.body()["code"] == "quota_exceeded"


async def test_quota_error_body_has_upgrade_prompt():
    org, *_ = await make_org(plan="TRIAL", trial_days=5)
    for i in range(10):
        await reserve(org, "urls_monthly", f"j{i}")
    with pytest.raises(billing.QuotaExceeded) as e:
        await reserve(org, "urls_monthly", "x")
    b = e.value.body()
    assert (b["used"], b["limit"], b["upgrade_url"]) == (10, 10, "/org#plan")


async def test_usage_is_per_organisation_and_per_month():
    a, *_ = await make_org(plan="TRIAL", trial_days=5)
    b, *_ = await make_org(plan="TRIAL", trial_days=5)
    for i in range(10):
        await reserve(a, "urls_monthly", f"j{i}")
    assert (await reserve(b, "urls_monthly", "j0")).created
    async with tenant_session(a) as db:
        nxt = datetime.now(UTC).replace(day=28) + timedelta(days=10)  # next month: fresh ledger
        assert (await billing.reserve(db, a, "urls_monthly", "next", now=nxt)).created


# --- coupons ----------------------------------------------------------------------------------


async def make_coupon(**kw) -> str:
    code = kw.pop("code", f"T{uuid.uuid4().hex[:8]}").upper()
    cols = {"code": code, "discount_type": "PERCENTAGE", "discount_value": 20, **kw}
    names = ", ".join(cols)
    ph = ", ".join(f"${i + 1}" for i in range(len(cols)))
    await sql(f"INSERT INTO coupons (id, {names}) VALUES (gen_random_uuid(), {ph})", *cols.values())
    return code


@pytest.fixture(autouse=True)
async def _coupon_cleanup():
    yield
    await sql(
        "DELETE FROM coupon_redemptions WHERE coupon_id IN (SELECT id FROM coupons WHERE code LIKE 'T%')"
    )
    await sql(
        "UPDATE subscriptions SET applied_coupon_id=NULL WHERE applied_coupon_id IN (SELECT id FROM coupons WHERE code LIKE 'T%')"
    )
    await sql("DELETE FROM coupons WHERE code LIKE 'T%'")


async def test_redeem_applies_coupon_and_is_case_and_space_insensitive(client):
    code = await make_coupon()
    org, user, _ = await make_org()
    r = await client.post(
        "/org/coupon",
        headers=auth(org, user),
        json={"code": f" {code.lower()[:4]} {code.lower()[4:]} "},
    )
    assert r.status_code == 200 and r.json()["applied"] == {
        "code": code,
        "type": "PERCENTAGE",
        "value": 20,
    }
    s = (await client.get("/org/subscription", headers=auth(org, user))).json()
    assert s["coupon"]["code"] == code
    again = await client.post("/org/coupon", headers=auth(org, user), json={"code": code})
    assert again.status_code == 422 and again.json()["field"] == "code"


async def test_coupon_max_redemptions_holds_under_concurrent_checkouts(client):
    code = await make_coupon(max_redemptions=3)
    orgs = [await make_org() for _ in range(12)]
    rs = await asyncio.gather(
        *[client.post("/org/coupon", headers=auth(o, u), json={"code": code}) for o, u, _ in orgs]
    )
    assert sorted(r.status_code for r in rs) == [200] * 3 + [422] * 9
    row = (await sql("SELECT current_redemptions FROM coupons WHERE code=$1", code))[0]
    assert row["current_redemptions"] == 3
    n = (
        await sql(
            "SELECT count(*) AS n FROM coupon_redemptions r JOIN coupons c ON c.id=r.coupon_id WHERE c.code=$1",
            code,
        )
    )[0]
    assert n["n"] == 3


@pytest.mark.parametrize(
    "kw,msg",
    [
        ({"is_active": False}, "not valid"),
        ({"valid_until": datetime.now(UTC) - timedelta(days=1)}, "expired"),
        ({"valid_from": datetime.now(UTC) + timedelta(days=1)}, "not valid yet"),
        ({"applicable_plan_ids": ["ENTERPRISE"]}, "does not apply"),
    ],
)
async def test_invalid_coupons_are_rejected_and_do_not_burn_a_redemption(client, kw, msg):
    code = await make_coupon(**kw)
    org, user, _ = await make_org(plan="GROWTH")
    r = await client.post("/org/coupon", headers=auth(org, user), json={"code": code})
    assert r.status_code == 422 and msg in r.json()["detail"]
    assert (await sql("SELECT current_redemptions FROM coupons WHERE code=$1", code))[0][
        "current_redemptions"
    ] == 0


async def test_unknown_coupon_and_non_admin(client):
    org, user, _ = await make_org()
    r = await client.post("/org/coupon", headers=auth(org, user), json={"code": "NOPE-NOPE"})
    assert r.status_code == 422
    member, muser, _ = await make_org(role="STANDARD_USER")
    r = await client.post(
        "/org/coupon", headers=auth(member, muser, "STANDARD_USER"), json={"code": "X"}
    )
    assert r.status_code == 403


# --- privileges -------------------------------------------------------------------------------


async def test_tenant_cannot_change_its_plan_or_edit_catalogue_or_coupons():
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    org, *_ = await make_org(plan="TRIAL", trial_days=5)
    for stmt in (
        "UPDATE subscriptions SET plan_id='ENTERPRISE'",
        "UPDATE plan_entitlements SET limit_value = NULL",
        "INSERT INTO plans (id, name) VALUES ('HACK','h')",
        "UPDATE coupons SET discount_value = 100",
        "INSERT INTO coupons (id, code, discount_type, discount_value) VALUES (gen_random_uuid(),'THACK','PERCENTAGE',100)",
        "DELETE FROM coupon_redemptions",
        "UPDATE usage_reservations SET amount = 1",
    ):
        with pytest.raises(DBAPIError):
            async with tenant_session(org) as db:
                await db.execute(text(stmt))


async def test_tenants_cannot_see_each_others_billing_rows():
    from sqlalchemy import text

    a, *_ = await make_org(plan="TRIAL", trial_days=5)
    b, *_ = await make_org(plan="TRIAL", trial_days=5)
    await reserve(b, "urls_monthly", "b-job")
    async with tenant_session(a) as db:
        for t in ("subscriptions", "usage_ledger", "usage_reservations", "coupon_redemptions"):
            rows = (await db.execute(text(f"SELECT organization_id FROM {t}"))).all()
            assert all(r.organization_id == a for r in rows), t
