# ruff: noqa: F811
"""The public API (/v1): API keys, authentication, scopes, limits, idempotency and the real end-to-end flow."""

import csv
import io
import uuid

import pytest
from a11y_core import api_keys
from a11y_core.config import Scope, get_config
from a11y_documents.tasks import render_report
from a11y_web_audit.tasks import run_scan

from .conftest import make_org, sql
from .test_billing import auth
from .test_scans_api import FAST, _cfg_reset, dev, high_ports, site  # noqa: F401  (fixtures)

ALL = ["scans:read", "scans:write", "reports:read", "reports:write", "audit:read"]


@pytest.fixture(autouse=True)
async def _clean():
    async def wipe():
        await sql("DELETE FROM setting_versions WHERE comment LIKE 'test-%'")
        r = get_config()._r()
        for k in await r.keys("cfg:*"):
            await r.delete(k)
        for k in await r.keys("rl:api:*") + await r.keys("idem:*"):
            await r.delete(k)

    await wipe()
    yield
    await wipe()


async def new_key(client, org, user, scopes=None, name="CI", **kw):
    r = await client.post(
        "/org/api-keys", headers=auth(org, user), json={"name": name, "scopes": scopes or ALL, **kw}
    )
    assert r.status_code == 201, r.text
    return r.json()


def bearer(key):
    return {"authorization": f"Bearer {key}"}


async def org_with_key(client, scopes=None, plan="GROWTH"):
    org, user, email = await make_org(plan=plan)
    k = await new_key(client, org, user, scopes)
    return org, user, k, bearer(k["key"])


# -- key management -------------------------------------------------------------------------------
async def test_a_key_is_shown_once_and_only_its_hash_is_stored(client):
    org, user, _ = await make_org(plan="GROWTH")
    k = await new_key(client, org, user)
    assert k["key"].startswith(f"a11y_{org.hex}_") and "only once" in k["notice"]
    listed = (await client.get("/org/api-keys", headers=auth(org, user))).json()
    assert "key" not in listed["keys"][0] and listed["keys"][0]["hint"] == k["key"][-4:]
    stored = (await sql("SELECT key_hash FROM api_keys WHERE organization_id=$1", org))[0][
        "key_hash"
    ]
    assert stored == api_keys.hash_key(k["key"]) and k["key"] not in stored and len(stored) == 64
    with pytest.raises(Exception, match="permission denied"):  # identity and scopes are immutable
        from a11y_core.db import tenant_session
        from sqlalchemy import text

        async with tenant_session(org) as db:
            await db.execute(text("UPDATE api_keys SET scopes = ARRAY['scans:write']"))


async def test_only_organisation_administrators_manage_keys(client):
    org, admin, _ = await make_org(plan="GROWTH")
    member, _, _ = await make_org(plan="GROWTH")
    from .test_reports_api import add_member

    uid = await add_member(org)
    assert (
        await client.get("/org/api-keys", headers=auth(org, uid, "STANDARD_USER"))
    ).status_code == 403
    assert (
        await client.post(
            "/org/api-keys",
            headers=auth(org, uid, "STANDARD_USER"),
            json={"name": "x", "scopes": ["scans:read"]},
        )
    ).status_code == 403
    assert (await client.get("/org/api-keys")).status_code == 401


async def test_creation_is_validated_limited_and_audited(client):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    assert (
        await client.post(
            "/org/api-keys", headers=h, json={"name": "x", "scopes": ["admin:everything"]}
        )
    ).status_code == 422
    assert (
        await client.post("/org/api-keys", headers=h, json={"name": "x", "scopes": []})
    ).status_code == 422
    await get_config().save(
        "api.limits",
        Scope.ORG,
        str(org),
        {"max_keys_per_org": 2, "max_key_lifetime_days": 30},
        comment="test-lim",
        actor=None,
    )
    k1 = await new_key(client, org, user, ["scans:read"], name="one")
    assert k1["expires_at"] is not None  # the cap makes a key expiring even when none was asked for
    await new_key(client, org, user, ["scans:read"], name="two", expires_in_days=7)
    over = await client.post(
        "/org/api-keys", headers=h, json={"name": "3", "scopes": ["scans:read"]}
    )
    assert over.status_code == 409 and over.json()["code"] == "too_many_keys"
    assert (await client.delete(f"/org/api-keys/{k1['id']}", headers=h)).status_code == 204
    assert (
        await client.delete(f"/org/api-keys/{k1['id']}", headers=h)
    ).status_code == 204  # idempotent
    await new_key(client, org, user, ["scans:read"], name="three")  # a revoked key frees a slot
    toolong = await client.post(
        "/org/api-keys",
        headers=h,
        json={"name": "t", "scopes": ["scans:read"], "expires_in_days": 90},
    )
    assert toolong.status_code in (409, 422)
    actions = [
        r["action"]
        for r in await sql(
            "SELECT action FROM audit_log WHERE organization_id=$1 AND action LIKE 'api_key.%' ORDER BY created_at",
            org,
        )
    ]
    assert (
        actions.count("api_key.create") == 3 and actions.count("api_key.revoke") == 1
    )  # the second delete wrote nothing


async def test_a_plan_without_api_access_cannot_create_keys(client):
    org, user, _ = await make_org(plan="STARTER")
    listed = (await client.get("/org/api-keys", headers=auth(org, user))).json()
    assert listed["entitled"] is False
    r = await client.post(
        "/org/api-keys", headers=auth(org, user), json={"name": "x", "scopes": ["scans:read"]}
    )
    assert (
        r.status_code == 402
        and r.json()["code"] == "api_not_in_plan"
        and r.json()["upgrade_url"] == "/org#plan"
    )


# -- authentication -------------------------------------------------------------------------------
async def test_every_way_a_key_can_be_wrong_gets_the_same_answer(client):
    org, user, k, h = await org_with_key(client)
    other, ouser, _ = await make_org(plan="GROWTH")
    good = k["key"]
    forged_org = f"a11y_{other.hex}_{good.split('_', 2)[2]}"  # right secret, wrong organisation
    wrong = good[:-1] + ("A" if good[-1] != "A" else "B")
    bad = [
        {},
        {"authorization": "Bearer"},
        {"authorization": "Basic abc"},
        bearer("not-a-key"),
        bearer(wrong),
        bearer(forged_org),
        bearer("a11y_" + "0" * 32 + "_" + "x" * 43),
    ]
    bodies = set()
    for hdr in bad:
        r = await client.get("/v1/me", headers=hdr)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer", hdr
        bodies.add(r.text)
    assert len(bodies) == 1, "a caller must not be able to tell which part of a guess was right"
    assert (await client.get("/v1/me", headers=h)).status_code == 200


async def test_revoked_expired_and_orphaned_keys_stop_working(client):
    org, user, k, h = await org_with_key(client)
    assert (await client.get("/v1/me", headers=h)).status_code == 200
    await client.delete(f"/org/api-keys/{k['id']}", headers=auth(org, user))
    assert (await client.get("/v1/me", headers=h)).status_code == 401

    k2 = await new_key(client, org, user, name="short")
    await sql(
        "UPDATE api_keys SET expires_at = now() - interval '1 minute' WHERE id=$1",
        uuid.UUID(k2["id"]),
    )
    assert (await client.get("/v1/me", headers=bearer(k2["key"]))).status_code == 401

    k3 = await new_key(client, org, user, name="creator-leaves")
    assert (await client.get("/v1/me", headers=bearer(k3["key"]))).status_code == 200
    await sql(
        "UPDATE users SET is_active=false WHERE id=$1", user
    )  # whoever made it is no longer a member
    assert (await client.get("/v1/me", headers=bearer(k3["key"]))).status_code == 401


async def test_losing_api_access_in_the_plan_is_enforced_on_every_request(client):
    org, user, k, h = await org_with_key(client)
    assert (await client.get("/v1/me", headers=h)).status_code == 200
    await sql("UPDATE subscriptions SET plan_id='STARTER' WHERE organization_id=$1", org)
    r = await client.get("/v1/me", headers=h)
    assert r.status_code == 403 and r.json()["code"] == "api_not_in_plan"


async def test_scopes_limit_what_a_key_can_do(client, site, dev):
    org, user, k, h = await org_with_key(client, ["scans:read"])
    r = await client.post("/v1/scans", headers=h, json={"url": f"{site}/good.html"})
    assert (
        r.status_code == 403
        and r.json()["code"] == "scope_missing"
        and r.json()["required_scope"] == "scans:write"
    )
    assert (await client.get("/v1/scans", headers=h)).status_code == 200
    assert (await client.get("/v1/audit-log", headers=h)).status_code == 403
    assert (
        await client.post(
            f"/v1/scans/{uuid.uuid4()}/reports", headers=h, json={"kind": "audit_csv"}
        )
    ).status_code == 403


async def test_an_api_key_cannot_use_the_session_api_or_become_an_administrator(client):
    org, user, k, h = await org_with_key(client)
    for method, url in (
        ("get", "/org/api-keys"),
        ("get", "/org/users"),
        ("get", "/scans"),
        ("get", "/admin/plans"),
    ):
        assert (await getattr(client, method)(url, headers=h)).status_code in (401, 403)


async def test_last_use_is_recorded(client):
    org, user, k, h = await org_with_key(client)
    await client.get("/v1/me", headers=h)
    row = (await sql("SELECT last_used_at FROM api_keys WHERE id=$1", uuid.UUID(k["id"])))[0]
    assert row["last_used_at"] is not None


# -- limits ---------------------------------------------------------------------------------------
async def test_each_key_has_its_own_rate_limit(client):
    org, user, k, h = await org_with_key(client)
    k2 = await new_key(client, org, user, name="other")
    await get_config().save(
        "api.limits", Scope.ORG, str(org), {"requests_per_minute": 3}, comment="test-rl", actor=None
    )
    codes = []
    for _ in range(5):
        r = await client.get("/v1/me", headers=h)
        codes.append(r.status_code)
    assert codes == [200, 200, 200, 429, 429]
    assert r.json()["code"] == "rate_limited" and int(r.headers["retry-after"]) >= 1
    assert r.headers["x-ratelimit-limit"] == "3" and r.headers["x-ratelimit-remaining"] == "0"
    ok = await client.get("/v1/me", headers=bearer(k2["key"]))
    assert (
        ok.status_code == 200 and ok.headers["x-ratelimit-remaining"] == "2"
    )  # another key is unaffected


# -- the real flow --------------------------------------------------------------------------------
async def test_start_a_scan_read_its_findings_and_download_a_report(client, site, dev):
    org, user, k, h = await org_with_key(client)
    me = (await client.get("/v1/me", headers=h)).json()
    assert (
        me["plan"] == "GROWTH"
        and me["organization"]["id"] == str(org)
        and set(me["key"]["scopes"]) == set(ALL)
    )

    r = await client.post(
        "/v1/scans", headers={**h, "Idempotency-Key": "build-42"}, json={"url": f"{site}/bad.html"}
    )
    assert r.status_code == 202, r.text
    sid = uuid.UUID(r.json()["id"])
    assert [d[0] for d in dev] == ["web.scan"]
    again = await client.post(
        "/v1/scans", headers={**h, "Idempotency-Key": "build-42"}, json={"url": f"{site}/bad.html"}
    )
    assert (
        again.status_code == 202
        and again.json() == r.json()
        and again.headers["idempotent-replay"] == "true"
    )
    assert (
        len(dev) == 1
        and (await client.get("/v1/me", headers=h)).json()["scans_used_this_month"] == 1
    )  # one scan, one credit

    assert (await client.get(f"/v1/scans/{sid}", headers=h)).json()["status"] == "QUEUED"
    assert await run_scan(org, sid, opts_override=FAST) == "SUCCEEDED"
    scan = (await client.get(f"/v1/scans/{sid}", headers=h)).json()
    assert (
        scan["status"] == "SUCCEEDED"
        and scan["findings_count"] > 10
        and scan["summary"]["disclaimer"]
    )
    listed = (await client.get("/v1/scans", headers=h)).json()
    assert listed["total"] == 1 and listed["scans"][0]["id"] == str(sid)

    f = (await client.get(f"/v1/scans/{sid}/findings?rule=image-alt&limit=5", headers=h)).json()
    assert (
        f["total"] >= 1
        and f["findings"][0]["rule"] == "image-alt"
        and "rect" in f["findings"][0]["element"]
    )
    assert "clusters" not in f  # exclude_none keeps the answer tidy
    grouped = (await client.get(f"/v1/scans/{sid}/findings?group=cluster", headers=h)).json()
    assert grouped["clusters"] and grouped["total"] >= 1
    assert (
        await client.get(f"/v1/scans/{sid}/findings?severity=bogus", headers=h)
    ).status_code == 422
    assert (await client.get(f"/v1/scans/{sid}/summary", headers=h)).json()[
        "standard"
    ] == "WCAG_2_2_AA"

    rep = await client.post(
        f"/v1/scans/{sid}/reports",
        headers={**h, "Idempotency-Key": "r1"},
        json={"kind": "audit_csv"},
    )
    assert rep.status_code == 202, rep.text
    rid = uuid.UUID(rep.json()["id"])
    assert (await client.get(f"/v1/reports/{rid}", headers=h)).json()["status"] == "QUEUED"
    assert (await client.get(f"/v1/reports/{rid}/download", headers=h)).status_code in (
        404,
        409,
    )  # not ready: no file
    await render_report(org, rid)
    got = (await client.get(f"/v1/reports/{rid}", headers=h)).json()
    assert got["status"] == "READY" and got["validation"]
    d = await client.get(f"/v1/reports/{rid}/download", headers=h)
    assert d.status_code == 200 and d.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(d.content.decode("utf-8-sig"))))
    assert len(rows) > 5
    assert len((await client.get(f"/v1/scans/{sid}/reports", headers=h)).json()) == 1


async def test_a_failed_request_does_not_burn_its_idempotency_key(client, site, dev):
    org, user, k, h = await org_with_key(client)
    bad = await client.post(
        "/v1/scans", headers={**h, "Idempotency-Key": "k1"}, json={"url": "http://127.0.0.1:1/"}
    )
    assert bad.status_code == 422 and dev == []  # not scanned: the guard refused the address
    ok = await client.post(
        "/v1/scans", headers={**h, "Idempotency-Key": "k1"}, json={"url": f"{site}/good.html"}
    )
    assert (
        ok.status_code == 202
    )  # the same key can be used again because the first attempt did nothing
    assert (
        await client.post(
            "/v1/scans", headers={**h, "Idempotency-Key": ""}, json={"url": f"{site}/good.html"}
        )
    ).status_code in (202, 422)
    long_key = "x" * 81
    r = await client.post(
        "/v1/scans", headers={**h, "Idempotency-Key": long_key}, json={"url": f"{site}/good.html"}
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_idempotency_key"


async def test_quota_errors_are_structured_for_programs(client, site, dev):
    org, user, k, h = await org_with_key(client)
    from a11y_core import billing
    from a11y_core.db import tenant_session

    await sql(
        "UPDATE plan_entitlements SET limit_value=1 WHERE plan_id='GROWTH' AND feature_key='urls_monthly'"
    )
    try:
        async with tenant_session(org) as db:
            await billing.reserve(db, org, "urls_monthly", "seed")
        r = await client.post("/v1/scans", headers=h, json={"url": f"{site}/good.html"})
        assert (
            r.status_code == 402 and r.json()["code"] == "quota_exceeded" and r.json()["limit"] == 1
        )
    finally:
        await sql(
            "UPDATE plan_entitlements SET limit_value=NULL WHERE plan_id='GROWTH' AND feature_key='urls_monthly'"
        )


async def test_organisations_cannot_see_each_others_data(client, site, dev):
    org, user, k, h = await org_with_key(client)
    sid = uuid.UUID(
        (await client.post("/v1/scans", headers=h, json={"url": f"{site}/good.html"})).json()["id"]
    )
    await run_scan(org, sid, opts_override=FAST)
    other, ouser, ok, oh = await org_with_key(client)
    assert (await client.get(f"/v1/scans/{sid}", headers=oh)).status_code == 404
    assert (await client.get(f"/v1/scans/{sid}/findings", headers=oh)).status_code == 404
    assert (await client.get("/v1/scans", headers=oh)).json()["total"] == 0
    assert (
        await client.post(f"/v1/scans/{sid}/reports", headers=oh, json={"kind": "audit_csv"})
    ).status_code == 404


async def test_the_audit_log_endpoint_pages_and_filters(client):
    org, user, k, h = await org_with_key(client)
    for i in range(3):
        await new_key(client, org, user, ["scans:read"], name=f"k{i}")
    r = (await client.get("/v1/audit-log?limit=2", headers=h)).json()
    assert len(r["events"]) == 2 and r["next_before"] is not None
    page2 = (
        await client.get(
            "/v1/audit-log", headers=h, params={"limit": 50, "before": r["next_before"]}
        )
    ).json()
    assert page2["next_before"] is None and {e["id"] for e in page2["events"]}.isdisjoint(
        {e["id"] for e in r["events"]}
    )
    only = (await client.get("/v1/audit-log?action=api_key.create&limit=50", headers=h)).json()
    assert {e["action"] for e in only["events"]} == {"api_key.create"} and len(only["events"]) == 4
    assert "scopes" in only["events"][0]["detail"]


# -- the published description --------------------------------------------------------------------
async def test_the_openapi_document_is_complete_and_only_describes_v1(client):
    r = await client.get("/v1/openapi.json")
    assert r.status_code == 200  # the description is public; using the API is not
    spec = r.json()
    assert (
        spec["openapi"].startswith("3.")
        and spec["info"]["title"] == "a11y API"
        and spec["info"]["version"] == "1.0.0"
    )
    assert all(p.startswith("/v1/") for p in spec["paths"]) and len(spec["paths"]) >= 9
    assert spec["components"]["securitySchemes"]["apiKey"]["scheme"] == "bearer"
    ids = []
    for path, item in spec["paths"].items():
        for method, o in item.items():
            where = f"{method.upper()} {path}"
            assert o.get("summary") and o.get("description"), where
            assert {"401", "403", "429"} <= set(o["responses"]), where
            assert o["responses"]["401"]["content"]["application/json"]["schema"]["$ref"].endswith(
                "/Problem"
            ), where
            assert o.get("security") == [{"apiKey": []}], where
            if path != "/v1/me":
                assert o["x-required-scope"] in api_keys.SCOPES, where
            ids.append(o["operationId"])
    assert len(ids) == len(set(ids))
    assert "Idempotency-Key" in str(spec["paths"]["/v1/scans"]["post"]["parameters"])
    assert (
        "Problem" in spec["components"]["schemas"]
        and "never a statement of conformance" in spec["info"]["description"]
    )


def test_the_reference_page_fixture_matches_the_real_api_description():
    """The web tests render the reference page from a saved copy of the OpenAPI description. If the API changes, this
    fails until the copy is refreshed, so the page is always tested against what the API really publishes:
        python -c "import json, a11y_api.main as m; from a11y_api.routers.v1 import v1_openapi; \
json.dump(v1_openapi(m.app), open('../web/e2e/openapi-fixture.json','w'), indent=1)" """
    import json
    from pathlib import Path

    from a11y_api.main import app
    from a11y_api.routers.v1 import v1_openapi

    saved = json.loads(
        (Path(__file__).resolve().parents[2] / "web/e2e/openapi-fixture.json").read_text()
    )
    assert json.loads(json.dumps(v1_openapi(app))) == saved
