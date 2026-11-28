"""Adapter for every provider that speaks the OpenAI chat-completions wire format:
DeepSeek, OpenAI, Azure OpenAI and any ``openai_compatible`` endpoint (vLLM, Ollama, OpenRouter...).

Differences are data, not code: base URL, auth header and URL shape per provider *type*, plus
per-provider ``options`` an admin can set (see ``OPTIONS`` below). Failures become
``ProviderError`` (the gateway then falls back); error text never includes request or response
bodies, so prompts and credentials cannot leak into logs.
"""

from __future__ import annotations

import httpx

from ..config.definitions import AIModel, AIProvider
from .types import CallParams, LLMRequest, ProviderAdapter, ProviderError, RawResult

DEFAULT_BASE_URL = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
}
DEFAULT_AZURE_API_VERSION = "2024-10-21"

# Provider ``options`` an admin may set (all optional, all strings):
#   api_version        Azure only. Default 2024-10-21.
#   token_param        "max_tokens" (default) or "max_completion_tokens" (Azure/OpenAI o-series).
#   omit_temperature   "true" for models that reject a temperature (o-series, deepseek-reasoner).
OPTIONS = ("api_version", "token_param", "omit_temperature")


def build_url(provider: AIProvider, model: AIModel) -> str:
    base = (provider.base_url or DEFAULT_BASE_URL.get(provider.type, "")).rstrip("/")
    if not base:
        raise ProviderError("provider has no base URL")
    if provider.type == "azure_openai":
        version = provider.options.get("api_version") or DEFAULT_AZURE_API_VERSION
        # For Azure the "model name" is the *deployment* name.
        return (
            f"{base}/openai/deployments/{model.model_name}/chat/completions?api-version={version}"
        )
    return f"{base}/chat/completions"


def build_headers(provider: AIProvider) -> dict[str, str]:
    key = provider.api_key.value() if provider.api_key.is_set else ""
    if provider.type == "azure_openai":
        return {"api-key": key, "content-type": "application/json"}
    h = {"content-type": "application/json"}
    if key:  # self-hosted endpoints may not need one
        h["authorization"] = f"Bearer {key}"
    return h


def build_body(provider: AIProvider, model: AIModel, params: CallParams, req: LLMRequest) -> dict:
    body: dict = {
        "messages": [{"role": m.role, "content": m.content} for m in req.messages],
        "stream": False,
    }
    if provider.type != "azure_openai":
        body["model"] = model.model_name
    if provider.options.get("omit_temperature", "").lower() != "true":
        body["temperature"] = params.temperature
    body[provider.options.get("token_param") or "max_tokens"] = params.max_tokens
    if req.json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


class OpenAIChatAdapter(ProviderAdapter):
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport  # tests inject httpx.MockTransport

    async def complete(
        self, provider: AIProvider, model: AIModel, params: CallParams, req: LLMRequest
    ) -> RawResult:
        url = build_url(provider, model)
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(params.timeout_seconds, connect=10),
                follow_redirects=False,  # a redirect could carry the key to another host
            ) as client:
                r = await client.post(
                    url,
                    headers=build_headers(provider),
                    json=build_body(provider, model, params, req),
                )
        except httpx.HTTPError as e:
            raise ProviderError(f"network error: {type(e).__name__}") from None
        if r.status_code in (401, 403):
            raise ProviderError("authentication failed (check the API key)")
        if r.status_code == 404:
            raise ProviderError("not found (check base URL, deployment or model name)")
        if r.status_code == 429:
            raise ProviderError("rate limited")
        if r.status_code >= 400:
            raise ProviderError(f"provider returned HTTP {r.status_code}")
        try:
            data = r.json()
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("unexpected response format") from None
        if choice.get("finish_reason") == "content_filter" and not text:
            raise ProviderError("blocked by the provider's content filter")
        return RawResult(
            text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        )

    async def test_connection(self, provider: AIProvider, model: AIModel | None = None) -> None:
        if model is None:
            raise ProviderError("add a model for this provider before testing")
        from .types import Message

        await self.complete(
            provider,
            model,
            CallParams(0.0, 8, 20),
            LLMRequest("code_fix", [Message("user", "Reply with the word ok.")], org_id=None),
        )
