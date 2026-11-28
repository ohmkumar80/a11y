"""An organisation's data policy: how long files are kept, where, whether people or AI may see them (ADR 0024).

Only the organisation's administrator can change it, and only inside what the platform has allowed for the plan (the
`data.controls` setting). The page always shows what is actually in force, which is the strictest of the plan's limits and
the organisation's own choices."""

from a11y_core import data_policy
from a11y_core.config import get_config
from a11y_core.config.definitions import OrgDataPolicy
from a11y_core.db import tenant_session
from a11y_core.models import DocumentStatus
from a11y_core.storage import StorageError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from ..deps import require_company_admin
from ..security import Principal

router = APIRouter(prefix="/org/data-policy", tags=["org"])


class DeleteIn(BaseModel):
    confirm: bool = False


def _eff_json(e: data_policy.Effective) -> dict:
    return {
        "retention_days": e.retention_days,
        "retention_ceiling": e.retention_ceiling,
        "region": {"id": e.region.id, "label": e.region.label},
        "allow_human_review": e.allow_human_review,
        "ai_on_documents": e.ai_on_documents,
        "ai_require_zero_retention": e.ai_require_zero_retention,
        "ai_regions": list(e.ai_regions),
    }


@router.get("")
async def read(p: Principal = Depends(require_company_admin)):
    eff = await data_policy.effective(p.org_id)
    providers = (await get_config().effective("ai.providers")).value.items
    async with tenant_session(p.org_id) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT region, count(*) AS n FROM documents WHERE status <> :s GROUP BY region"
                ),
                {"s": DocumentStatus.DELETED},
            )
        ).all()
    return {
        "controls": eff.controls.model_dump(),
        "chosen": eff.chosen.model_dump(),
        "effective": _eff_json(eff),
        "regions": [{"id": r.id, "label": r.label} for r in eff.offered_regions],
        "ai_region_options": sorted(
            {
                x.lower()
                for pr in providers
                if pr.is_enabled
                for x in pr.data_policy.processing_regions
            }
        ),
        "documents": {"stored": sum(r.n for r in rows), "by_region": {r.region: r.n for r in rows}},
    }


@router.put("")
async def write(body: OrgDataPolicy, p: Principal = Depends(require_company_admin)):
    try:
        eff, shortened = await data_policy.save(p.org_id, p.user_id, body)
    except data_policy.PolicyRefused as e:
        raise HTTPException(422, detail={"detail": e.message, "field": e.field or None}) from None
    return {"effective": _eff_json(eff), "existing_files_shortened": shortened}


@router.post("/delete-documents")
async def delete_documents(body: DeleteIn, p: Principal = Depends(require_company_admin)):
    """Erase every stored file now. Needs `confirm: true`: it cannot be undone."""
    if not body.confirm:
        raise HTTPException(
            422,
            detail={
                "detail": "Confirm that you want to delete every document.",
                "field": "confirm",
            },
        )
    try:
        return {"deleted": await data_policy.delete_all_documents(p.org_id, p.user_id)}
    except StorageError:
        raise HTTPException(
            503,
            detail={
                "detail": "We could not reach file storage. Nothing more was deleted; please try again.",
                "code": "storage_unavailable",
            },
        ) from None
