"""Enterprise bring-your-own-key: an organisation admin manages the org's own AI accounts.

Gated by the ``byok_ai`` plan entitlement (checked here AND on every AI call). Writes go through
the settings store with the org id taken from the caller's token, never from the request, and the
registry guard (``ByokConfig``) restricts provider types and addresses so a tenant cannot aim our
servers at arbitrary hosts. Keys are write-only, as everywhere else.
"""

from a11y_core import billing
from a11y_core.ai import get_gateway
from a11y_core.config import GuardrailError, Scope, get_config, redact
from a11y_core.config import definitions as _definitions  # noqa: F401
from a11y_core.config.definitions import BYOK_TYPES, ByokConfig
from a11y_core.config.registry import public_schema
from a11y_core.db import tenant_session
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..deps import require_company_admin
from ..security import Principal

router = APIRouter(prefix="/org/ai", tags=["org"])


class PutIn(BaseModel):
    value: dict


class TestIn(BaseModel):
    provider_id: str = Field(max_length=40)


async def _require_entitled(org_id) -> None:
    if not await get_gateway().byok_entitled(org_id):
        raise billing.FeatureNotInPlan(
            "Using your own AI accounts is part of the Enterprise plan.",
            feature="byok_ai",
            upgrade_url=billing.UPGRADE_PATH,
        )


@router.get("")
async def read(p: Principal = Depends(require_company_admin)):
    eligible = await get_gateway().byok_entitled(p.org_id)
    out: dict = {
        "eligible": eligible,
        "provider_types": list(BYOK_TYPES),
        "upgrade_url": billing.UPGRADE_PATH,
    }
    if not eligible:
        return out
    e = await get_config().effective("ai.byok", org_id=p.org_id)
    async with tenant_session(p.org_id) as db:
        calls, cost = (
            await db.execute(
                text(
                    "SELECT count(*), coalesce(sum(tokens_in + tokens_out), 0) FROM ai_usage "
                    "WHERE byok AND status='ok' AND created_at >= date_trunc('month', now())"
                )
            )
        ).one()
    out |= {
        "schema": public_schema(ByokConfig),
        "version": e.version,
        "value": redact(e.value.model_dump(mode="json", by_alias=True)),
        "usage_this_month": {"calls": calls, "tokens": int(cost)},
    }
    return out


@router.put("")
async def write(body: PutIn, p: Principal = Depends(require_company_admin)):
    await _require_entitled(p.org_id)
    try:
        row = await get_config().save(
            "ai.byok",
            Scope.ORG,
            str(p.org_id),
            body.value,
            comment="Updated by an organisation administrator",
            actor=p.user_id,
        )
    except GuardrailError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"detail": str(e), "field": "value"}
        ) from None
    return {"version": row.version}


@router.post("/test")
async def test_connection(body: TestIn, p: Principal = Depends(require_company_admin)):
    await _require_entitled(p.org_id)
    cfg = (await get_config().effective("ai.byok", org_id=p.org_id)).value
    prov = next((x for x in cfg.providers if x.id == body.provider_id), None)
    if prov is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Save your provider first, then test it.")
    return await get_gateway().test_provider(prov, cfg.models)
