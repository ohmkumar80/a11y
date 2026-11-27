from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..config.definitions import AIModel, AIProvider


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMRequest:
    task: str  # a key of config.definitions.AI_TASKS
    messages: list[Message]
    org_id: object  # uuid.UUID; usage is metered and budgets enforced per organisation
    job_id: str | None = None
    plan_id: str | None = None  # lets plan-scoped routing overrides apply
    json_mode: bool = False


@dataclass(frozen=True)
class CallParams:
    temperature: float
    max_tokens: int
    timeout_seconds: int


@dataclass(frozen=True)
class RawResult:
    text: str
    tokens_in: int
    tokens_out: int


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider_id: str
    model_id: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    fell_back: bool  # True when a fallback served the request
    config_refs: list[str] = field(default_factory=list)


class ProviderError(Exception):
    """Any failure of one provider call (network, 5xx, rate limit, bad key). The gateway moves
    on to the next model in the chain."""


class AIUnavailable(Exception):
    """No model could serve the request. Callers MUST degrade to deterministic-only output;
    never silently ignore a tenant restriction (PROJECT_PLAN 3.11.2)."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason  # not_configured | no_eligible_model | all_failed | budget_exceeded


class ProviderAdapter:
    """One per provider *type* (API style). Adding a provider = a settings row; adding a new API
    style = one subclass registered in ``adapters.ADAPTERS``."""

    async def complete(
        self, provider: AIProvider, model: AIModel, params: CallParams, req: LLMRequest
    ) -> RawResult:  # pragma: no cover - interface
        raise NotImplementedError

    async def test_connection(self, provider: AIProvider) -> None:  # pragma: no cover
        raise NotImplementedError
