# ruff: noqa: F811
"""Code-fix suggestions end to end: real scan -> request -> worker job -> validated result, with a stubbed model."""

import json
import uuid

import pytest
from a11y_core.ai.types import AIUnavailable, LLMResponse
from a11y_core.config import Scope, get_config
from a11y_web_audit.tasks import run_fix, run_scan

from .conftest import make_org, sql
from .test_billing import auth
from .test_scans_api import FAST, _cfg_reset, create, dev, high_ports, site  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
async def _reset_policy():
    yield
    await sql("DELETE FROM setting_versions WHERE key = 'ai.code_fix'")
    from a11y_core.config import get_config

    await get_config().invalidate("ai.code_fix") if hasattr(get_config(), "invalidate") else None


class FakeGateway:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0

    async def complete(self, req):
        self.calls += 1
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return LLMResponse(
            json.dumps({"fixed_html": a, "explanation": "Adds a name."}),
            "p",
            "m-light",
            5,
            5,
            0,
            1,
            False,
        )


async def scanned(client, site, org=None, user=None):
    if org is None:
        org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    sid = uuid.UUID((await create(client, h, f"{site}/bad.html")).json()["id"])
    assert await run_scan(org, sid, opts_override=FAST) == "SUCCEEDED"
    return org, user, sid, h


async def finding(client, h, sid, rule, kind="violation"):
    r = await client.get(f"/scans/{sid}/findings?kind={kind}&rule={rule}&limit=5", headers=h)
    fs = r.json()["findings"]
    assert fs, f"no {rule} finding in the fixture page"
    return fs[0]["id"]


async def test_recipe_fix_end_to_end_and_idempotent(client, site, dev):
    org, user, sid, h = await scanned(client, site)
    fid = await finding(client, h, sid, "form-field-label")
    dev.clear()
    r = await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json={})
    assert r.status_code == 202, r.text
    fix = r.json()
    assert fix["status"] == "PENDING" and fix["fixed_html"] is None
    assert dev == [
        ("web.suggest_fix", [str(org), fix["id"]], "web")
    ]  # browser queue: the oracle needs a browser

    assert await run_fix(org, uuid.UUID(fix["id"])) == "READY"
    got = (await client.get(f"/fixes/{fix['id']}", headers=h)).json()
    assert (
        got["status"] == "READY" and got["rung"] == "recipe" and "<label for=" in got["fixed_html"]
    )
    assert any("no longer appears" in c["name"] and c["passed"] for c in got["checks"])
    assert await run_fix(org, uuid.UUID(fix["id"])) == "READY"  # redelivery changes nothing

    again = await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json={})
    assert again.json()["id"] == fix["id"] and again.json()["status"] == "READY"
    assert len(dev) == 1  # nothing queued the second time


async def test_model_fix_is_validated_before_it_is_shown(client, site, dev, monkeypatch):
    org, user, sid, h = await scanned(client, site)
    fid = await finding(client, h, sid, "button-name")
    gw = FakeGateway('<button aria-label="Submit form"></button>')
    monkeypatch.setattr("a11y_core.ai.get_gateway", lambda: gw)
    fix = (await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json={})).json()
    st = await run_fix(org, uuid.UUID(fix["id"]))
    got = (await client.get(f"/fixes/{fix['id']}", headers=h)).json()
    assert st == "READY", json.dumps(
        {k: got[k] for k in ("original_html", "reason", "checks", "detail")}
    )
    assert got["rung"] == "light" and got["model_id"] == "m-light" and gw.calls == 1
    assert "aria-label" in got["fixed_html"]


async def test_a_model_fix_that_does_not_work_is_never_delivered(client, site, dev, monkeypatch):
    org, user, sid, h = await scanned(client, site)
    fid = await finding(client, h, sid, "button-name")
    monkeypatch.setattr(
        "a11y_core.ai.get_gateway", lambda: FakeGateway("<button></button>", "<button></button>")
    )
    fix = (await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json={})).json()
    assert await run_fix(org, uuid.UUID(fix["id"])) == "NEEDS_REVIEW"
    got = (await client.get(f"/fixes/{fix['id']}", headers=h)).json()
    assert got["fixed_html"] is None and got["reason"] == "no_valid_fix" and got["attempts"] == 2
    assert "did not" in got["detail"] or "not showing" in got["detail"]
    # the database itself refuses unvalidated code
    with pytest.raises(Exception, match="ck_fix_only_if_ready"):
        await sql("UPDATE fix_suggestions SET fixed_html='<x>' WHERE id=$1", uuid.UUID(fix["id"]))


async def test_no_model_configured_degrades_to_a_clear_message_and_retry_works(
    client, site, dev, monkeypatch
):
    org, user, sid, h = await scanned(client, site)
    fid = await finding(client, h, sid, "button-name")
    monkeypatch.setattr(
        "a11y_core.ai.get_gateway",
        lambda: FakeGateway(AIUnavailable("none", reason="not_configured")),
    )
    fix = (await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json={})).json()
    assert await run_fix(org, uuid.UUID(fix["id"])) == "NEEDS_REVIEW"
    got = (await client.get(f"/fixes/{fix['id']}", headers=h)).json()
    assert (
        got["reason"] == "ai_unavailable"
        and got["fixed_html"] is None
        and "No AI model" in got["detail"]
    )

    # an admin configures a model; retry re-runs it
    monkeypatch.setattr(
        "a11y_core.ai.get_gateway", lambda: FakeGateway('<button aria-label="Send"></button>')
    )
    r = await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json={"retry": True})
    assert r.json()["status"] == "PENDING" and r.json()["id"] == fix["id"]
    assert await run_fix(org, uuid.UUID(fix["id"])) == "READY"


async def test_same_element_in_a_later_scan_is_a_free_cache_hit(client, site, dev):
    org, user, sid, h = await scanned(client, site)
    fid = await finding(client, h, sid, "form-field-label")
    first = (await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json={})).json()
    await run_fix(org, uuid.UUID(first["id"]))
    _, _, sid2, _ = await scanned(client, site, org, user)
    fid2 = await finding(client, h, sid2, "form-field-label")
    dev.clear()
    hit = (await client.post(f"/scans/{sid2}/findings/{fid2}/fix", headers=h, json={})).json()
    assert hit["status"] == "READY" and hit["from_cache"] is True and hit["id"] != first["id"]
    assert dev == []  # rung 1: no job, no tokens


async def test_policy_can_switch_fixes_off_or_models_off(client, site, dev, monkeypatch):
    org, user, sid, h = await scanned(client, site)
    fid = await finding(client, h, sid, "button-name")
    await get_config().save(
        "ai.code_fix", Scope.ORG, str(org), {"use_ai": False}, comment="t", actor=None
    )
    gw = FakeGateway('<button aria-label="x"></button>')
    monkeypatch.setattr("a11y_core.ai.get_gateway", lambda: gw)
    fix = (await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json={})).json()
    assert (
        await run_fix(org, uuid.UUID(fix["id"])) == "NEEDS_REVIEW" and gw.calls == 0
    )  # recipes only
    await get_config().save(
        "ai.code_fix", Scope.ORG, str(org), {"enabled": False}, comment="t2", actor=None
    )
    r = await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json={})
    assert r.status_code == 403 and r.json()["code"] == "fixes_disabled"


async def test_rate_limit_and_validation(client, site, dev):
    org, user, sid, h = await scanned(client, site)
    await get_config().save(
        "ai.code_fix", Scope.ORG, str(org), {"per_minute": 1}, comment="rl", actor=None
    )
    a, b = (
        await finding(client, h, sid, "form-field-label"),
        await finding(client, h, sid, "button-name"),
    )
    assert (
        await client.post(f"/scans/{sid}/findings/{a}/fix", headers=h, json={})
    ).status_code == 202
    r = await client.post(f"/scans/{sid}/findings/{b}/fix", headers=h, json={})
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"
    assert (
        await client.post(f"/scans/{sid}/findings/{uuid.uuid4()}/fix", headers=h, json={})
    ).status_code == 404


async def test_best_practices_have_no_fix(client, site, dev):
    org, user, sid, h = await scanned(client, site)
    bp = (await client.get(f"/scans/{sid}/findings?kind=best_practice&limit=1", headers=h)).json()[
        "findings"
    ]
    assert bp
    r = await client.post(f"/scans/{sid}/findings/{bp[0]['id']}/fix", headers=h, json={})
    assert r.status_code == 422 and r.json()["code"] == "not_fixable"


async def test_another_organisation_cannot_see_or_request_it(client, site, dev):
    org, user, sid, h = await scanned(client, site)
    fid = await finding(client, h, sid, "form-field-label")
    fix = (await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json={})).json()
    org2, user2, _ = await make_org(plan="GROWTH")
    h2 = auth(org2, user2)
    assert (await client.get(f"/fixes/{fix['id']}", headers=h2)).status_code == 404
    assert (
        await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h2, json={})
    ).status_code == 404
    assert (await client.get(f"/fixes/{fix['id']}")).status_code == 401
