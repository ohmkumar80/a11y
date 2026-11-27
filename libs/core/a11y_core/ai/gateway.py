"""LLMGateway: the ONLY way application code talks to a model.

Nothing else in the codebase imports a provider SDK. Which provider/model serves a task, the
fallback chain, parameters and budgets are admin-configured settings (``ai.providers``,
``ai.models``, ``ai.route.<task>``), read through the live-reloading config service - so
switching a provider in /admin takes effect on the next call with no redeploy.
"""

from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import text

from ..config import ConfigService, get_config
from ..config import definitions as _definitions  # noqa: F401
from ..config.definitions import AI_TASKS, AIModel, AIProvider
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
        async with tenant_session(org_id) as db:
            return float(
                (
                    await db.execute(
                        text(
                            "SELECT coalesce(sum(cost_usd), 0) FROM ai_usage "
                            "WHERE created_at >= date_trunc('month', now())"
                        )
                    )
                ).scalar_one()
            )

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
    ) -> None:
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

    async def complete(self, req: LLMRequest) -> LLMResponse:
        if req.task not in AI_TASKS:
            raise ValueError(f"unknown AI task {req.task!r}")
        cfg = self.config
        kw = {"org_id": req.org_id, "plan_id": req.plan_id}
        route = await cfg.effective(f"ai.route.{req.task}", **kw)
        providers = await cfg.effective("ai.providers")
        models = await cfg.effective("ai.models")
        refs = [route.ref, providers.ref, models.ref]
        r = route.value

        if not r.primary_model_id:
            raise AIUnavailable(f"No model is configured for {req.task}.", reason="not_configured")
        if (
            r.monthly_budget_usd is not None
            and await self._month_spend(req.org_id) >= r.monthly_budget_usd
        ):
            raise AIUnavailable(
                "This organisation's AI budget for the month is used up.", reason="budget_exceeded"
            )

        by_provider: dict[str, AIProvider] = {p.id: p for p in providers.value.items}
        by_model: dict[str, AIModel] = {m.id: m for m in models.value.items}
        need = set(AI_TASKS[req.task])
        params = CallParams(r.temperature, r.max_tokens, r.timeout_seconds)

        chain: list[tuple[AIProvider, AIModel]] = []
        for mid in [r.primary_model_id, *r.fallback_model_ids]:
            m = by_model.get(mid)
            p = by_provider.get(m.provider_id) if m else None
            # Skip (never fail on) anything misconfigured, disabled or incapable.
            if (
                m
                and p
                and m.is_enabled
                and p.is_enabled
                and need <= set(m.capabilities)
                and p.type in self._adapters
            ):
                chain.append((p, m))
        if not chain:
            raise AIUnavailable(f"No eligible model for {req.task}.", reason="no_eligible_model")

        for p, m in chain:
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
                )
                log.warning(
                    "AI call failed task=%s provider=%s model=%s: %s",
                    req.task,
                    p.id,
                    m.id,
                    type(e).__name__,
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
            )
            return LLMResponse(
                raw.text,
                p.id,
                m.id,
                raw.tokens_in,
                raw.tokens_out,
                cost,
                ms,
                fell_back=m.id != r.primary_model_id,
                config_refs=refs,
            )
        raise AIUnavailable(f"Every model for {req.task} failed.", reason="all_failed")


_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
