from a11y_core.ai import get_gateway
from a11y_core.config import definitions as _definitions  # noqa: F401
from a11y_core.config import get_config
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..deps import require_super_admin
from ..security import Principal

router = APIRouter(prefix="/admin/ai", tags=["admin"])


class TestIn(BaseModel):
    model_id: str | None = Field(None, max_length=60)


@router.get("/providers")
async def providers(_: Principal = Depends(require_super_admin)):
    """Providers with their models and whether a key is set (never the key)."""
    cfg = get_config()
    provs = (await cfg.effective("ai.providers")).value.items
    models = (await cfg.effective("ai.models")).value.items
    return [
        {
            "id": p.id,
            "type": p.type,
            "display_name": p.display_name,
            "base_url": p.base_url,
            "region": p.region,
            "is_enabled": p.is_enabled,
            "key_set": p.api_key.is_set,
            "data_policy": p.data_policy.model_dump(),
            "models": [
                {
                    "id": m.id,
                    "model_name": m.model_name,
                    "capabilities": m.capabilities,
                    "is_enabled": m.is_enabled,
                }
                for m in models
                if m.provider_id == p.id
            ],
        }
        for p in provs
    ]


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: str, body: TestIn, _: Principal = Depends(require_super_admin)
):
    """Live 'Test connection' with the saved credentials (secrets are decrypted server-side only)."""
    cfg = get_config()
    prov = next(
        (p for p in (await cfg.effective("ai.providers")).value.items if p.id == provider_id), None
    )
    if prov is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No such provider. Save it in Settings first."
        )
    models = (await cfg.effective("ai.models")).value.items
    return await get_gateway().test_provider(prov, models, model_id=body.model_id)


# --- quick add ----------------------------------------------------------------------------------
# Everything here is just a convenience over the Settings editor: it writes the same versioned,
# audited ``ai.providers`` / ``ai.models`` / ``ai.route.<task>`` settings, so it can be edited,
# rolled back and overridden per plan or organisation like any other setting.

from typing import Literal  # noqa: E402

from a11y_core.config import GuardrailError, Scope  # noqa: E402
from a11y_core.config.definitions import AI_TASKS  # noqa: E402

PRESETS = {
    "deepseek": {
        "type": "deepseek",
        "label": "DeepSeek",
        "provider_id": "deepseek",
        "needs_endpoint": False,
        "default_model": "deepseek-chat",
        "capabilities": ["text", "json", "tools"],
        "context_window": 65536,
        # DeepSeek's hosted API processes data in China: flagged so regulated tenants can exclude it.
        "data_policy": {
            "zero_retention": False,
            "processing_regions": ["cn"],
            "gov_approved": False,
        },
        "options": {},
    },
    "azure_openai": {
        "type": "azure_openai",
        "label": "Azure OpenAI",
        "provider_id": "azure-openai",
        "needs_endpoint": True,
        "default_model": "",
        "capabilities": ["text", "vision", "json", "tools"],
        "context_window": 128000,
        "data_policy": {"zero_retention": False, "processing_regions": [], "gov_approved": False},
        "options": {},
    },
    "openai": {
        "type": "openai",
        "label": "OpenAI",
        "provider_id": "openai",
        "needs_endpoint": False,
        "default_model": "gpt-4o-mini",
        "capabilities": ["text", "vision", "json", "tools"],
        "context_window": 128000,
        "data_policy": {
            "zero_retention": False,
            "processing_regions": ["us"],
            "gov_approved": False,
        },
        "options": {},
    },
}


class QuickAddIn(BaseModel):
    preset: Literal["deepseek", "azure_openai", "openai"]
    api_key: str = Field(min_length=8, max_length=4096)
    # Azure: https://<resource>.openai.azure.com ; ignored for fixed-address providers.
    endpoint: str | None = Field(None, max_length=300)
    # The provider's model name, or for Azure your DEPLOYMENT name.
    model_name: str | None = Field(None, max_length=200)
    api_version: str | None = Field(None, max_length=40)
    use_for_tasks: list[str] = []
    comment: str = Field(min_length=1, max_length=500)


@router.get("/presets")
async def presets(_: Principal = Depends(require_super_admin)):
    return {"presets": PRESETS, "tasks": {k: list(v) for k, v in AI_TASKS.items()}}


@router.post("/quick-add")
async def quick_add(body: QuickAddIn, p: Principal = Depends(require_super_admin)):
    pre = PRESETS[body.preset]
    if pre["needs_endpoint"] and not body.endpoint:
        raise HTTPException(
            422,
            detail={
                "detail": "Enter your Azure resource address, like https://your-resource.openai.azure.com",
                "field": "endpoint",
            },
        )
    model_name = (body.model_name or pre["default_model"]).strip()
    if not model_name:
        raise HTTPException(
            422,
            detail={
                "detail": "Enter the deployment name from your Azure portal.",
                "field": "model_name",
            },
        )
    unknown = [t for t in body.use_for_tasks if t not in AI_TASKS]
    if unknown:
        raise HTTPException(
            422, detail={"detail": f"Unknown task: {unknown[0]}", "field": "use_for_tasks"}
        )

    cfg = get_config()
    prov = {
        "id": pre["provider_id"],
        "type": pre["type"],
        "display_name": pre["label"],
        "base_url": body.endpoint.strip() if pre["needs_endpoint"] and body.endpoint else None,
        "region": None,
        "api_key": {"$secret": True, "plaintext": body.api_key},
        "options": {"api_version": body.api_version} if body.api_version else {},
        "data_policy": pre["data_policy"],
        "is_enabled": True,
    }
    model = {
        "id": f"{pre['provider_id']}-{model_name}".lower().replace(" ", "-")[:59],
        "provider_id": pre["provider_id"],
        "model_name": model_name,
        "capabilities": pre["capabilities"],
        "context_window": pre["context_window"],
        "input_cost_per_1m": 0,
        "output_cost_per_1m": 0,
        "is_enabled": True,
    }
    try:
        cur_p = (await cfg.effective("ai.providers")).value.model_dump(mode="json", by_alias=True)[
            "items"
        ]
        cur_m = (await cfg.effective("ai.models")).value.model_dump(mode="json", by_alias=True)[
            "items"
        ]
        # Replace the same provider/model id (re-adding is how a key is rotated); keep others.
        await cfg.save(
            "ai.providers",
            Scope.GLOBAL,
            "",
            {"items": [x for x in cur_p if x["id"] != prov["id"]] + [prov]},
            comment=body.comment,
            actor=p.user_id,
        )
        await cfg.save(
            "ai.models",
            Scope.GLOBAL,
            "",
            {"items": [x for x in cur_m if x["id"] != model["id"]] + [model]},
            comment=body.comment,
            actor=p.user_id,
        )
        routed, skipped = [], []
        for task in body.use_for_tasks:
            if not set(AI_TASKS[task]) <= set(model["capabilities"]):
                skipped.append(
                    {"task": task, "reason": "this model cannot do " + "/".join(AI_TASKS[task])}
                )
                continue
            route = (await cfg.effective(f"ai.route.{task}")).value.model_dump(mode="json")
            if route["primary_model_id"] in (None, model["id"]):
                route["primary_model_id"] = model["id"]
            elif model["id"] not in route["fallback_model_ids"]:
                route["fallback_model_ids"] = [*route["fallback_model_ids"], model["id"]][:5]
            await cfg.save(
                f"ai.route.{task}", Scope.GLOBAL, "", route, comment=body.comment, actor=p.user_id
            )
            routed.append(task)
    except GuardrailError as e:
        raise HTTPException(422, detail={"detail": str(e)}) from None
    return {
        "provider_id": prov["id"],
        "model_id": model["id"],
        "routed_tasks": routed,
        "skipped": skipped,
    }
