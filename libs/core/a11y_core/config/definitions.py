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
    "code_fix_escalate": (
        "text",
    ),  # a stronger model, tried once when the light one could not produce a valid fix
    "code_fix_validate": (
        "text",
    ),  # an independent reviewer (ideally another provider) that reads the fix
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
    tier: Literal["LIGHT", "STANDARD", "PREMIUM"] = Field(
        "STANDARD",
        description="How capable and costly this model is. Light: routine work; Standard: component-level fixes; "
        "Premium: validation and hard reasoning.",
    )


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
    screenshots: bool = Field(True, description="Save a screenshot of each scanned page")
    screenshot_pages: int = Field(
        25, ge=0, le=200, description="Most pages per scan that keep a screenshot"
    )
    screenshot_max_height: int = Field(
        5000, ge=800, le=12000, description="Tallest part of a page to save, in pixels"
    )
    screenshot_quality: int = Field(60, ge=30, le=90, description="JPEG quality (higher = bigger)")

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
    escalate: bool = Field(
        True,
        description="If the light model cannot produce a valid fix, try the stronger `code_fix_escalate` route once",
    )
    validation: Literal["off", "sample", "always"] = Field(
        "sample",
        description="Independent review of model-written fixes by the `code_fix_validate` route. "
        "Always = a fix is not shown unless the reviewer approves it.",
    )
    validation_sample_rate: float = Field(
        0.1, ge=0, le=1, description="Share of fixes reviewed when validation is 'sample'"
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


class ApiLimits(BaseModel):
    requests_per_minute: int = Field(
        120, ge=1, le=6000, description="Requests per API key per minute"
    )
    max_keys_per_org: int = Field(10, ge=1, le=200, description="Active API keys per organisation")
    max_key_lifetime_days: int | None = Field(
        None, ge=1, le=3650, description="Longest a key may live; empty = keys can be non-expiring"
    )


register(
    SettingDef(
        key="api.limits",
        model=ApiLimits,
        default=ApiLimits(),
        description="Public API: request rate per key, keys per organisation, and key lifetime.",
        scopes=frozenset({Scope.GLOBAL, Scope.PLAN, Scope.ORG}),
        tags=("api",),
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


# --- Documents and eBooks (PROJECT_PLAN Phase 3; ADR 0020) --------------------------------------------------
# Everything about customer-file handling is an admin setting, so limits can be tightened or relaxed per plan or
# per organisation without a deploy. The safety knobs are global-only and high-risk.


class DocumentUploads(BaseModel):
    enabled: bool = Field(True, description="Accept document uploads at all (a kill switch)")
    allow_pdf: bool = Field(True, description="Accept PDF files")
    allow_docx: bool = Field(True, description="Accept Word (.docx) files")
    allow_pptx: bool = Field(True, description="Accept PowerPoint (.pptx) files")
    allow_epub: bool = Field(True, description="Accept EPUB files")
    max_mb_pdf: int = Field(50, ge=1, le=500, description="Largest PDF, in megabytes")
    max_mb_docx: int = Field(25, ge=1, le=500, description="Largest Word file, in megabytes")
    max_mb_pptx: int = Field(50, ge=1, le=500, description="Largest PowerPoint file, in megabytes")
    max_mb_epub: int = Field(50, ge=1, le=500, description="Largest EPUB, in megabytes")
    max_pages: int = Field(
        500, ge=1, le=10000, description="Most pages (or slides) in one file; a longer file is refused"
    )
    max_files_per_hour: int = Field(
        60, ge=1, le=10000, description="Uploads one organisation may make per hour"
    )
    max_active_files: int = Field(
        500, ge=1, le=1000000, description="Files one organisation may keep at once"
    )

    def kinds(self) -> tuple[str, ...]:
        return tuple(k for k in ("pdf", "docx", "pptx", "epub") if getattr(self, f"allow_{k}"))

    def max_bytes(self, kind: str) -> int:
        return int(getattr(self, f"max_mb_{kind}")) * 1024 * 1024


register(
    SettingDef(
        key="documents.uploads",
        model=DocumentUploads,
        default=DocumentUploads(),
        description="Which document types are accepted, size and page limits, and upload rates. Override per plan or organisation.",
        scopes=frozenset({Scope.GLOBAL, Scope.PLAN, Scope.ORG}),
        tags=("documents",),
    )
)


class DocumentSafety(BaseModel):
    """How untrusted files are checked before anything reads them. Platform-wide on purpose: a customer or plan
    must not be able to weaken it."""

    malware_scan: Literal["required", "off"] = Field(
        "required",
        description="'required': a file is held back until the virus scanner has passed it, and stays held if the "
        "scanner is down. 'off' is for development only and is refused in production.",
    )
    scan_timeout_seconds: int = Field(
        60, ge=5, le=600, description="How long the virus scanner may take on one file"
    )
    reject_encrypted: bool = Field(
        True, description="Refuse password-protected files (they cannot be audited)"
    )
    reject_active_content: bool = Field(
        True,
        description="Refuse PDFs that carry scripts or launch actions. Turn off only if customers need to audit "
        "interactive forms; the file is still virus-scanned.",
    )
    zip_max_entries: int = Field(
        5000, ge=10, le=100000, description="Most items inside a Word, PowerPoint or EPUB file"
    )
    zip_max_uncompressed_mb: int = Field(
        500, ge=1, le=5000, description="Most data a Word, PowerPoint or EPUB file may expand to"
    )
    zip_max_ratio: int = Field(
        200, ge=2, le=10000, description="Largest allowed expansion of any one item (a 'zip bomb' guard)"
    )
    max_attempts: int = Field(
        5, ge=1, le=20, description="How often a check is retried when the scanner is unavailable"
    )


def _safety_guard(new: DocumentSafety, prev: DocumentSafety) -> None:
    from ..settings import get_settings

    if get_settings().env == "production" and new.malware_scan == "off":
        raise GuardrailError("The virus scan cannot be switched off in production.")


register(
    SettingDef(
        key="documents.safety",
        model=DocumentSafety,
        default=DocumentSafety(),
        description="Virus scan, encrypted and active-content policy, and zip-bomb limits for uploaded files.",
        guard=_safety_guard,
        high_risk=True,
        tags=("documents", "security"),
    )
)


class DocumentRetention(BaseModel):
    retention_days: int = Field(
        30, ge=1, le=3650, description="Days a customer's files are kept before they are deleted"
    )
    rejected_retention_days: int = Field(
        3, ge=1, le=90, description="Days a refused or infected file is kept (for support) before deletion"
    )
    purge_batch: int = Field(200, ge=1, le=5000, description="Most files deleted per hourly sweep")


register(
    SettingDef(
        key="documents.retention",
        model=DocumentRetention,
        default=DocumentRetention(),
        description="How long customer files are kept. Set shorter for a plan or organisation with stricter needs.",
        scopes=frozenset({Scope.GLOBAL, Scope.PLAN, Scope.ORG}),
        tags=("documents", "privacy"),
    )
)
