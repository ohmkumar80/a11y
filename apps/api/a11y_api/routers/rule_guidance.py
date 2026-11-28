"""Plain-language fix guidance for a rule (PROJECT_PLAN 3.13 content library)."""

from a11y_core.rules import get_registry
from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import current_principal
from ..security import Principal

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("/{rule_id}/guidance")
async def guidance(rule_id: str, _: Principal = Depends(current_principal)):
    """404 when we have no written guidance yet; the UI then shows only the engine's own help link.
    ``review_status`` stays 'draft' until an accessibility SME signs the content off."""
    c = get_registry().content.get(rule_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No guidance for this rule yet.")
    return {
        "rule": c.id,
        "review_status": c.status,
        "summary": c.summary,
        "why": c.why,
        "who": c.who,
        "steps": c.steps,
        "examples": [e.model_dump() for e in c.examples],
        "links": [link.model_dump() for link in c.links],
        "how_to_check": c.test,
        "machine_checked": c.machine_check,
    }
