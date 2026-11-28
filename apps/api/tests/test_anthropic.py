"""Anthropic (Claude) adapter: wire format, error mapping, no secret leakage, fallback and the admin quick-add preset."""

import json

import httpx
import pytest
from a11y_core.ai import LLMGateway, LLMRequest, Message, ProviderError
from a11y_core.ai.adapters import ADAPTERS
from a11y_core.ai.anthropic import AnthropicAdapter
from a11y_core.ai.types import CallParams
from a11y_core.config import Scope, get_config
from a11y_core.config.definitions import AIModel, AIProvider

from .conftest import make_org, super_admin_headers
from .test_ai_gateway import model
from .test_settings import _clean  # noqa: F401  (autouse cleanup of test-* settings)

KEY = "sk-ant-test-0123456789abcdef-WXYZ"


def provider(**kw):
    from a11y_core.config.crypto import get_box

    # sealed exactly as the settings store would: only ciphertext, decrypted inside the adapter
    return AIProvider(
        id="anthropic",
        type="anthropic",
        display_name="Claude",
        api_key={"$secret": True, "ct": get_box().encrypt(KEY), "hint": KEY[-4:]},
        **kw,
    )


MODEL = AIModel(
    id="haiku",
    provider_id="anthropic",
    model_name="claude-haiku-5-5",
    capabilities=["text", "json"],
)
PARAMS = CallParams(0.2, 300, 30)


def reply(text="hello", tin=11, tout=7, **extra):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": tin, "output_tokens": tout},
        **extra,
    }


class Rec:
    def __init__(self, handler=None):
        self.requests: list[httpx.Request] = []
        self.handler = handler or (lambda r: httpx.Response(200, json=reply()))

    def __call__(self, request):
        self.requests.append(request)
        return self.handler(request)

    def adapter(self):
        return AnthropicAdapter(transport=httpx.MockTransport(self))


def request(**kw):
    return LLMRequest(
        "code_fix",
        [Message("system", "You fix accessibility problems."), Message("user", "fix my <img>")],
        org_id=None,
        **kw,
    )


async def test_request_shape_and_response():
    rec = Rec()
    out = await rec.adapter().complete(provider(), MODEL, PARAMS, request())
    sent = rec.requests[0]
    assert str(sent.url) == "https://api.anthropic.com/v1/messages"
    assert sent.headers["x-api-key"] == KEY and sent.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in sent.headers
    body = json.loads(sent.content)
    assert (
        body["model"] == "claude-haiku-5-5"
        and body["max_tokens"] == 300
        and body["temperature"] == 0.2
    )
    assert (
        body["system"] == "You fix accessibility problems."
    )  # system text is its own field, not a message
    assert body["messages"] == [{"role": "user", "content": "fix my <img>"}]
    assert (out.text, out.tokens_in, out.tokens_out) == ("hello", 11, 7)


async def test_json_mode_asks_for_json_and_non_text_blocks_are_ignored():
    rec = Rec(
        lambda r: httpx.Response(
            200,
            json={
                **reply(),
                "content": [
                    {"type": "thinking", "thinking": "..."},
                    {"type": "text", "text": '{"a":'},
                    {"type": "text", "text": "1}"},
                ],
            },
        )
    )
    out = await rec.adapter().complete(provider(), MODEL, PARAMS, request(json_mode=True))
    assert "valid JSON object" in json.loads(rec.requests[0].content)["system"]
    assert out.text == '{"a":1}'


async def test_options_can_pin_the_api_version_and_the_address():
    rec = Rec()
    await rec.adapter().complete(
        provider(
            options={"anthropic_version": "2024-01-01"}, base_url="https://llm-gateway.example.com/"
        ),
        MODEL,
        PARAMS,
        request(),
    )
    assert rec.requests[0].headers["anthropic-version"] == "2024-01-01"
    assert str(rec.requests[0].url) == "https://llm-gateway.example.com/v1/messages"


@pytest.mark.parametrize(
    "response,message",
    [
        (httpx.Response(401), "authentication failed"),
        (httpx.Response(403), "authentication failed"),
        (httpx.Response(404), "not found"),
        (httpx.Response(429), "rate limited"),
        (httpx.Response(529), "overloaded"),
        (httpx.Response(500), "overloaded"),
        (httpx.Response(400, text="invalid_request: your prompt was 'secret prompt'"), "HTTP 400"),
        (httpx.Response(200, json={"unexpected": True}), "unexpected response"),
        (httpx.Response(200, text="not json"), "unexpected response"),
        (httpx.Response(200, json=reply(text="", stop_reason="refusal")), "declined"),
    ],
)
async def test_failures_become_provider_errors_without_leaking_anything(response, message):
    with pytest.raises(ProviderError) as e:
        await Rec(lambda r: response).adapter().complete(provider(), MODEL, PARAMS, request())
    assert message in str(e.value)
    assert KEY not in str(e.value) and "secret prompt" not in str(e.value)


async def test_a_network_failure_is_a_provider_error():
    def boom(r):
        raise httpx.ConnectError("name resolution failed for api.anthropic.com with key " + KEY)

    with pytest.raises(ProviderError) as e:
        await Rec(boom).adapter().complete(provider(), MODEL, PARAMS, request())
    assert str(e.value) == "network error: ConnectError" and KEY not in str(e.value)


async def test_a_provider_without_a_key_does_not_call_out():
    rec = Rec()
    p = AIProvider(id="anthropic", type="anthropic", display_name="Claude")
    with pytest.raises(ProviderError, match="no API key"):
        await rec.adapter().complete(p, MODEL, PARAMS, request())
    assert rec.requests == []


async def test_test_connection_needs_a_model_and_sends_a_tiny_request():
    rec = Rec()
    with pytest.raises(ProviderError, match="add a model"):
        await rec.adapter().test_connection(provider(), None)
    await rec.adapter().test_connection(provider(), MODEL)
    assert json.loads(rec.requests[0].content)["max_tokens"] == 8


def test_the_gateway_knows_the_provider_type():
    assert isinstance(ADAPTERS["anthropic"], AnthropicAdapter)


async def test_claude_serves_requests_through_the_gateway_with_fallback_and_cost():
    org, *_ = await make_org()
    cfg = get_config()
    await cfg.save(
        "ai.providers",
        Scope.GLOBAL,
        "",
        {
            "items": [
                {
                    "id": "anthropic",
                    "type": "anthropic",
                    "display_name": "Claude",
                    "api_key": {"$secret": True, "plaintext": KEY},
                },
                {
                    "id": "f",
                    "type": "fake",
                    "display_name": "f",
                    "api_key": {"$secret": True, "plaintext": "fake-key-0123456789-ABCD"},
                },
            ]
        },
        comment="test-ant",
        actor=None,
    )
    await cfg.save(
        "ai.models",
        Scope.GLOBAL,
        "",
        {
            "items": [
                model(
                    "claude",
                    "anthropic",
                    "claude-haiku-5-5",
                    ("text", "json"),
                    input_cost_per_1m=1,
                    output_cost_per_1m=5,
                    tier="LIGHT",
                ),
                model("fake", "f", "ok"),
            ]
        },
        comment="test-ant",
        actor=None,
    )
    await cfg.save(
        "ai.route.code_fix",
        Scope.GLOBAL,
        "",
        {"primary_model_id": "claude", "fallback_model_ids": ["fake"]},
        comment="test-ant",
        actor=None,
    )

    good = Rec()
    out = await LLMGateway(adapters={**ADAPTERS, "anthropic": good.adapter()}).complete(
        LLMRequest("code_fix", [Message("user", "hi")], org_id=org)
    )
    assert (out.provider_id, out.fell_back, out.text) == ("anthropic", False, "hello")
    assert out.cost_usd == pytest.approx(11 / 1e6 * 1 + 7 / 1e6 * 5)

    down = Rec(lambda r: httpx.Response(529))
    out = await LLMGateway(adapters={**ADAPTERS, "anthropic": down.adapter()}).complete(
        LLMRequest("code_fix", [Message("user", "hi")], org_id=org)
    )
    assert (
        out.provider_id == "f" and out.fell_back is True
    )  # an overloaded Claude falls back, the caller never notices


async def test_quick_add_offers_claude(client):
    h = super_admin_headers()
    presets = (await client.get("/admin/ai/presets", headers=h)).json()["presets"]
    assert (
        presets["anthropic"]["label"] == "Anthropic (Claude)"
        and presets["anthropic"]["default_model"] == "claude-haiku-5-5"
    )
    r = await client.post(
        "/admin/ai/quick-add",
        headers=h,
        json={
            "preset": "anthropic",
            "api_key": KEY,
            "use_for_tasks": ["code_fix", "alt_text"],
            "comment": "test-ant",
        },
    )
    assert r.status_code == 200 and r.json()["routed_tasks"] == [
        "code_fix",
        "alt_text",
    ]  # Claude can see images, so vision tasks too
    p = next(
        x for x in (await get_config().effective("ai.providers")).value.items if x.id == "anthropic"
    )
    assert p.type == "anthropic" and p.api_key.value() == KEY
    assert KEY not in (await client.get("/admin/settings/ai.providers", headers=h)).text
