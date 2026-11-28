from a11y_core.settings import get_settings
from fastapi import APIRouter, Depends

from ..deps import require_super_admin
from ..security import Principal
from .mfa import policy_for

router = APIRouter(prefix="/admin/security", tags=["admin"])


@router.get("/mfa")
async def mfa_policy(_: Principal = Depends(require_super_admin)):
    """What the admin console needs to warn when two-step verification is off (it is for development only)."""
    super_admin, issuer = await policy_for("SUPER_ADMIN")
    org_admin, _ = await policy_for("COMPANY_ADMIN")
    return {
        "super_admin": super_admin,
        "org_admin": org_admin,
        "issuer": issuer,
        "environment": get_settings().env,
    }
