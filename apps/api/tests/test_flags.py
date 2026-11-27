# ruff: noqa: F811
"""Feature flags: switched off globally, per plan or per organisation, enforced on the server and visible to the UI."""

import pytest
from a11y_core import flags
from a11y_core.config import Scope, get_config

from .conftest import make_org, sql
from .test_billing import auth
from .test_public_api import org_with_key
from .test_reports_api import finished_scan
from .test_scans_api import _cfg_reset, dev, high_ports, site  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
async def _clean():
    async def wipe():
        await sql("DELETE FROM setting_versions WHERE comment LIKE 'test-%'")
        r = get_config()._r()
        for k in await r.keys("cfg:*") + await r.keys("rl:api:*"):
            await r.delete(k)

    await wipe()
    yield
    await wipe()


async def set_flags(scope, scope_id, **values):
    await get_config().save("flags", scope, scope_id, values, comment="test-flag", actor=None)


async def test_every_flag_defaults_to_on_and_scopes_override_in_order():
    org, user, _ = await make_org(plan="GROWTH")
    assert (await flags.effective_flags(org, "GROWTH")).model_dump() == dict.fromkeys(
        flags.FeatureFlags.model_fields, True
    )
    await set_flags(Scope.GLOBAL, "", vpat=False)
    assert not await flags.enabled("vpat", org_id=org, plan_id="GROWTH")
    await set_flags(
        Scope.ORG, str(org), vpat=True
    )  # a negotiated exception for one organisation wins
    assert await flags.enabled("vpat", org_id=org, plan_id="GROWTH")
    other, _, _ = await make_org(plan="GROWTH")
    assert not await flags.enabled("vpat", org_id=other, plan_id="GROWTH")


async def test_the_organisation_can_see_which_features_are_on(client):
    org, user, _ = await make_org(plan="GROWTH")
    await set_flags(Scope.ORG, str(org), crawl_scans=False)
    got = (await client.get("/org/flags", headers=auth(org, user))).json()
    assert got["crawl_scans"] is False and got["public_api"] is True
    assert (await client.get("/org/flags")).status_code == 401


async def test_crawl_scans_can_be_switched_off_but_single_page_scans_still_work(client, site, dev):
    org, user, _ = await make_org(plan="GROWTH")
    await set_flags(Scope.ORG, str(org), crawl_scans=False)
    h = auth(org, user)
    r = await client.post(
        "/scans", headers=h, json={"url": f"{site}/", "mode": "crawl", "max_pages": 3}
    )
    assert (
        r.status_code == 403
        and r.json()["code"] == "feature_disabled"
        and r.json()["feature"] == "crawl_scans"
    )
    assert (
        await client.post("/scans", headers=h, json={"url": f"{site}/good.html"})
    ).status_code == 202


async def test_switching_the_public_api_off_stops_keys_at_once_and_blocks_new_ones(client):
    org, user, k, h = await org_with_key(client)
    assert (await client.get("/v1/me", headers=h)).status_code == 200
    await set_flags(Scope.PLAN, "GROWTH", public_api=False)
    r = await client.get("/v1/me", headers=h)
    assert (
        r.status_code == 503
        and r.json()["code"] == "feature_disabled"
        and r.headers["retry-after"] == "300"
    )
    made = await client.post(
        "/org/api-keys", headers=auth(org, user), json={"name": "x", "scopes": ["scans:read"]}
    )
    assert made.status_code == 403 and made.json()["feature"] == "public_api"
    await sql("DELETE FROM setting_versions WHERE comment LIKE 'test-%'")
    r2 = get_config()._r()
    for key in await r2.keys("cfg:*"):
        await r2.delete(key)
    assert (
        await client.get("/v1/me", headers=h)
    ).status_code == 200  # back on: the same key works again


async def test_vpat_can_be_switched_off(client, site, dev):
    org, user, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    await set_flags(Scope.GLOBAL, "", vpat=False)
    r = await client.post(
        f"/scans/{sid}/vpat",
        headers=h,
        json={"standard": "WCAG_2_2_AA", "edition": "WCAG", "product": {}},
    )
    assert r.status_code == 403 and r.json()["feature"] == "vpat"
    assert (
        await client.post(f"/scans/{sid}/reports", headers=h, json={"kind": "audit_csv"})
    ).status_code == 202  # reports are unaffected


async def test_flags_appear_in_the_admin_settings_with_all_three_scopes(client):
    from .conftest import super_admin_headers

    defs = {
        d["key"]: d
        for d in (await client.get("/admin/settings", headers=super_admin_headers())).json()
    }
    assert set(defs["flags"]["scopes"]) == {"global", "plan", "org"}
    assert set(defs["flags"]["schema"]["properties"]) == set(flags.FeatureFlags.model_fields)
