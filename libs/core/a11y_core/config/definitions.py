"""Declared settings. Add new ones here (or beside the feature that owns them, imported from
here); the admin API and forms pick them up automatically."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

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


# --- Enterprise bring-your-own-key (BYOK) -------------------------------------------------------
# An Enterprise organisation admin may use their own AI accounts. Because a tenant is NOT trusted
# the way a platform admin is, this setting is restricted: only provider types with a fixed or
# allow-listed host (so a tenant cannot make our servers call arbitrary URLs: SSRF), only known
# options, and a hard cap on size. The same guard applies whoever writes it.

BYOK_TYPES = ("openai", "azure_openai", "deepseek")
AZURE_HOSTS = (".openai.azure.com", ".cognitiveservices.azure.com")
ADAPTER_OPTIONS = ("api_version", "token_param", "omit_temperature")


class ByokConfig(BaseModel):
    enabled: bool = Field(False, description="Use this organisation's own AI accounts.")
    providers: list[AIProvider] = Field(default_factory=list, max_length=3)
    models: list[AIModel] = Field(default_factory=list, max_length=10)
    model_order: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Model ids to try, in order. Models that cannot do a task are skipped for it.",
    )
    only_tasks: list[Literal[tuple(AI_TASKS)]] = Field(  # type: ignore[valid-type]
        default_factory=list,
        description="Use your own accounts only for these tasks. Empty = all tasks.",
    )
    fallback_to_platform: bool = Field(
        False,
        description="If your accounts fail, fall back to the platform's AI (counts toward platform usage).",
    )

    @model_validator(mode="after")
    def _check(self):
        pids = [p.id for p in self.providers]
        mids = [m.id for m in self.models]
        if len(pids) != len(set(pids)) or len(mids) != len(set(mids)):
            raise ValueError("Provider and model ids must be unique.")
        for p in self.providers:
            if p.type not in BYOK_TYPES:
                raise ValueError(
                    f"Provider type {p.type} is not available for your own accounts. Use one of: {', '.join(BYOK_TYPES)}."
                )
            if p.type == "azure_openai":
                u = urlparse(p.base_url or "")
                host = (u.hostname or "").lower()
                if (
                    u.scheme != "https"
                    or u.username
                    or u.password
                    or u.port not in (None, 443)
                    or not host.endswith(AZURE_HOSTS)
                    or u.path not in ("", "/")
                ):
                    raise ValueError(
                        "Azure OpenAI needs your resource address, like https://your-resource.openai.azure.com"
                    )
            elif p.base_url:
                raise ValueError(f"{p.type} uses a fixed address; leave the base URL empty.")
            bad = set(p.options) - set(ADAPTER_OPTIONS)
            if bad:
                raise ValueError(f"Unknown option(s): {', '.join(sorted(bad))}.")
        for m in self.models:
            if m.provider_id not in pids:
                raise ValueError(f"Model {m.id} refers to a provider that is not in your list.")
        if any(x not in mids for x in self.model_order):
            raise ValueError("model_order names a model that is not in your list.")
        if self.enabled and not self.model_order:
            raise ValueError("Choose at least one model in model_order before enabling.")
        return self


register(
    SettingDef(
        key="ai.byok",
        model=ByokConfig,
        default=ByokConfig(),
        description="An organisation's own AI provider accounts (Enterprise). Keys are write-only.",
        scopes=frozenset({Scope.ORG}),
        owner_role="ORG_ADMIN",
        tags=("ai", "byok"),
    )
)


# --- Web scanner ----------------------------------------------------------------------------------


class ScanEngines(BaseModel):
    axe: bool = Field(True, description="axe-core")
    ibm: bool = Field(True, description="IBM Equal Access")
    htmlcs: bool = Field(True, description="HTML_CodeSniffer")
    page_timeout_seconds: int = Field(45, ge=5, le=180, description="Per page: load and analysis")
    max_pages_cap: int = Field(
        100,
        ge=1,
        le=2000,
        description="Platform ceiling on pages per scan, whatever the plan allows",
    )
    politeness_delay_ms: int = Field(
        250, ge=0, le=5000, description="Pause between pages of a crawl"
    )
    respect_robots: bool = Field(True, description="Honour robots.txt when crawling")
    unverified_crawl_pages: int = Field(
        5,
        ge=1,
        le=50,
        description="Largest crawl allowed on a site the organisation has not verified",
    )
    max_concurrent_per_org: int = Field(
        2, ge=1, le=20, description="Scans one organisation can run at once"
    )
    creations_per_minute: int = Field(
        10, ge=1, le=600, description="Scan requests per organisation per minute"
    )

    @model_validator(mode="after")
    def _one_engine(self):
        if not (self.axe or self.ibm or self.htmlcs):
            raise ValueError("At least one scan engine must stay enabled.")
        return self

    def enabled(self) -> tuple[str, ...]:
        return tuple(e for e in ("axe", "ibm", "htmlcs") if getattr(self, e))


register(
    SettingDef(
        key="scan.engines",
        model=ScanEngines,
        default=ScanEngines(),
        description="Which engines run, timeouts, crawl limits and rate limits. Override per plan or organisation.",
        scopes=frozenset({Scope.GLOBAL, Scope.PLAN, Scope.ORG}),
        tags=("scan",),
    )
)


class CodeFixPolicy(BaseModel):
    enabled: bool = Field(True, description="Offer code-fix suggestions on findings")
    per_minute: int = Field(
        20, ge=1, le=600, description="Fix requests per organisation per minute"
    )
    use_ai: bool = Field(
        True,
        description="Let a model propose fixes when no ready-made recipe applies. Off = recipes only; "
        "the element's HTML tag is sent to the AI provider when on.",
    )


register(
    SettingDef(
        key="ai.code_fix",
        model=CodeFixPolicy,
        default=CodeFixPolicy(),
        description="Code-fix suggestions: on or off, request rate, and whether a model may be used.",
        scopes=frozenset({Scope.GLOBAL, Scope.PLAN, Scope.ORG}),
        owner_role="AI_OPS",
        tags=("ai",),
    )
)


# --- Two-step verification policy ------------------------------------------------------------------------


def _mfa_default(attr: str):
    """Starting value comes from the environment (so development can start with MFA off); admins override it in /admin."""

    def make() -> str:
        from ..settings import get_settings

        return getattr(get_settings(), attr)

    return make


class MfaPolicy(BaseModel):
    """Who must use two-step verification at sign-in. Change it in /admin -> Settings -> auth.mfa.

    required  everyone in the group must enrol and enter a code at every sign-in
    optional  only people who have enrolled are asked for a code
    off       nobody is asked, even if enrolled. DEVELOPMENT ONLY: refused for platform administrators when
              ENV=production (and a banner shows in /admin while it is off)."""

    super_admin: Literal["required", "optional", "off"] = Field(
        default_factory=_mfa_default("mfa_super_admin_default"),
        description="Platform administrators (the /admin console)",
    )
    org_admin: Literal["required", "optional", "off"] = Field(
        default_factory=_mfa_default("mfa_org_admin_default"),
        description="Organisation administrators",
    )
    issuer: str = Field(
        "a11y", min_length=1, max_length=40, description="Name shown in authenticator apps"
    )


def _mfa_guard(new: MfaPolicy, prev: MfaPolicy) -> None:
    from ..settings import get_settings

    if get_settings().env == "production" and new.super_admin == "off":
        raise GuardrailError(
            "Two-step verification cannot be switched off for platform administrators in production."
        )


register(
    SettingDef(
        key="auth.mfa",
        model=MfaPolicy,
        default=MfaPolicy(),
        description="Two-step verification policy for administrators. 'off' is for development only.",
        guard=_mfa_guard,
        high_risk=True,
        tags=("auth", "security"),
    )
)
