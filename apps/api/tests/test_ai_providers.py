"""DeepSeek / Azure OpenAI / OpenAI adapters (HTTP mocked) and enterprise BYOK."""

import json

import httpx
import pytest
from a11y_core.ai import AIUnavailable, LLMGateway, LLMRequest, Message
from a11y_core.ai.adapters import ADAPTERS
from a11y_core.ai.openai_chat import OpenAIChatAdapter
from a11y_core.config import GuardrailError, Scope, get_config
from a11y_core.config.definitions import ByokConfig

from .conftest import make_org, sql, super_admin_headers
from .test_ai_gateway import configure, model, req
from .test_ai_gateway import prov as fake_prov
from .test_billing import auth
from .test_settings import _clean  # noqa: F401

KEY = "sk-test-0123456789abcdef-WXYZ"


def ok_body(text="hello", tin=11, tout=7):
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": tin, "completion_tokens": tout},
    }


class Recorder:
    def __init__(self, handler=None):
        self.requests: list[httpx.Request] = []
        self.handler = handler or (lambda r: httpx.Response(200, json=ok_body()))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def adapter(self) -> OpenAIChatAdapter:
        return OpenAIChatAdapter(transport=httpx.MockTransport(self))


def gw(**adapters) -> LLMGateway:
    return LLMGateway(adapters={**ADAPTERS, **adapters})


def secret(v=KEY):
    return {"$secret": True, "plaintext": v}


def real_provider(pid, typ, **kw):
    return {"id": pid, "type": typ, "display_name": pid, "api_key": secret(), **kw}


@pytest.fixture(autouse=True)
async def _byok_clean():
    yield
    await sql("DELETE FROM setting_versions WHERE key='ai.byok'")
    await sql("DELETE FROM ai_usage WHERE task_key='code_fix'")


# --- wire format -------------------------------------------------------------------------------


async def test_deepseek_request_and_response_shape():
    org, *_ = await make_org()
    rec = Recorder()
    await get_config().save(
        "ai.providers",
        Scope.GLOBAL,
        "",
        {"items": [real_provider("ds", "deepseek")]},
        comment="test-ds",
        actor=None,
    )
    await get_config().save(
        "ai.models",
        Scope.GLOBAL,
        "",
        {
            "items": [
                model(
                    "ds-chat",
                    "ds",
                    "deepseek-chat",
                    ("text", "json"),
                    input_cost_per_1m=0.27,
                    output_cost_per_1m=1.1,
                )
            ]
        },
        comment="test-ds",
        actor=None,
    )
    await get_config().save(
        "ai.route.code_fix",
        Scope.GLOBAL,
        "",
        {"primary_model_id": "ds-chat", "temperature": 0.2, "max_tokens": 300},
        comment="test-ds",
        actor=None,
    )
    r = await gw(deepseek=rec.adapter()).complete(req(org, json_mode=True))
    sent = rec.requests[0]
    assert str(sent.url) == "https://api.deepseek.com/chat/completions"
    assert sent.headers["authorization"] == f"Bearer {KEY}"  # decrypted server-side only
    body = json.loads(sent.content)
    assert (
        body["model"] == "deepseek-chat"
        and body["temperature"] == 0.2
        and body["max_tokens"] == 300
    )
    assert body["response_format"] == {"type": "json_object"} and body["stream"] is False
    assert (r.text, r.tokens_in, r.tokens_out, r.provider_id) == ("hello", 11, 7, "ds")
    assert r.cost_usd == pytest.approx(11 / 1e6 * 0.27 + 7 / 1e6 * 1.1)


async def test_azure_openai_uses_deployment_url_api_key_header_and_options():
    org, *_ = await make_org()
    rec = Recorder()
    az = real_provider(
        "az",
        "azure_openai",
        base_url="https://acme.openai.azure.com/",
        options={
            "api_version": "2025-01-01-preview",
            "token_param": "max_completion_tokens",
            "omit_temperature": "true",
        },
    )
    await get_config().save(
        "ai.providers", Scope.GLOBAL, "", {"items": [az]}, comment="test-az", actor=None
    )
    await get_config().save(
        "ai.models",
        Scope.GLOBAL,
        "",
        {"items": [model("gpt", "az", "my-gpt4o-deployment", ("text", "vision"))]},
        comment="test-az",
        actor=None,
    )
    await get_config().save(
        "ai.route.alt_text",
        Scope.GLOBAL,
        "",
        {"primary_model_id": "gpt"},
        comment="test-az",
        actor=None,
    )
    await gw(azure_openai=rec.adapter()).complete(req(org, task="alt_text"))
    sent = rec.requests[0]
    assert (
        str(sent.url)
        == "https://acme.openai.azure.com/openai/deployments/my-gpt4o-deployment/chat/completions?api-version=2025-01-01-preview"
    )
    assert sent.headers["api-key"] == KEY and "authorization" not in sent.headers
    body = json.loads(sent.content)
    assert (
        "model" not in body
        and "temperature" not in body
        and "max_completion_tokens" in body
        and "max_tokens" not in body
    )
    await sql("DELETE FROM ai_usage WHERE task_key='alt_text'")
    await get_config().save(
        "ai.route.alt_text", Scope.GLOBAL, "", {}, comment="test-az", actor=None
    )


async def test_deepseek_cannot_serve_vision_tasks_so_the_router_skips_it():
    org, *_ = await make_org()
    await get_config().save(
        "ai.providers",
        Scope.GLOBAL,
        "",
        {"items": [real_provider("ds", "deepseek"), fake_prov("f")]},
        comment="test-v",
        actor=None,
    )
    await get_config().save(
        "ai.models",
        Scope.GLOBAL,
        "",
        {
            "items": [
                model("ds", "ds", "deepseek-chat", ("text",)),
                model("fv", "f", "ok", ("vision",)),
            ]
        },
        comment="test-v",
        actor=None,
    )
    await get_config().save(
        "ai.route.alt_text",
        Scope.GLOBAL,
        "",
        {"primary_model_id": "ds", "fallback_model_ids": ["fv"]},
        comment="test-v",
        actor=None,
    )
    r = await gw(deepseek=Recorder().adapter()).complete(req(org, task="alt_text"))
    assert (r.provider_id, r.fell_back) == ("f", True)
    await sql("DELETE FROM ai_usage WHERE task_key='alt_text'")
    await get_config().save("ai.route.alt_text", Scope.GLOBAL, "", {}, comment="test-v", actor=None)


@pytest.mark.parametrize(
    "status,detail",
    [
        (401, "authentication"),
        (403, "authentication"),
        (404, "not found"),
        (429, "rate limited"),
        (500, "HTTP 500"),
    ],
)
async def test_http_errors_become_provider_errors_without_leaking_secrets(status, detail):
    from a11y_core.ai import ProviderError
    from a11y_core.ai.types import CallParams
    from a11y_core.config.definitions import AIModel, AIProvider

    rec = Recorder(lambda r: httpx.Response(status, text=f"echo of your key {KEY} and prompt"))
    p = AIProvider.model_validate(
        {
            "id": "ds",
            "type": "deepseek",
            "display_name": "d",
            "api_key": {"$secret": True, "plaintext": None},
        }
    )
    m = AIModel(id="m", provider_id="ds", model_name="deepseek-chat")
    with pytest.raises(ProviderError) as e:
        await rec.adapter().complete(
            p,
            m,
            CallParams(0, 10, 5),
            LLMRequest("code_fix", [Message("user", "secret prompt")], org_id=None),
        )
    assert (
        detail in str(e.value) and KEY not in str(e.value) and "secret prompt" not in str(e.value)
    )


async def test_garbage_response_and_network_failure_fall_back_to_the_next_provider():
    org, *_ = await make_org()
    bad = Recorder(lambda r: httpx.Response(200, json={"unexpected": True}))
    await get_config().save(
        "ai.providers",
        Scope.GLOBAL,
        "",
        {"items": [real_provider("ds", "deepseek"), fake_prov("f")]},
        comment="test-fb",
        actor=None,
    )
    await get_config().save(
        "ai.models",
        Scope.GLOBAL,
        "",
        {"items": [model("ds", "ds", "deepseek-chat"), model("fm", "f", "ok")]},
        comment="test-fb",
        actor=None,
    )
    await get_config().save(
        "ai.route.code_fix",
        Scope.GLOBAL,
        "",
        {"primary_model_id": "ds", "fallback_model_ids": ["fm"]},
        comment="test-fb",
        actor=None,
    )
    r = await gw(deepseek=bad.adapter()).complete(req(org))
    assert (r.provider_id, r.fell_back) == ("f", True)

    def boom(request):
        raise httpx.ConnectError("down")

    r = await gw(deepseek=Recorder(boom).adapter()).complete(req(org))
    assert r.provider_id == "f"


# --- admin test connection -----------------------------------------------------------------------


async def test_admin_test_connection_endpoint(client, monkeypatch):
    h = super_admin_headers()
    ok = Recorder()
    monkeypatch.setitem(ADAPTERS, "deepseek", ok.adapter())
    await get_config().save(
        "ai.providers",
        Scope.GLOBAL,
        "",
        {"items": [real_provider("ds", "deepseek")]},
        comment="test-t",
        actor=None,
    )
    r = await client.post("/admin/ai/providers/ds/test", headers=h, json={})
    assert r.json() == {"ok": False, "detail": "Add a model for this provider first, then test."}
    await get_config().save(
        "ai.models",
        Scope.GLOBAL,
        "",
        {"items": [model("m", "ds", "deepseek-chat")]},
        comment="test-t",
        actor=None,
    )
    r = await client.post("/admin/ai/providers/ds/test", headers=h, json={})
    assert r.json()["ok"] is True and r.json()["model_id"] == "m"
    assert json.loads(ok.requests[0].content)["max_tokens"] == 8  # a tiny, cheap call
    monkeypatch.setitem(ADAPTERS, "deepseek", Recorder(lambda r: httpx.Response(401)).adapter())
    r = await client.post("/admin/ai/providers/ds/test", headers=h, json={})
    assert r.json()["ok"] is False and "authentication" in r.json()["detail"]
    assert (
        await client.post("/admin/ai/providers/nope/test", headers=h, json={})
    ).status_code == 404
    listing = (await client.get("/admin/ai/providers", headers=h)).json()
    assert listing[0]["key_set"] is True and KEY not in json.dumps(listing)


# --- BYOK: validation ----------------------------------------------------------------------------


def byok(providers, models, order, **kw):
    return {"enabled": True, "providers": providers, "models": models, "model_order": order, **kw}


@pytest.mark.parametrize(
    "prov,msg",
    [
        (
            {
                "id": "x",
                "type": "openai_compatible",
                "display_name": "x",
                "base_url": "https://internal.example",
            },
            "not available",
        ),
        (
            {
                "id": "x",
                "type": "azure_openai",
                "display_name": "x",
                "base_url": "http://acme.openai.azure.com",
            },
            "resource address",
        ),
        (
            {
                "id": "x",
                "type": "azure_openai",
                "display_name": "x",
                "base_url": "https://169.254.169.254",
            },
            "resource address",
        ),
        (
            {
                "id": "x",
                "type": "azure_openai",
                "display_name": "x",
                "base_url": "https://evil.com/.openai.azure.com",
            },
            "resource address",
        ),
        (
            {
                "id": "x",
                "type": "azure_openai",
                "display_name": "x",
                "base_url": "https://acme.openai.azure.com.evil.com",
            },
            "resource address",
        ),
        (
            {
                "id": "x",
                "type": "azure_openai",
                "display_name": "x",
                "base_url": "https://u:p@acme.openai.azure.com",
            },
            "resource address",
        ),
        (
            {
                "id": "x",
                "type": "deepseek",
                "display_name": "x",
                "base_url": "https://evil.example",
            },
            "fixed address",
        ),
        (
            {"id": "x", "type": "deepseek", "display_name": "x", "options": {"headers": "x"}},
            "Unknown option",
        ),
    ],
)
def test_byok_guard_rejects_unsafe_providers(prov, msg):
    m = model("m", "x")
    with pytest.raises(ValueError, match=msg):
        ByokConfig.model_validate(byok([prov], [m], ["m"]))


def test_byok_guard_accepts_valid_azure_and_checks_references():
    ok = real_provider("az", "azure_openai", base_url="https://acme.openai.azure.com")
    ByokConfig.model_validate(byok([ok], [model("m", "az")], ["m"]))
    with pytest.raises(ValueError, match="at least one model"):
        ByokConfig.model_validate(
            {"enabled": True, "providers": [ok], "models": [model("m", "az")]}
        )
    with pytest.raises(ValueError, match="not in your list"):
        ByokConfig.model_validate(byok([ok], [model("m", "ghost")], ["m"]))
    with pytest.raises(ValueError, match="model_order"):
        ByokConfig.model_validate(byok([ok], [model("m", "az")], ["nope"]))


async def test_byok_is_org_scoped_only():
    with pytest.raises(GuardrailError):
        await get_config().save("ai.byok", Scope.GLOBAL, "", {}, comment="test-x", actor=None)


# --- BYOK: gateway behaviour ---------------------------------------------------------------------


async def own_ds(org, **kw):
    cfg = byok(
        [real_provider("mine", "deepseek")],
        [model("mine-chat", "mine", "deepseek-chat")],
        ["mine-chat"],
        **kw,
    )
    await get_config().save("ai.byok", Scope.ORG, str(org), cfg, comment="test-byok", actor=None)


async def test_enterprise_org_uses_its_own_key_first_and_is_metered_as_byok():
    org, *_ = await make_org(plan="ENTERPRISE")
    await configure([model("m-a", "a")], route={"primary_model_id": "m-a"})
    await own_ds(org)
    rec = Recorder()
    r = await gw(deepseek=rec.adapter()).complete(req(org, job_id="j1"))
    assert (r.provider_id, r.byok, r.fell_back) == ("mine", True, False)
    assert rec.requests[0].headers["authorization"] == f"Bearer {KEY}"
    rows = await sql("SELECT byok, provider_id FROM ai_usage WHERE organization_id=$1", org)
    assert [(x["byok"], x["provider_id"]) for x in rows] == [(True, "mine")]


async def test_non_enterprise_org_cannot_use_byok_even_if_a_value_exists():
    org, *_ = await make_org(plan="GROWTH")
    await configure([model("m-a", "a")], route={"primary_model_id": "m-a"})
    await own_ds(org)  # e.g. left over from before a downgrade, or written by a Super Admin
    rec = Recorder()
    r = await gw(deepseek=rec.adapter()).complete(req(org))
    assert (r.provider_id, r.byok) == ("a", False) and rec.requests == []


async def test_downgrade_stops_byok_on_the_next_call():
    org, *_ = await make_org(plan="ENTERPRISE")
    await configure([model("m-a", "a")], route={"primary_model_id": "m-a"})
    await own_ds(org)
    g = gw(deepseek=Recorder().adapter())
    assert (await g.complete(req(org))).byok is True
    await sql("UPDATE subscriptions SET plan_id='GROWTH' WHERE organization_id=$1", org)
    assert (await g.complete(req(org))).byok is False


async def test_byok_failure_without_fallback_does_not_spend_platform_ai():
    org, *_ = await make_org(plan="ENTERPRISE")
    await configure([model("m-a", "a")], route={"primary_model_id": "m-a"})
    await own_ds(org)
    with pytest.raises(AIUnavailable) as e:
        await gw(deepseek=Recorder(lambda r: httpx.Response(500)).adapter()).complete(req(org))
    assert e.value.reason == "all_failed"
    assert [
        x["provider_id"]
        for x in await sql("SELECT provider_id FROM ai_usage WHERE organization_id=$1", org)
    ] == ["mine"]


async def test_byok_failure_with_fallback_uses_platform_and_marks_fell_back():
    org, *_ = await make_org(plan="ENTERPRISE")
    await configure([model("m-a", "a")], route={"primary_model_id": "m-a"})
    await own_ds(org, fallback_to_platform=True)
    r = await gw(deepseek=Recorder(lambda r: httpx.Response(429)).adapter()).complete(req(org))
    assert (r.provider_id, r.byok, r.fell_back) == ("a", False, True)


async def test_byok_works_for_tasks_the_platform_has_not_configured_and_respects_only_tasks():
    org, *_ = await make_org(plan="ENTERPRISE")
    await configure([model("m-a", "a")])  # no platform route for code_fix at all
    await own_ds(org, only_tasks=["code_fix"])
    g = gw(deepseek=Recorder().adapter())
    assert (await g.complete(req(org))).byok is True
    with pytest.raises(
        AIUnavailable
    ) as e:  # mathml is not covered by BYOK and has no platform route
        await g.complete(LLMRequest("mathml", [Message("user", "x")], org_id=org))
    assert e.value.reason == "not_configured"


async def test_byok_usage_does_not_count_against_the_platform_budget():
    org, *_ = await make_org(plan="ENTERPRISE")
    await configure(
        [model("m-a", "a", input_cost_per_1m=1_000_000, output_cost_per_1m=1_000_000)],
        route={"primary_model_id": "m-a", "monthly_budget_usd": 0.0005},
    )
    cfg = byok(
        [real_provider("mine", "deepseek")],
        [
            model(
                "mine-chat",
                "mine",
                "deepseek-chat",
                input_cost_per_1m=1_000_000,
                output_cost_per_1m=1_000_000,
            )
        ],
        ["mine-chat"],
    )
    await get_config().save(
        "ai.byok",
        Scope.ORG,
        str(org),
        {**cfg, "fallback_to_platform": True},
        comment="test-b",
        actor=None,
    )
    g = gw(deepseek=Recorder().adapter())
    for _ in range(3):  # BYOK spend is far above the platform budget but must not trip it
        assert (await g.complete(req(org))).byok is True
    # now BYOK fails, platform budget is untouched, so the fallback can serve
    r = await gw(deepseek=Recorder(lambda r: httpx.Response(500)).adapter()).complete(req(org))
    assert (r.provider_id, r.byok) == ("a", False)


# --- BYOK: org admin API -----------------------------------------------------------------------


async def test_org_api_not_eligible_on_lower_plans(client):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    r = await client.get("/org/ai", headers=h)
    assert r.json()["eligible"] is False and "value" not in r.json()
    put = await client.put("/org/ai", headers=h, json={"value": {}})
    assert put.status_code == 402 and put.json()["code"] == "feature_not_in_plan"
    assert (
        await client.post("/org/ai/test", headers=h, json={"provider_id": "x"})
    ).status_code == 402


async def test_org_api_members_cannot_manage_ai_accounts(client):
    org, user, _ = await make_org(plan="ENTERPRISE", role="STANDARD_USER")
    assert (
        await client.get("/org/ai", headers=auth(org, user, "STANDARD_USER"))
    ).status_code == 403


async def test_enterprise_admin_saves_key_write_only_tests_it_and_sees_usage(client, monkeypatch):
    org, user, _ = await make_org(plan="ENTERPRISE")
    h = auth(org, user)
    value = byok(
        [real_provider("mine", "deepseek")],
        [model("mine-chat", "mine", "deepseek-chat")],
        ["mine-chat"],
    )
    r = await client.put("/org/ai", headers=h, json={"value": value})
    assert r.status_code == 200
    got = await client.get("/org/ai", headers=h)
    txt = got.text
    assert KEY not in txt and '"ct"' not in txt and '"plaintext": "' not in txt
    assert got.json()["value"]["providers"][0]["api_key"] == {
        "$secret": True,
        "set": True,
        "hint": "••••WXYZ",
    }
    assert got.json()["eligible"] and got.json()["schema"]["properties"]["providers"]
    # re-saving without the key keeps it
    value["providers"][0]["api_key"] = {"$secret": True}
    assert (await client.put("/org/ai", headers=h, json={"value": value})).status_code == 200
    rec = Recorder()
    monkeypatch.setitem(ADAPTERS, "deepseek", rec.adapter())
    t = await client.post("/org/ai/test", headers=h, json={"provider_id": "mine"})
    assert t.json()["ok"] is True and rec.requests[0].headers["authorization"] == f"Bearer {KEY}"
    assert (
        await client.post("/org/ai/test", headers=h, json={"provider_id": "ghost"})
    ).status_code == 404


async def test_org_api_rejects_ssrf_attempts_with_a_field_error(client):
    org, user, _ = await make_org(plan="ENTERPRISE")
    bad = byok(
        [
            {
                "id": "x",
                "type": "azure_openai",
                "display_name": "x",
                "base_url": "http://169.254.169.254/latest",
            }
        ],
        [model("m", "x")],
        ["m"],
    )
    r = await client.put("/org/ai", headers=auth(org, user), json={"value": bad})
    assert r.status_code == 422 and "resource address" in r.json()["detail"]


async def test_orgs_cannot_see_or_use_each_others_keys(client):
    a, ua, _ = await make_org(plan="ENTERPRISE")
    b, ub, _ = await make_org(plan="ENTERPRISE")
    await own_ds(a)
    assert (await client.get("/org/ai", headers=auth(b, ub))).json()["value"]["providers"] == []
    assert (
        await client.post("/org/ai/test", headers=auth(b, ub), json={"provider_id": "mine"})
    ).status_code == 404
    await configure([model("m-a", "a")], route={"primary_model_id": "m-a"})
    assert (await gw(deepseek=Recorder().adapter()).complete(req(b))).byok is False


# --- quick add --------------------------------------------------------------------------------


async def test_quick_add_deepseek_then_azure_builds_routing_and_serves_requests(client):
    h = super_admin_headers()
    org, *_ = await make_org()
    r = await client.post(
        "/admin/ai/quick-add",
        headers=h,
        json={
            "preset": "deepseek",
            "api_key": KEY,
            "use_for_tasks": ["code_fix", "alt_text"],
            "comment": "test-qa",
        },
    )
    assert r.status_code == 200
    assert (
        r.json()["routed_tasks"] == ["code_fix"] and r.json()["skipped"][0]["task"] == "alt_text"
    )  # no vision
    r = await client.post(
        "/admin/ai/quick-add",
        headers=h,
        json={
            "preset": "azure_openai",
            "api_key": "azure-key-0123456789",
            "endpoint": "https://acme.openai.azure.com",
            "model_name": "gpt4o-prod",
            "use_for_tasks": ["code_fix", "alt_text"],
            "comment": "test-qa",
        },
    )
    assert r.json()["routed_tasks"] == ["code_fix", "alt_text"]
    cfg = get_config()
    route = (await cfg.effective("ai.route.code_fix")).value
    assert route.primary_model_id == "deepseek-deepseek-chat" and route.fallback_model_ids == [
        "azure-openai-gpt4o-prod"
    ]
    assert (
        await cfg.effective("ai.route.alt_text")
    ).value.primary_model_id == "azure-openai-gpt4o-prod"
    # DeepSeek is flagged as processing in China so regulated tenants can exclude it
    ds = next(p for p in (await cfg.effective("ai.providers")).value.items if p.id == "deepseek")
    assert ds.data_policy.processing_regions == ["cn"] and ds.api_key.value() == KEY
    # DeepSeek down -> Azure serves; both over the mocked wire
    azure = Recorder()
    g = gw(deepseek=Recorder(lambda q: httpx.Response(503)).adapter(), azure_openai=azure.adapter())
    out = await g.complete(req(org))
    assert (out.provider_id, out.fell_back) == ("azure-openai", True)
    assert azure.requests[0].url.path == "/openai/deployments/gpt4o-prod/chat/completions"
    # re-adding rotates the key without duplicating the provider
    await client.post(
        "/admin/ai/quick-add",
        headers=h,
        json={"preset": "deepseek", "api_key": "sk-rotated-0123456789", "comment": "test-qa"},
    )
    items = (await cfg.effective("ai.providers")).value.items
    assert [p.id for p in items].count("deepseek") == 1 and next(
        p for p in items if p.id == "deepseek"
    ).api_key.value() == "sk-rotated-0123456789"
    assert KEY not in (await client.get("/admin/settings/ai.providers", headers=h)).text


async def test_quick_add_validation(client):
    h = super_admin_headers()
    base = {"api_key": KEY, "comment": "test-qa"}
    r = await client.post(
        "/admin/ai/quick-add", headers=h, json={**base, "preset": "azure_openai", "model_name": "d"}
    )
    assert r.status_code == 422 and r.json()["field"] == "endpoint"
    r = await client.post(
        "/admin/ai/quick-add",
        headers=h,
        json={**base, "preset": "azure_openai", "endpoint": "https://a.openai.azure.com"},
    )
    assert r.status_code == 422 and r.json()["field"] == "model_name"
    r = await client.post(
        "/admin/ai/quick-add",
        headers=h,
        json={**base, "preset": "deepseek", "use_for_tasks": ["nope"]},
    )
    assert r.status_code == 422
    assert (
        await client.post("/admin/ai/quick-add", json={**base, "preset": "deepseek"})
    ).status_code == 401
