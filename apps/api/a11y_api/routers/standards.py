from a11y_core.rules import get_registry
from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import current_principal
from ..security import Principal

router = APIRouter(prefix="/standards", tags=["standards"])


@router.get("")
async def list_standards(_: Principal = Depends(current_principal)):
    """Standards a scan can be evaluated against. ``review`` tells the UI whether an accessibility
    SME has signed off the mapping; until then it must say 'draft'."""
    reg = get_registry()
    return {
        "review": reg.review | {"version": reg.standards_version},
        "standards": [
            {
                "id": s.id,
                "label": s.label,
                "legal_status": s.legal_status,
                "citation": s.citation,
                "notes": s.notes,
                "criteria_count": len(reg.criteria_for(s.id)),
                "automated_criteria": len(
                    [c for c in reg.criteria_for(s.id) if c.id in reg.automated_sc]
                ),
            }
            for s in reg.standards.values()
        ],
    }


@router.get("/{standard_id}/criteria")
async def criteria(standard_id: str, _: Principal = Depends(current_principal)):
    reg = get_registry()
    if standard_id not in reg.standards:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such standard.")
    return [
        {
            "id": c.id,
            "name": c.name,
            "level": c.level,
            "clause": reg.clause(standard_id, c.id),
            "automated": c.id in reg.automated_sc,
        }
        for c in reg.criteria_for(standard_id)
    ]
