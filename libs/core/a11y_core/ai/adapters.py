"""Provider adapters by ``AIProvider.type``. Only ``fake`` exists today; the real ones
(openai / azure_openai / anthropic / bedrock / gemini / deepseek / openai_compatible ...) are
added here, ideally via LiteLLM (PROJECT_PLAN 3.11.2)."""

from __future__ import annotations

import asyncio

from ..config.definitions import AIModel, AIProvider
from .types import CallParams, LLMRequest, ProviderAdapter, ProviderError, RawResult


class FakeAdapter(ProviderAdapter):
    """Deterministic, offline. Behaviour is chosen by the model's ``model_name``:
    ``fail`` -> ProviderError, ``hang`` -> never returns (exercises timeouts), anything else
    echoes. Tests read ``FakeAdapter.calls`` to see which model really served a request."""

    calls: list[dict] = []

    async def complete(
        self, provider: AIProvider, model: AIModel, params: CallParams, req: LLMRequest
    ) -> RawResult:
        self.calls.append(
            {
                "provider": provider.id,
                "model": model.id,
                "task": req.task,
                # prove the credential was decrypted and handed over, without exposing it
                "had_key": provider.api_key.is_set,
            }
        )
        if model.model_name == "fail":
            raise ProviderError("simulated provider outage")
        if model.model_name == "hang":
            await asyncio.sleep(3600)
        prompt = " ".join(m.content for m in req.messages)
        out = f"[{provider.id}/{model.model_name}] {req.task}: {prompt[:60]}"
        return RawResult(out, tokens_in=max(1, len(prompt) // 4), tokens_out=max(1, len(out) // 4))

    async def test_connection(self, provider: AIProvider, model: AIModel | None = None) -> None:
        return None


def _build() -> dict[str, ProviderAdapter]:
    from .openai_chat import OpenAIChatAdapter

    chat = OpenAIChatAdapter()
    return {
        "fake": FakeAdapter(),
        # One wire format, five provider types (see openai_chat.py).
        "deepseek": chat,
        "openai": chat,
        "azure_openai": chat,
        "openai_compatible": chat,
    }


ADAPTERS: dict[str, ProviderAdapter] = _build()
