"""LLMGateway driven entirely by admin settings (PROJECT_PLAN 3.11.2, Phase 1 exit criteria)."""

import asyncio

import pytest
from a11y_core.ai import AIUnavailable, LLMRequest, Message, get_gateway
from a11y_core.ai.adapters import FakeAdapter
from a11y_core.config import Scope, get_config

from .conftest import make_org, sql
from .test_settings import _clean  # noqa: F401  (clears settings + cache around each test)


@pytest.fixture(autouse=True)
async def _ai_clean():
    FakeAdapter.calls.clear()
    yield
    await sql("DELETE FROM ai_usage WHERE task_key IN ('code_fix','alt_text')")


def prov(pid, key=True, **kw):
    return {
        "id": pid,
        "type": "fake",
        "display_name": pid,
        **kw,
        **({"api_key": {"$secret": True, "plaintext": "fake-key-0123456789-ABCD"}} if key else {}),
    }


def model(mid, pid, name="ok", caps=("text",), **kw):
    return {"id": mid, "provider_id": pid, "model_name": name, "capabilities": list(caps), **kw}


async def configure(models, providers=("a", "b"), route=None, **route_kw):
    cfg = get_config()
    await cfg.save(
        "ai.providers",
        Scope.GLOBAL,
        "",
        {"items": [prov(p) for p in providers]},
        comment="test-ai",
        actor=None,
    )
    await cfg.save("ai.models", Scope.GLOBAL, "", {"items": models}, comment="test-ai", actor=None)
    if route:
        await cfg.save(
            "ai.route.code_fix", Scope.GLOBAL, "", route, comment="test-ai", actor=None, **route_kw
        )


def req(org, task="code_fix", **kw):
    return LLMRequest(task, [Message("user", "fix my <img>")], org_id=org, **kw)


async def test_unconfigured_task_degrades_to_deterministic():
    org, *_ = await make_org()
    with pytest.raises(AIUnavailable) as e:
        await get_gateway().complete(req(org))
    assert e.value.reason == "not_configured"


async def test_routes_to_primary_and_meters_cost():
    org, *_ = await make_org()
    await configure(
        [model("m-a", "a", input_cost_per_1m=3, output_cost_per_1m=15)],
        route={"primary_model_id": "m-a"},
    )
    r = await get_gateway().complete(req(org, job_id="job-1"))
    assert (r.provider_id, r.model_id, r.fell_back) == ("a", "m-a", False)
    assert r.cost_usd == pytest.approx(r.tokens_in / 1e6 * 3 + r.tokens_out / 1e6 * 15)
    rows = await sql(
        "SELECT status, job_id, provider_id FROM ai_usage WHERE organization_id=$1", org
    )
    assert [(x["status"], x["job_id"], x["provider_id"]) for x in rows] == [("ok", "job-1", "a")]
    assert FakeAdapter.calls[0]["had_key"] is True  # credential reached the adapter
    assert any(ref.startswith("ai.route.code_fix@global::v") for ref in r.config_refs)


async def test_switching_provider_in_admin_applies_to_the_very_next_call():
    org, *_ = await make_org()
    await configure([model("m-a", "a"), model("m-b", "b")], route={"primary_model_id": "m-a"})
    assert (await get_gateway().complete(req(org))).provider_id == "a"
    await get_config().save(
        "ai.route.code_fix",
        Scope.GLOBAL,
        "",
        {"primary_model_id": "m-b"},
        comment="test-switch",
        actor=None,
    )
    assert (await get_gateway().complete(req(org))).provider_id == "b"  # no redeploy, no restart


async def test_outage_falls_back_automatically_and_records_both_attempts():
    org, *_ = await make_org()
    await configure(
        [model("m-a", "a", name="fail"), model("m-b", "b")],
        route={"primary_model_id": "m-a", "fallback_model_ids": ["m-b"]},
    )
    r = await get_gateway().complete(req(org))
    assert (r.provider_id, r.fell_back) == ("b", True)
    rows = await sql(
        "SELECT provider_id, status, error_class FROM ai_usage WHERE organization_id=$1 ORDER BY created_at",
        org,
    )
    assert [(x["provider_id"], x["status"]) for x in rows] == [("a", "error"), ("b", "ok")]
    assert rows[0]["error_class"] == "ProviderError"


async def test_hung_provider_times_out_then_falls_back():
    org, *_ = await make_org()
    await configure(
        [model("m-a", "a", name="hang"), model("m-b", "b")],
        route={"primary_model_id": "m-a", "fallback_model_ids": ["m-b"], "timeout_seconds": 1},
    )
    r = await asyncio.wait_for(get_gateway().complete(req(org)), timeout=10)
    assert (r.provider_id, r.fell_back) == ("b", True)


async def test_all_failing_raises_unavailable():
    org, *_ = await make_org()
    await configure(
        [model("m-a", "a", name="fail"), model("m-b", "b", name="fail")],
        route={"primary_model_id": "m-a", "fallback_model_ids": ["m-b"]},
    )
    with pytest.raises(AIUnavailable) as e:
        await get_gateway().complete(req(org))
    assert e.value.reason == "all_failed"


async def test_router_only_uses_models_with_the_required_capability_and_enabled():
    org, *_ = await make_org()
    cfg = get_config()
    await configure([model("text-only", "a"), model("vision", "b", caps=("text", "vision"))])
    await cfg.save(
        "ai.route.alt_text",
        Scope.GLOBAL,
        "",
        {"primary_model_id": "text-only", "fallback_model_ids": ["vision"]},
        comment="test-ai",
        actor=None,
    )
    r = await get_gateway().complete(
        req(org, task="alt_text")
    )  # alt_text needs vision: skip text-only silently
    assert (r.model_id, r.fell_back) == ("vision", True)
    await configure(
        [model("text-only", "a"), model("vision", "b", caps=("vision",), is_enabled=False)]
    )
    with pytest.raises(AIUnavailable) as e:
        await get_gateway().complete(req(org, task="alt_text"))
    assert e.value.reason == "no_eligible_model"
    await cfg.save("ai.route.alt_text", Scope.GLOBAL, "", {}, comment="test-cleanup", actor=None)


async def test_disabled_provider_is_skipped():
    org, *_ = await make_org()
    cfg = get_config()
    await cfg.save(
        "ai.providers",
        Scope.GLOBAL,
        "",
        {"items": [prov("a", is_enabled=False), prov("b")]},
        comment="test-ai",
        actor=None,
    )
    await cfg.save(
        "ai.models",
        Scope.GLOBAL,
        "",
        {"items": [model("m-a", "a"), model("m-b", "b")]},
        comment="test-ai",
        actor=None,
    )
    await cfg.save(
        "ai.route.code_fix",
        Scope.GLOBAL,
        "",
        {"primary_model_id": "m-a", "fallback_model_ids": ["m-b"]},
        comment="test-ai",
        actor=None,
    )
    assert (await get_gateway().complete(req(org))).provider_id == "b"


async def test_per_org_and_per_plan_routing_overrides():
    a, *_ = await make_org()
    b, *_ = await make_org()
    await configure([model("m-a", "a"), model("m-b", "b")], route={"primary_model_id": "m-a"})
    await get_config().save(
        "ai.route.code_fix",
        Scope.ORG,
        str(b),
        {"primary_model_id": "m-b"},
        comment="test-org",
        actor=None,
    )
    assert (await get_gateway().complete(req(a))).provider_id == "a"
    assert (await get_gateway().complete(req(b))).provider_id == "b"
    await get_config().save(
        "ai.route.code_fix",
        Scope.PLAN,
        "ENTERPRISE",
        {"primary_model_id": "m-b"},
        comment="test-plan",
        actor=None,
    )
    assert (await get_gateway().complete(req(a, plan_id="ENTERPRISE"))).provider_id == "b"
    assert (await get_gateway().complete(req(a, plan_id="STARTER"))).provider_id == "a"


async def test_monthly_budget_stops_ai_for_that_org_only():
    a, *_ = await make_org()
    b, *_ = await make_org()
    await configure(
        [model("m-a", "a", input_cost_per_1m=1_000_000, output_cost_per_1m=1_000_000)],
        route={"primary_model_id": "m-a", "monthly_budget_usd": 0.0005},
    )
    await get_gateway().complete(req(a))  # costs well over the budget
    with pytest.raises(AIUnavailable) as e:
        await get_gateway().complete(req(a))
    assert e.value.reason == "budget_exceeded"
    assert (await get_gateway().complete(req(b))).provider_id == "a"


async def test_route_validation_rejects_duplicate_or_orphan_fallbacks():
    from a11y_core.config import GuardrailError

    cfg = get_config()
    for bad in (
        {"primary_model_id": "x", "fallback_model_ids": ["x"]},
        {"fallback_model_ids": ["x"]},
    ):
        with pytest.raises(GuardrailError):
            await cfg.save(
                "ai.route.code_fix", Scope.GLOBAL, "", bad, comment="test-bad", actor=None
            )


async def test_metering_rows_are_tenant_isolated_and_append_only():
    from a11y_core.db import tenant_session
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    a, *_ = await make_org()
    b, *_ = await make_org()
    await configure([model("m-a", "a")], route={"primary_model_id": "m-a"})
    await get_gateway().complete(req(b))
    async with tenant_session(a) as db:
        assert (await db.execute(text("SELECT count(*) FROM ai_usage"))).scalar_one() == 0
    for stmt in ("UPDATE ai_usage SET cost_usd = 0", "DELETE FROM ai_usage"):
        with pytest.raises(DBAPIError):
            async with tenant_session(b) as db:
                await db.execute(text(stmt))
