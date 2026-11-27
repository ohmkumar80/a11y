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
        if not self.answers:  # like the real gateway: a route nobody configured is "not available"
            raise AIUnavailable("no route", reason="not_configured")
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
    # sampling is random by design: switch it off so the number of model calls is deterministic
    await get_config().save(
        "ai.code_fix", Scope.ORG, str(org), {"validation": "off"}, comment="test-off", actor=None
    )
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


class TaskGateway:
    """A model per task: code_fix, code_fix_escalate, code_fix_validate."""

    def __init__(self, **by_task):
        self.by_task, self.calls = {k: list(v) for k, v in by_task.items()}, []

    async def complete(self, req):
        self.calls.append(req.task)
        answers = self.by_task.get(req.task)
        if not answers:
            raise AIUnavailable("no route", reason="not_configured")
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        text = (
            a if a.startswith("{") else json.dumps({"fixed_html": a, "explanation": "Adds a name."})
        )
        return LLMResponse(text, "p", f"model-for-{req.task}", 5, 5, 0, 1, False)


BTN_FIX = '<button aria-label="Submit form"></button>'
PASS = json.dumps({"verdict": "pass", "reasons": []})


async def test_settings_drive_escalation_and_the_reviewer_through_the_real_job(
    client, site, dev, monkeypatch
):
    org, user, sid, h = await scanned(client, site)
    fid = await finding(client, h, sid, "button-name")
    await get_config().save(
        "ai.code_fix",
        Scope.ORG,
        str(org),
        {"validation": "always", "validation_sample_rate": 1.0},
        comment="test-tier",
        actor=None,
    )
    gw = TaskGateway(
        code_fix=["<button></button>", "<button></button>"],
        code_fix_escalate=[BTN_FIX],
        code_fix_validate=[PASS],
    )
    monkeypatch.setattr("a11y_core.ai.get_gateway", lambda: gw)
    fix = (await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json={})).json()
    assert await run_fix(org, uuid.UUID(fix["id"])) == "READY"
    got = (await client.get(f"/fixes/{fix['id']}", headers=h)).json()
    assert (
        got["rung"] == "standard"
        and got["model_id"] == "model-for-code_fix_escalate"
        and got["attempts"] == 3
    )
    assert gw.calls == ["code_fix", "code_fix", "code_fix_escalate", "code_fix_validate"]
    assert any("independent reviewer" in c["name"] and c["passed"] for c in got["checks"])


async def test_a_required_review_that_cannot_run_blocks_the_fix_end_to_end(
    client, site, dev, monkeypatch
):
    org, user, sid, h = await scanned(client, site)
    fid = await finding(client, h, sid, "button-name")
    await get_config().save(
        "ai.code_fix", Scope.ORG, str(org), {"validation": "always"}, comment="test-req", actor=None
    )
    gw = TaskGateway(code_fix=[BTN_FIX])  # no reviewer route configured
    monkeypatch.setattr("a11y_core.ai.get_gateway", lambda: gw)
    fix = (await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json={})).json()
    assert await run_fix(org, uuid.UUID(fix["id"])) == "NEEDS_REVIEW"
    got = (await client.get(f"/fixes/{fix['id']}", headers=h)).json()
    assert (
        got["reason"] == "validator_unavailable"
        and got["fixed_html"] is None
        and "independent review" in got["detail"]
    )


async def test_escalation_can_be_switched_off(client, site, dev, monkeypatch):
    org, user, sid, h = await scanned(client, site)
    fid = await finding(client, h, sid, "button-name")
    await get_config().save(
        "ai.code_fix",
        Scope.ORG,
        str(org),
        {"escalate": False, "validation": "off"},
        comment="test-noesc",
        actor=None,
    )
    gw = TaskGateway(
        code_fix=["<button></button>", "<button></button>"], code_fix_escalate=[BTN_FIX]
    )
    monkeypatch.setattr("a11y_core.ai.get_gateway", lambda: gw)
    fix = (await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json={})).json()
    assert await run_fix(org, uuid.UUID(fix["id"])) == "NEEDS_REVIEW"
    assert "code_fix_escalate" not in gw.calls


# -- credits: pay only for a fix an AI model produced and our checks accepted ----------------------
FIXC = "ai_code_fixes_monthly"


async def set_fix_limit(org, limit):
    await sql(
        "INSERT INTO entitlement_overrides (organization_id, feature_key, enabled, limit_value, reason) VALUES ($1,$2,true,$3,'test') "
        "ON CONFLICT (organization_id, feature_key) DO UPDATE SET limit_value=$3",
        org,
        FIXC,
        limit,
    )


async def meter(client, h):
    q = (await client.get("/org/subscription", headers=h)).json()["quotas"]
    return next(m for m in q if m["feature"] == FIXC)


async def ask(client, h, sid, fid, **body):
    return (await client.post(f"/scans/{sid}/findings/{fid}/fix", headers=h, json=body)).json()


async def test_only_an_accepted_ai_fix_uses_a_credit(client, site, dev, monkeypatch):
    org, user, sid, h = await scanned(client, site)
    await set_fix_limit(org, 5)
    assert (await meter(client, h))["used"] == 0
    # a ready-made recipe is free
    f1 = await finding(client, h, sid, "form-field-label")
    r1 = await ask(client, h, sid, f1)
    assert await run_fix(org, uuid.UUID(r1["id"])) == "READY"
    assert (await meter(client, h))["used"] == 0 and (
        await client.get(f"/fixes/{r1['id']}", headers=h)
    ).json()["credit_used"] is False
    # an AI fix that is accepted costs one
    f2 = await finding(client, h, sid, "button-name")
    gw = TaskGateway(code_fix=[BTN_FIX], code_fix_validate=[PASS])
    monkeypatch.setattr("a11y_core.ai.get_gateway", lambda: gw)
    r2 = await ask(client, h, sid, f2)
    assert (await meter(client, h))["used"] == 1  # held while the job is queued
    assert await run_fix(org, uuid.UUID(r2["id"])) == "READY"
    got = (await client.get(f"/fixes/{r2['id']}", headers=h)).json()
    assert (await meter(client, h))["used"] == 1 and got["credit_used"] is True
    # asking again returns the same fix: no second charge
    again = await ask(client, h, sid, f2)
    assert again["id"] == r2["id"] and (await meter(client, h))["used"] == 1


async def test_a_fix_nobody_could_produce_is_free_and_a_retry_charges_only_on_success(
    client, site, dev, monkeypatch
):
    org, user, sid, h = await scanned(client, site)
    await set_fix_limit(org, 5)
    fid = await finding(client, h, sid, "button-name")
    monkeypatch.setattr(
        "a11y_core.ai.get_gateway",
        lambda: TaskGateway(code_fix=["<button></button>", "<button></button>"]),
    )
    r = await ask(client, h, sid, fid)
    assert await run_fix(org, uuid.UUID(r["id"])) == "NEEDS_REVIEW"
    assert (await meter(client, h))["used"] == 0  # nothing delivered: not charged
    monkeypatch.setattr("a11y_core.ai.get_gateway", lambda: TaskGateway(code_fix=[BTN_FIX]))
    retry = await ask(client, h, sid, fid, retry=True)
    assert (
        retry["id"] == r["id"] and (await meter(client, h))["used"] == 1
    )  # a new credit is held for the new attempt
    assert await run_fix(org, uuid.UUID(r["id"])) == "READY"
    assert (await meter(client, h))["used"] == 1


async def test_a_crash_never_charges(client, site, dev, monkeypatch):
    org, user, sid, h = await scanned(client, site)
    await set_fix_limit(org, 5)
    fid = await finding(client, h, sid, "button-name")
    r = await ask(client, h, sid, fid)

    async def boom(*a, **k):
        raise RuntimeError("browser crashed")

    monkeypatch.setattr("a11y_web_audit.fixes.ladder.suggest", boom)
    assert await run_fix(org, uuid.UUID(r["id"])) == "FAILED"
    assert (await meter(client, h))["used"] == 0


async def test_when_the_monthly_credits_run_out_recipes_still_work_and_the_model_is_not_called(
    client, site, dev, monkeypatch
):
    org, user, sid, h = await scanned(client, site)
    await set_fix_limit(org, 0)
    gw = TaskGateway(code_fix=[BTN_FIX])
    monkeypatch.setattr("a11y_core.ai.get_gateway", lambda: gw)
    b = await finding(client, h, sid, "button-name")
    r = await ask(client, h, sid, b)
    assert r["status"] == "PENDING"  # not refused: the person is told why when it finishes
    assert await run_fix(org, uuid.UUID(r["id"])) == "NEEDS_REVIEW"
    got = (await client.get(f"/fixes/{r['id']}", headers=h)).json()
    assert (
        got["reason"] == "ai_quota_reached"
        and "used all your AI code fixes" in got["detail"]
        and got["fixed_html"] is None
    )
    assert gw.calls == []  # no tokens were spent
    free = await ask(client, h, sid, await finding(client, h, sid, "form-field-label"))
    assert (
        await run_fix(org, uuid.UUID(free["id"])) == "READY"
    )  # a recipe costs nothing, so it still works
    assert (await meter(client, h))["used"] == 0


async def test_the_last_credit_goes_to_exactly_one_of_many_simultaneous_requests(
    client, site, dev, monkeypatch
):
    import asyncio

    org, user, sid, h = await scanned(client, site)
    await set_fix_limit(org, 1)
    fs = (await client.get(f"/scans/{sid}/findings?kind=violation&limit=12", headers=h)).json()[
        "findings"
    ]
    ids = [f["id"] for f in fs][:8]
    await asyncio.gather(*[ask(client, h, sid, i) for i in ids])
    assert (await meter(client, h))[
        "used"
    ] == 1  # never more than the limit, however many arrive at once


async def test_the_sweeper_settles_fix_credits_left_by_a_dead_job(client, site, dev):
    from a11y_core import billing
    from a11y_core.db import tenant_session
    from a11y_core.scan_jobs import sweep_orphaned_reservations

    org, user, sid, h = await scanned(client, site)
    await set_fix_limit(org, 10)
    f = await finding(client, h, sid, "button-name")
    delivered, vanished = uuid.uuid4(), uuid.uuid4()
    await sql(
        "INSERT INTO fix_suggestions (id, organization_id, scan_id, finding_id, rule, input_hash, original_html, status, rung, finished_at) "
        "VALUES ($1,$2,$3,$4,'button-name',$5,'<button></button>','READY','light',now())",
        delivered,
        org,
        sid,
        uuid.UUID(f),
        "h" * 64,
    )
    for job in (
        delivered,
        vanished,
    ):  # the worker died after reserving; one fix was delivered, one row never existed
        async with tenant_session(org) as db:
            await billing.reserve(db, org, FIXC, str(job))
        await sql(
            "UPDATE usage_reservations SET created_at = now() - interval '3 hours' WHERE job_id=$1",
            str(job),
        )
    await sweep_orphaned_reservations()
    status = {
        j: (await sql("SELECT status FROM usage_reservations WHERE job_id=$1", str(j)))[0]["status"]
        for j in (delivered, vanished)
    }
    assert status == {
        delivered: "COMMITTED",
        vanished: "RELEASED",
    }  # charged only for what was delivered
    assert (await meter(client, h))["used"] == 1
