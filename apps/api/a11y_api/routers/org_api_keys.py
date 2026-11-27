"""Organisation administrators manage API keys here (the keys themselves authenticate /v1, see ``api_auth``).

A key is shown once, at creation. Only a hash is kept, so a lost key cannot be recovered, only replaced."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from a11y_core import api_keys, billing
from a11y_core.config import get_config
from a11y_core.db import tenant_session
from a11y_core.models import ApiKey, AuditLog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update

from ..deps import ensure_flag, require_company_admin
from ..security import Principal

router = APIRouter(prefix="/org/api-keys", tags=["org"])


def _problem(
    http_status: int, detail: str, code: str | None = None, field: str | None = None, **extra
) -> HTTPException:
    return HTTPException(
        http_status, detail={"detail": detail, "code": code, "field": field, **extra}
    )


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1, max_length=len(api_keys.SCOPES))
    expires_in_days: int | None = Field(None, ge=1, le=3650)


def _json(k: ApiKey) -> dict:
    now = datetime.now(UTC)
    state = (
        "revoked"
        if k.revoked_at
        else "expired"
        if k.expires_at and k.expires_at <= now
        else "active"
    )
    return {
        "id": str(k.id),
        "name": k.name,
        "hint": k.key_hint,
        "scopes": k.scopes,
        "state": state,
        "created_at": k.created_at,
        "expires_at": k.expires_at,
        "last_used_at": k.last_used_at,
        "revoked_at": k.revoked_at,
    }


async def _plan_and_limits(db, org_id: uuid.UUID):
    sub = await billing.load_subscription(db)
    ent = await billing.entitlement(db, sub.plan_id, api_keys.ENTITLEMENT)
    lim = (await get_config().effective("api.limits", org_id=org_id, plan_id=sub.plan_id)).value
    return sub, ent, lim


@router.get("")
async def list_keys(p: Principal = Depends(require_company_admin)):
    async with tenant_session(p.org_id) as db:
        _, ent, lim = await _plan_and_limits(db, p.org_id)
        rows = (await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))).scalars().all()
    return {
        "entitled": ent.enabled,
        "upgrade_url": "/org#plan",
        "max_keys": lim.max_keys_per_org,
        "max_lifetime_days": lim.max_key_lifetime_days,
        "scopes": api_keys.SCOPES,
        "keys": [_json(k) for k in rows],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_key(body: KeyIn, p: Principal = Depends(require_company_admin)):
    await ensure_flag("public_api", p)
    unknown = sorted(set(body.scopes) - set(api_keys.SCOPES))
    if unknown:
        raise _problem(422, f"Unknown scope: {', '.join(unknown)}.", "unknown_scope", "scopes")
    key, digest, hint = api_keys.generate(p.org_id)
    async with tenant_session(p.org_id) as db:
        # Serialise creation per organisation so the key limit cannot be raced past.
        sub = await billing.require_writable(db, lock=True)
        _, ent, lim = await _plan_and_limits(db, p.org_id)
        if not ent.enabled:
            raise _problem(
                402,
                "Your plan does not include API access.",
                "api_not_in_plan",
                upgrade_url="/org#plan",
            )
        active = (
            await db.execute(
                text(
                    "SELECT count(*) FROM api_keys WHERE revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())"
                )
            )
        ).scalar_one()
        if active >= lim.max_keys_per_org:
            raise _problem(
                409,
                f"You already have {active} active keys, the most your organisation can have. Revoke one first.",
                "too_many_keys",
            )
        days = body.expires_in_days
        if lim.max_key_lifetime_days is not None:
            if days is None or days > lim.max_key_lifetime_days:
                if days is None:
                    days = lim.max_key_lifetime_days
                else:
                    raise _problem(
                        422,
                        f"Keys can live at most {lim.max_key_lifetime_days} days.",
                        "lifetime_too_long",
                        "expires_in_days",
                    )
        k = ApiKey(
            id=uuid.uuid4(),
            organization_id=p.org_id,
            name=body.name.strip(),
            key_hash=digest,
            key_hint=hint,
            scopes=sorted(set(body.scopes)),
            created_by=p.user_id,
            expires_at=datetime.now(UTC) + timedelta(days=days) if days else None,
        )
        db.add(k)
        db.add(
            AuditLog(
                organization_id=p.org_id,
                actor_user_id=p.user_id,
                action="api_key.create",
                detail={
                    "key_id": str(k.id),
                    "name": k.name,
                    "scopes": k.scopes,
                    "plan": sub.plan_id,
                },
            )
        )
        await db.flush()
        await db.refresh(k)
        out = _json(k)
    return {
        **out,
        "key": key,
        "notice": "Copy this key now. It is shown only once and cannot be recovered.",
    }


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(key_id: uuid.UUID, p: Principal = Depends(require_company_admin)):
    async with tenant_session(p.org_id) as db:
        k = (await db.execute(select(ApiKey).where(ApiKey.id == key_id))).scalar_one_or_none()
        if k is None:
            raise _problem(404, "We could not find that key.")
        if k.revoked_at is None:
            await db.execute(
                update(ApiKey).where(ApiKey.id == key_id).values(revoked_at=datetime.now(UTC))
            )
            db.add(
                AuditLog(
                    organization_id=p.org_id,
                    actor_user_id=p.user_id,
                    action="api_key.revoke",
                    detail={"key_id": str(key_id), "name": k.name},
                )
            )
