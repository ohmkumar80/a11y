"""Super Admin settings API. The admin UI renders its forms from ``GET /admin/settings``
(JSON Schema per setting) so a new registry entry needs no new screen."""

import uuid

from a11y_core.config import GuardrailError, Scope, get_config, get_def, redact
from a11y_core.config import definitions as _definitions  # noqa: F401  (registers settings)
from a11y_core.config.registry import REGISTRY
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..deps import require_super_admin
from ..security import Principal

router = APIRouter(prefix="/admin/settings", tags=["admin"])


class Target(BaseModel):
    scope: Scope = Scope.GLOBAL
    scope_id: str = Field("", max_length=64)


class WriteIn(Target):
    value: dict
    comment: str = Field(max_length=1000)
    publish: bool = True


class PublishIn(Target):
    version: int
    comment: str = Field(max_length=1000)


class RollbackIn(Target):
    to_version: int
    comment: str = Field(max_length=1000)


def _unknown(key: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"No setting called {key}.")


def _bad(e: GuardrailError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"detail": str(e), "field": "value"}
    )


def _def(key: str):
    try:
        return get_def(key)
    except KeyError:
        raise _unknown(key) from None


@router.get("")
async def list_settings(_: Principal = Depends(require_super_admin)):
    get_def("billing.trial")
    return [
        {
            "key": d.key,
            "description": d.description,
            "scopes": sorted(s.value for s in d.scopes),
            "owner_role": d.owner_role,
            "high_risk": d.high_risk,
            "tags": list(d.tags),
            "schema": d.json_schema(),
        }
        for d in sorted(REGISTRY.values(), key=lambda d: d.key)
    ]


@router.get("/{key}")
async def read_setting(
    key: str,
    scope: Scope = Scope.GLOBAL,
    scope_id: str = Query("", max_length=64),
    _: Principal = Depends(require_super_admin),
):
    """Effective value (secrets redacted) and where it comes from. For org scope the effective
    value for that organisation is returned; for plan scope, for that plan."""
    _def(key)
    kw = {"org_id": uuid.UUID(scope_id)} if scope is Scope.ORG and scope_id else {}
    if scope is Scope.PLAN:
        kw = {"plan_id": scope_id}
    e = await get_config().effective(key, **kw)
    return {
        "key": key,
        "source": e.source,
        "version": e.version,
        "value": redact(e.value.model_dump(mode="json", by_alias=True)),
    }


@router.put("/{key}")
async def write_setting(key: str, body: WriteIn, p: Principal = Depends(require_super_admin)):
    _def(key)
    try:
        row = await get_config().save(
            key,
            body.scope,
            body.scope_id,
            body.value,
            comment=body.comment,
            actor=p.user_id,
            publish=body.publish,
        )
    except GuardrailError as e:
        raise _bad(e) from None
    return {"version": row.version, "status": row.status}


@router.post("/{key}/publish")
async def publish_setting(key: str, body: PublishIn, p: Principal = Depends(require_super_admin)):
    _def(key)
    try:
        row = await get_config().publish(
            key, body.scope, body.scope_id, body.version, comment=body.comment, actor=p.user_id
        )
    except GuardrailError as e:
        raise _bad(e) from None
    return {"version": row.version, "status": row.status}


@router.get("/{key}/history")
async def setting_history(
    key: str,
    scope: Scope = Scope.GLOBAL,
    scope_id: str = Query("", max_length=64),
    p: Principal = Depends(require_super_admin),
):
    _def(key)
    try:
        return await get_config().history(key, scope, scope_id, actor=p.user_id)
    except GuardrailError as e:
        raise _bad(e) from None


@router.post("/{key}/rollback")
async def rollback_setting(key: str, body: RollbackIn, p: Principal = Depends(require_super_admin)):
    _def(key)
    try:
        row = await get_config().rollback(
            key, body.scope, body.scope_id, body.to_version, comment=body.comment, actor=p.user_id
        )
    except GuardrailError as e:
        raise _bad(e) from None
    return {"version": row.version, "restored_from": row.restored_from}
