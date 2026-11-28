"""Adapter for Anthropic's Messages API (``type: anthropic``).

Same promises as the OpenAI-format adapter: failures become ``ProviderError`` so the gateway can fall back, error text
never includes request or response bodies (prompts and keys cannot leak into logs), and redirects are not followed
(a redirect could carry the key to another host)."""

from __future__ import annotations

import httpx

from ..config.definitions import AIModel, AIProvider
from .types import CallParams, LLMRequest, Message, ProviderAdapter, ProviderError, RawResult

DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_VERSION = "2023-06-01"
JSON_NOTE = "\n\nReply with one valid JSON object and nothing else: no prose and no code fences."


def build_body(model: AIModel, params: CallParams, req: LLMRequest) -> dict:
    system = "\n\n".join(m.content for m in req.messages if m.role == "system")
    if req.json_mode:
        system += JSON_NOTE
    body: dict = {
        "model": model.model_name,
        "max_tokens": params.max_tokens,
        "temperature": params.temperature,
        "messages": [
            {"role": m.role, "content": m.content} for m in req.messages if m.role != "system"
        ],
    }
    if system.strip():
        body["system"] = system.strip()
    return body


class AnthropicAdapter(ProviderAdapter):
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport  # tests inject httpx.MockTransport

    async def complete(
        self, provider: AIProvider, model: AIModel, params: CallParams, req: LLMRequest
    ) -> RawResult:
        if not provider.api_key.is_set:
            raise ProviderError("no API key is set for this provider")
        url = (provider.base_url or DEFAULT_BASE_URL).rstrip("/") + "/v1/messages"
        headers = {
            "x-api-key": provider.api_key.value(),
            "anthropic-version": provider.options.get("anthropic_version") or DEFAULT_VERSION,
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(params.timeout_seconds, connect=10),
                follow_redirects=False,
            ) as client:
                r = await client.post(url, headers=headers, json=build_body(model, params, req))
        except httpx.HTTPError as e:
            raise ProviderError(f"network error: {type(e).__name__}") from None
        if r.status_code in (401, 403):
            raise ProviderError("authentication failed (check the API key)")
        if r.status_code == 404:
            raise ProviderError("not found (check the model name)")
        if r.status_code == 429:
            raise ProviderError("rate limited")
        if r.status_code in (500, 502, 503, 529):
            raise ProviderError("the provider is overloaded or unavailable")
        if r.status_code >= 400:
            raise ProviderError(f"provider returned HTTP {r.status_code}")
        try:
            data = r.json()
            text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
            usage = data.get("usage") or {}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderError("unexpected response format") from None
        if not text and data.get("stop_reason") == "refusal":
            raise ProviderError("declined by the provider")
        return RawResult(
            text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        )

    async def test_connection(self, provider: AIProvider, model: AIModel | None = None) -> None:
        if model is None:
            raise ProviderError("add a model for this provider before testing")
        await self.complete(
            provider,
            model,
            CallParams(0.0, 8, 20),
            LLMRequest("code_fix", [Message("user", "Reply with the word ok.")], org_id=None),
        )
