"""Declared settings. Add new ones here (or beside the feature that owns them, imported from
here); the admin API and forms pick them up automatically."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .registry import GuardrailError, Scope, Secret, SettingDef, register

# --- billing ------------------------------------------------------------------------------


class TrialPolicy(BaseModel):
    length_days: int = Field(14, ge=1, le=365, description="Length of a new organisation's trial")
    plan_id: str = Field(
        "TRIAL", min_length=1, max_length=64, description="Plan active during the trial"
    )
    grace_days: int = Field(
        0, ge=0, le=90, description="Extra days of full access after the trial ends"
    )
    after_expiry: Literal["LOCKED_READ_ONLY"] = "LOCKED_READ_ONLY"
    reminder_days_before: list[int] = Field(default_factory=lambda: [3, 1])


register(
    SettingDef(
        key="billing.trial",
        model=TrialPolicy,
        default=TrialPolicy(),
        description="Trial length, plan, grace period and what happens at expiry.",
        scopes=frozenset({Scope.GLOBAL, Scope.ORG}),  # org scope = a negotiated longer trial
        tags=("billing",),
    )
)

# --- AI providers, models, task routing (PROJECT_PLAN 3.11.2) --------------------------------

PROVIDER_TYPES = (
    "openai",
    "azure_openai",
    "anthropic",
    "bedrock",
    "gemini",
    "deepseek",
    "mistral",
    "groq",
    "openai_compatible",
    "fake",
)
CAPABILITIES = ("text", "vision", "json", "tools")
# Tasks are code (a feature must exist to use one); which model serves them is data.
AI_TASKS: dict[str, tuple[str, ...]] = {
    "code_fix": ("text",),
    "vision_audit": ("vision",),
    "alt_text": ("vision",),
    "mathml": ("text",),
    "ad_script": ("vision",),
    "vpat_narrative": ("text",),
    "focus_anomaly": ("text",),
    "doc_layout": ("vision",),
}


class DataPolicy(BaseModel):
    zero_retention: bool = False
    processing_regions: list[str] = Field(default_factory=list, description="e.g. ['us','eu','in']")
    gov_approved: bool = False


class AIProvider(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    type: Literal[PROVIDER_TYPES]  # type: ignore[valid-type]
    display_name: str = Field(max_length=100)
    base_url: str | None = Field(None, max_length=500)
    region: str | None = Field(None, max_length=50)
    api_key: Secret = Field(default_factory=Secret)
    # Provider-specific: azure api_version/deployment, bedrock role arn, ...
    options: dict[str, str] = Field(default_factory=dict)
    data_policy: DataPolicy = Field(default_factory=DataPolicy)
    is_enabled: bool = True


class AIProviders(BaseModel):
    items: list[AIProvider] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self):
        ids = [p.id for p in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Provider ids must be unique.")
        return self


class AIModel(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,59}$")
    provider_id: str
    model_name: str = Field(max_length=200, description="The provider's own model/deployment name")
    capabilities: list[Literal[CAPABILITIES]] = Field(default_factory=lambda: ["text"])  # type: ignore[valid-type]
    context_window: int = Field(8192, ge=1)
    input_cost_per_1m: float = Field(0, ge=0, description="USD per million input tokens")
    output_cost_per_1m: float = Field(0, ge=0)
    is_enabled: bool = True


class AIModels(BaseModel):
    items: list[AIModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self):
        ids = [m.id for m in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Model ids must be unique.")
        return self


class AIRoute(BaseModel):
    """Which model serves a task, and what to try if it fails."""

    primary_model_id: str | None = None  # None => task not configured => deterministic only
    fallback_model_ids: list[str] = Field(default_factory=list, max_length=5)
    temperature: float = Field(0.0, ge=0, le=2)
    max_tokens: int = Field(1024, ge=1, le=200_000)
    timeout_seconds: int = Field(60, ge=1, le=900)
    monthly_budget_usd: float | None = Field(
        None, ge=0, description="Cap per organisation; empty = none"
    )

    @model_validator(mode="after")
    def _chain(self):
        chain = [m for m in [self.primary_model_id, *self.fallback_model_ids] if m]
        if len(chain) != len(set(chain)):
            raise ValueError("A model can appear only once in a route.")
        if self.fallback_model_ids and not self.primary_model_id:
            raise ValueError("Choose a primary model before adding fallbacks.")
        return self


def _provider_guard(new: AIProviders, prev: AIProviders) -> None:
    if any(p.type == "fake" for p in new.items):
        from ..settings import get_settings

        if get_settings().env == "production":
            raise GuardrailError("The fake provider cannot be configured in production.")


register(
    SettingDef(
        key="ai.providers",
        model=AIProviders,
        default=AIProviders(),
        description="AI providers and their credentials (write-only). Add a row to add a provider.",
        guard=_provider_guard,
        high_risk=True,
        owner_role="AI_OPS",
        tags=("ai",),
    )
)
register(
    SettingDef(
        key="ai.models",
        model=AIModels,
        default=AIModels(),
        description="Model catalogue: capabilities and prices (prices drive FinOps cost reports).",
        owner_role="AI_OPS",
        tags=("ai",),
    )
)
for _task, _needs in AI_TASKS.items():
    register(
        SettingDef(
            key=f"ai.route.{_task}",
            model=AIRoute,
            default=AIRoute(),
            description=f"Primary model and fallback chain for '{_task}' (needs: {', '.join(_needs)}).",
            scopes=frozenset({Scope.GLOBAL, Scope.PLAN, Scope.ORG}),
            owner_role="AI_OPS",
            tags=("ai", "routing"),
        )
    )
