"""LLMGateway: the ONLY way application code talks to a model.

Nothing else in the codebase imports a provider SDK. Which provider/model serves a task, the
fallback chain, parameters and budgets are admin-configured settings (``ai.providers``,
``ai.models``, ``ai.route.<task>``), read through the live-reloading config service - so
switching a provider in /admin takes effect on the next call with no redeploy.

Enterprise organisations may bring their own accounts (``ai.byok``, org-scoped). Their models are
tried first; the platform chain is used only if they allow it (``fallback_to_platform``). BYOK
calls are metered (``byok=true``) but never count against platform budgets.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from sqlalchemy import text

from ..billing import entitlement, load_subscription
from ..config import ConfigService, get_config
from ..config import definitions as _definitions  # noqa: F401
from ..config.definitions import AI_TASKS, DOCUMENT_TASKS, AIModel, AIProvider
from ..db import tenant_session
from ..models import AIUsage
from .adapters import ADAPTERS
from .types import (
    AIUnavailable,
    CallParams,
    LLMRequest,
    LLMResponse,
    ProviderAdapter,
    ProviderError,
)

log = logging.getLogger(__name__)
BYOK_FEATURE = "byok_ai"
Link = tuple[AIProvider, AIModel, bool]  # (provider, model, is_byok)


class LLMGateway:
    def __init__(
        self,
        config: ConfigService | None = None,
        adapters: dict[str, ProviderAdapter] | None = None,
    ) -> None:
        self._config = config
        self._adapters = adapters if adapters is not None else ADAPTERS

    @property
    def config(self) -> ConfigService:
        return self._config or get_config()

    async def _month_spend(self, org_id) -> float:
        """Platform-paid spend only: BYOK usage is the customer's own money."""
        async with tenant_session(org_id) as db:
            return float(
                (
                    await db.execute(
                        text(
                            "SELECT coalesce(sum(cost_usd), 0) FROM ai_usage "
                            "WHERE NOT byok AND created_at >= date_trunc('month', now())"
                        )
                    )
                ).scalar_one()
            )

    async def byok_entitled(self, org_id: uuid.UUID) -> bool:
        """Checked on every call (not just at save time) so a downgrade stops BYOK immediately."""
        async with tenant_session(org_id) as db:
            sub = await load_subscription(db)
            ent = await entitlement(db, sub.plan_id, BYOK_FEATURE)
        return ent.enabled

    async def _record(
        self,
        req: LLMRequest,
        prov: str,
        model: str,
        *,
        ok: bool,
        err: str | None,
        tin: int,
        tout: int,
        cost: float,
        ms: int,
        refs: list[str],
        byok: bool,
    ) -> None:
        if req.org_id is None:
            return
        try:
            async with tenant_session(req.org_id) as db:
                db.add(
                    AIUsage(
                        organization_id=req.org_id,
                        job_id=req.job_id,
                        task_key=req.task,
                        provider_id=prov,
                        model_id=model,
                        status="ok" if ok else "error",
                        byok=byok,
                        error_class=err,
                        tokens_in=tin,
                        tokens_out=tout,
                        cost_usd=cost,
                        latency_ms=ms,
                        config_refs=refs,
                    )
                )
        except Exception:  # noqa: BLE001 - metering must never turn a good answer into a failure
            log.exception("failed to record AI usage")

    @staticmethod
    def _links(
        model_ids: list[str],
        models: dict[str, AIModel],
        providers: dict[str, AIProvider],
        need: set[str],
        supported: set[str],
        byok: bool,
    ) -> list[Link]:
        out: list[Link] = []
        for mid in model_ids:
            m = models.get(mid)
            p = providers.get(m.provider_id) if m else None
            # Skip (never fail on) anything misconfigured, disabled or incapable.
            if (
                m
                and p
                and m.is_enabled
                and p.is_enabled
                and need <= set(m.capabilities)
                and p.type in supported
            ):
                out.append((p, m, byok))
        return out

    @staticmethod
    async def _apply_data_policy(req: LLMRequest, chain: list[Link]) -> list[Link]:
        """A customer's document may go only to providers the organisation's data policy allows (ADR 0024). Fails CLOSED: no
        organisation, or no provider that qualifies, means nothing is sent."""
        from .. import data_policy  # noqa: PLC0415

        if req.org_id is None:
            raise AIUnavailable(
                "Customer documents cannot be sent without an organisation.",
                reason="blocked_by_data_policy",
            )
        eff = await data_policy.effective(req.org_id, req.plan_id)
        if not eff.ai_on_documents:
            raise AIUnavailable(
                "This organisation's data policy does not allow AI to process its documents.",
                reason="blocked_by_data_policy",
            )
        ok: list[Link] = []
        why: list[str] = []
        for link in chain:
            problem = data_policy.ai_provider_problem(eff, link[0])
            if problem:
                why.append(problem)
            else:
                ok.append(link)
        if not ok:
            raise AIUnavailable(
                "No AI provider meets this organisation's data policy: "
                + "; ".join(dict.fromkeys(why))
                + ".",
                reason="blocked_by_data_policy",
            )
        return ok

    async def complete(self, req: LLMRequest) -> LLMResponse:
        if req.task not in AI_TASKS:
            raise ValueError(f"unknown AI task {req.task!r}")
        cfg = self.config
        kw = {"org_id": req.org_id, "plan_id": req.plan_id}
        route = await cfg.effective(f"ai.route.{req.task}", **kw)
        providers = await cfg.effective("ai.providers")
        models = await cfg.effective("ai.models")
        byok = await cfg.effective("ai.byok", org_id=req.org_id)
        refs = [route.ref, providers.ref, models.ref, byok.ref]
        r = route.value
        need = set(AI_TASKS[req.task])
        supported = set(self._adapters)
        params = CallParams(r.temperature, r.max_tokens, r.timeout_seconds)

        # 1. The organisation's own accounts (Enterprise), when enabled, entitled and applicable.
        own: list[Link] = []
        b = byok.value
        byok_active = (
            b.enabled
            and (not b.only_tasks or req.task in b.only_tasks)
            and await self.byok_entitled(req.org_id)
        )
        if byok_active:
            own = self._links(
                b.model_order,
                {m.id: m for m in b.models},
                {p.id: p for p in b.providers},
                need,
                supported,
                True,
            )

        # 2. The platform chain: unless BYOK is active without permission to fall back.
        platform: list[Link] = []
        if not own or b.fallback_to_platform:
            if r.primary_model_id:
                over_budget = (
                    r.monthly_budget_usd is not None
                    and await self._month_spend(req.org_id) >= r.monthly_budget_usd
                )
                if over_budget:
                    if not own:
                        raise AIUnavailable(
                            "This organisation's AI budget for the month is used up.",
                            reason="budget_exceeded",
                        )
                else:
                    platform = self._links(
                        [r.primary_model_id, *r.fallback_model_ids],
                        {m.id: m for m in models.value.items},
                        {p.id: p for p in providers.value.items},
                        need,
                        supported,
                        False,
                    )
        if not own and not r.primary_model_id:
            raise AIUnavailable(f"No model is configured for {req.task}.", reason="not_configured")
        chain = own + platform
        if not chain:
            raise AIUnavailable(f"No eligible model for {req.task}.", reason="no_eligible_model")
        if req.data_class == "customer_document" or req.task in DOCUMENT_TASKS:
            chain = await self._apply_data_policy(req, chain)

        # "Fell back" = something other than the model the config intended to serve it.
        intended = b.model_order[0] if byok_active else r.primary_model_id
        for p, m, is_byok in chain:
            t0 = time.perf_counter()
            try:
                raw = await asyncio.wait_for(
                    self._adapters[p.type].complete(p, m, params, req),
                    timeout=params.timeout_seconds,
                )
            except (ProviderError, TimeoutError) as e:
                ms = int((time.perf_counter() - t0) * 1000)
                await self._record(
                    req,
                    p.id,
                    m.id,
                    ok=False,
                    err=type(e).__name__,
                    tin=0,
                    tout=0,
                    cost=0.0,
                    ms=ms,
                    refs=refs,
                    byok=is_byok,
                )
                log.warning(
                    "AI call failed task=%s provider=%s model=%s byok=%s: %s",
                    req.task,
                    p.id,
                    m.id,
                    is_byok,
                    e,
                )
                continue
            ms = int((time.perf_counter() - t0) * 1000)
            cost = (
                raw.tokens_in / 1e6 * m.input_cost_per_1m
                + raw.tokens_out / 1e6 * m.output_cost_per_1m
            )
            await self._record(
                req,
                p.id,
                m.id,
                ok=True,
                err=None,
                tin=raw.tokens_in,
                tout=raw.tokens_out,
                cost=cost,
                ms=ms,
                refs=refs,
                byok=is_byok,
            )
            return LLMResponse(
                raw.text,
                p.id,
                m.id,
                raw.tokens_in,
                raw.tokens_out,
                cost,
                ms,
                fell_back=m.id != intended,
                config_refs=refs,
                byok=is_byok,
            )
        raise AIUnavailable(f"Every model for {req.task} failed.", reason="all_failed")

    async def test_provider(
        self, provider: AIProvider, models: list[AIModel], *, model_id: str | None = None
    ) -> dict:
        """Tiny live call to prove credentials, address and model/deployment name work. Used by
        the admin and org-admin 'Test connection' buttons. Returns a safe, user-facing result."""
        adapter = self._adapters.get(provider.type)
        if adapter is None:
            return {"ok": False, "detail": f"No adapter for provider type {provider.type} yet."}
        mine = [
            m
            for m in models
            if m.provider_id == provider.id and (model_id is None or m.id == model_id)
        ]
        if not mine:
            return {"ok": False, "detail": "Add a model for this provider first, then test."}
        t0 = time.perf_counter()
        try:
            await asyncio.wait_for(adapter.test_connection(provider, mine[0]), timeout=30)
        except (ProviderError, TimeoutError) as e:
            return {"ok": False, "detail": str(e) or "timed out", "model_id": mine[0].id}
        return {
            "ok": True,
            "detail": "Connected.",
            "model_id": mine[0].id,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
