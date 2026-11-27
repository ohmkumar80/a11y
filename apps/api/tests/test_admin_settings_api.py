from a11y_core.config import get_config

from .conftest import make_org, super_admin_headers
from .test_settings import KEY, _clean  # noqa: F401  (autouse cleanup fixture)


async def test_requires_super_admin(client):
    assert (await client.get("/admin/settings")).status_code == 401
    org, user, email = await make_org()
    from a11y_api.security import Principal, issue_access_token

    tok, _ = issue_access_token(Principal(user, org, "COMPANY_ADMIN"))
    r = await client.get("/admin/settings", headers={"authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    # and a super admin token cannot be used on tenant routes
    r = await client.get("/me", headers=super_admin_headers())
    assert r.status_code == 403


async def test_registry_exposes_schemas_for_generated_forms(client):
    r = await client.get("/admin/settings", headers=super_admin_headers())
    assert r.status_code == 200
    by_key = {s["key"]: s for s in r.json()}
    assert "ai.providers" in by_key and "billing.trial" in by_key
    assert by_key["billing.trial"]["schema"]["properties"]["length_days"]["maximum"] == 365
    assert by_key["ai.providers"]["high_risk"] is True


async def test_write_read_history_rollback_over_http(client):
    h = super_admin_headers()
    w = await client.put(
        "/admin/settings/billing.trial",
        headers=h,
        json={"value": {"length_days": 30}, "comment": "test-http-1"},
    )
    assert w.status_code == 200 and w.json()["version"] == 1
    await client.put(
        "/admin/settings/billing.trial",
        headers=h,
        json={"value": {"length_days": 7}, "comment": "test-http-2"},
    )
    r = await client.get("/admin/settings/billing.trial", headers=h)
    assert (r.json()["value"]["length_days"], r.json()["version"], r.json()["source"]) == (
        7,
        2,
        "global (v2)",
    )
    hist = (await client.get("/admin/settings/billing.trial/history", headers=h)).json()
    assert [x["version"] for x in hist] == [2, 1]
    rb = await client.post(
        "/admin/settings/billing.trial/rollback",
        headers=h,
        json={"to_version": 1, "comment": "test-http-3"},
    )
    assert rb.json() == {"version": 3, "restored_from": 1}
    assert (await get_config().effective(KEY)).value.length_days == 30


async def test_validation_errors_use_the_standard_error_shape(client):
    h = super_admin_headers()
    r = await client.put(
        "/admin/settings/billing.trial",
        headers=h,
        json={"value": {"length_days": 0}, "comment": "test-bad"},
    )
    assert (
        r.status_code == 422
        and r.json()["field"] == "value"
        and "length_days" in r.json()["detail"]
    )
    r = await client.put(
        "/admin/settings/nope", headers=h, json={"value": {}, "comment": "test-bad"}
    )
    assert r.status_code == 404


async def test_secrets_never_come_back_over_http(client):
    h = super_admin_headers()
    key = "sk-test-0123456789abcdef-QRST"
    body = {
        "items": [
            {
                "id": "p",
                "type": "openai",
                "display_name": "P",
                "api_key": {"$secret": True, "plaintext": key},
            }
        ]
    }
    assert (
        await client.put(
            "/admin/settings/ai.providers", headers=h, json={"value": body, "comment": "test-sec"}
        )
    ).status_code == 200
    for url in ("/admin/settings/ai.providers", "/admin/settings/ai.providers/history"):
        txt = (await client.get(url, headers=h)).text
        assert key not in txt and '"ct"' not in txt and "••••QRST" in txt
