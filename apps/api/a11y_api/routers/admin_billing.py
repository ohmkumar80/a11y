"""Super Admin: plans & entitlements, coupons, tenant directory, manual plan assignment, trial
funnel. Every call goes through ``admin_session`` (cross-tenant, audit-logged with a reason)."""

import uuid
from datetime import datetime
from typing import Literal

from a11y_core import billing
from a11y_core.db import admin_session
from a11y_core.models import (
    AuditLog,
    Coupon,
    Plan,
    PlanEntitlement,
    PlanPrice,
    Subscription,
)
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from ..deps import require_super_admin
from ..security import Principal

router = APIRouter(prefix="/admin", tags=["admin"])
FEATURE = r"^[a-z][a-z0-9_]{0,63}$"


def _err(status_code: int, msg: str, field: str | None = None, **extra) -> HTTPException:
    return HTTPException(status_code, detail={"detail": msg, "field": field, **extra})


# --- plans ------------------------------------------------------------------------------------


class EntitlementIn(BaseModel):
    feature_key: str = Field(pattern=FEATURE)
    enabled: bool = True
    limit_value: int | None = Field(None, ge=0, description="null = unlimited")


class PriceIn(BaseModel):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    cycle: Literal["MONTHLY", "ANNUAL"]
    amount_minor: int = Field(ge=0)


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field("", max_length=1000)
    is_public: bool = True
    is_active: bool = True
    sort_order: int = 0
    entitlements: list[EntitlementIn]
    prices: list[PriceIn] = []
    # Required to lower a limit below what an organisation has already used.
    confirm_below_usage: bool = False
    comment: str = Field(min_length=1, max_length=500)


async def _plan_json(db, plan: Plan) -> dict:
    ents = (
        (
            await db.execute(
                select(PlanEntitlement)
                .where(PlanEntitlement.plan_id == plan.id)
                .order_by(PlanEntitlement.feature_key)
            )
        )
        .scalars()
        .all()
    )
    prices = (
        (
            await db.execute(
                select(PlanPrice)
                .where(PlanPrice.plan_id == plan.id)
                .order_by(PlanPrice.currency, PlanPrice.cycle)
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": plan.id,
        "name": plan.name,
        "description": plan.description,
        "is_public": plan.is_public,
        "is_active": plan.is_active,
        "sort_order": plan.sort_order,
        "entitlements": [
            {"feature_key": e.feature_key, "enabled": e.enabled, "limit_value": e.limit_value}
            for e in ents
        ],
        "prices": [
            {"currency": p.currency, "cycle": p.cycle, "amount_minor": p.amount_minor}
            for p in prices
        ],
    }


@router.get("/plans")
async def list_plans(p: Principal = Depends(require_super_admin)):
    async with admin_session(
        actor_user_id=p.user_id, reason="list plans", action="admin.read"
    ) as db:
        plans = (await db.execute(select(Plan).order_by(Plan.sort_order, Plan.id))).scalars().all()
        return [await _plan_json(db, pl) for pl in plans]


async def _below_usage(db, plan_id: str, ents: list[EntitlementIn]) -> list[dict]:
    """Organisations on this plan that already exceed a NEW limit."""
    hits: list[dict] = []
    for e in ents:
        if e.limit_value is None:
            continue
        if e.feature_key == billing.SEATS:
            sql = (
                "SELECT s.organization_id AS org, count(u.id) AS used FROM subscriptions s "
                "JOIN users u ON u.organization_id = s.organization_id AND u.is_active "
                "WHERE s.plan_id = :p GROUP BY s.organization_id HAVING count(u.id) > :l"
            )
            params = {"p": plan_id, "l": e.limit_value}
        else:
            sql = (
                "SELECT l.organization_id AS org, l.used AS used FROM usage_ledger l "
                "JOIN subscriptions s ON s.organization_id = l.organization_id "
                "WHERE s.plan_id = :p AND l.feature_key = :f AND l.period_start = :d AND l.used > :l"
            )
            params = {
                "p": plan_id,
                "f": e.feature_key,
                "d": billing.period_start(),
                "l": e.limit_value,
            }
        for r in (await db.execute(text(sql), params)).all():
            hits.append(
                {
                    "organization_id": str(r.org),
                    "feature": e.feature_key,
                    "used": r.used,
                    "new_limit": e.limit_value,
                }
            )
    return hits


@router.put("/plans/{plan_id}")
async def upsert_plan(plan_id: str, body: PlanIn, p: Principal = Depends(require_super_admin)):
    if not plan_id.replace("_", "").isalnum() or plan_id != plan_id.upper() or len(plan_id) > 64:
        raise _err(422, "Plan ids are upper-case letters, digits and underscores.", "plan_id")
    keys = [e.feature_key for e in body.entitlements]
    if len(keys) != len(set(keys)):
        raise _err(422, "Each feature can appear once.", "entitlements")
    async with admin_session(
        actor_user_id=p.user_id, reason=body.comment, action="plan.write"
    ) as db:
        if not body.confirm_below_usage and (
            hits := await _below_usage(db, plan_id, body.entitlements)
        ):
            raise _err(
                409,
                f"{len(hits)} organisation(s) already use more than the new limit. Confirm to apply anyway; "
                "they will be blocked from further use until they are under it.",
                "entitlements",
                code="limit_below_usage",
                affected=hits[:20],
            )
        existing = (await db.execute(select(Plan).where(Plan.id == plan_id))).scalar_one_or_none()
        if existing is None:
            db.add(
                Plan(
                    id=plan_id,
                    name=body.name,
                    description=body.description,
                    is_public=body.is_public,
                    is_active=body.is_active,
                    sort_order=body.sort_order,
                )
            )
        else:
            existing.name, existing.description = body.name, body.description
            existing.is_public, existing.is_active, existing.sort_order = (
                body.is_public,
                body.is_active,
                body.sort_order,
            )
        await db.flush()
        await db.execute(delete(PlanEntitlement).where(PlanEntitlement.plan_id == plan_id))
        await db.execute(delete(PlanPrice).where(PlanPrice.plan_id == plan_id))
        db.add_all(PlanEntitlement(plan_id=plan_id, **e.model_dump()) for e in body.entitlements)
        db.add_all(PlanPrice(plan_id=plan_id, **pr.model_dump()) for pr in body.prices)
        db.add(
            AuditLog(
                actor_user_id=p.user_id,
                action="plan.updated" if existing else "plan.created",
                detail={"plan_id": plan_id, "comment": body.comment, "entitlements": keys},
            )
        )
        await db.flush()
        return await _plan_json(
            db, (await db.execute(select(Plan).where(Plan.id == plan_id))).scalar_one()
        )


# --- coupons ----------------------------------------------------------------------------------


class CouponIn(BaseModel):
    code: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    discount_type: Literal["PERCENTAGE", "FIXED_INR"]
    discount_value: int = Field(gt=0, description="percent, or paise for FIXED_INR")
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    max_redemptions: int | None = Field(None, ge=1)
    applicable_plan_ids: list[str] = []


class CouponPatch(BaseModel):
    is_active: bool | None = None
    valid_until: datetime | None = None
    max_redemptions: int | None = Field(None, ge=1)


def _coupon_json(c: Coupon) -> dict:
    return {
        "id": str(c.id),
        "code": c.code,
        "discount_type": c.discount_type,
        "discount_value": c.discount_value,
        "valid_from": c.valid_from,
        "valid_until": c.valid_until,
        "max_redemptions": c.max_redemptions,
        "current_redemptions": c.current_redemptions,
        "applicable_plan_ids": c.applicable_plan_ids,
        "is_active": c.is_active,
    }


@router.get("/coupons")
async def list_coupons(p: Principal = Depends(require_super_admin)):
    async with admin_session(
        actor_user_id=p.user_id, reason="list coupons", action="admin.read"
    ) as db:
        rows = (await db.execute(select(Coupon).order_by(Coupon.created_at.desc()))).scalars().all()
        return [_coupon_json(c) for c in rows]


@router.post("/coupons", status_code=status.HTTP_201_CREATED)
async def create_coupon(body: CouponIn, p: Principal = Depends(require_super_admin)):
    if body.discount_type == "PERCENTAGE" and body.discount_value > 100:
        raise _err(422, "A percentage discount cannot exceed 100.", "discount_value")
    if body.valid_from and body.valid_until and body.valid_until <= body.valid_from:
        raise _err(422, "The end date must be after the start date.", "valid_until")
    try:
        async with admin_session(
            actor_user_id=p.user_id, reason=f"create coupon {body.code}", action="coupon.created"
        ) as db:
            c = Coupon(**{**body.model_dump(), "code": billing.normalise_code(body.code)})
            db.add(c)
            await db.flush()
            await db.refresh(c)
            return _coupon_json(c)
    except IntegrityError:
        raise _err(409, "A coupon with that code already exists.", "code") from None


@router.patch("/coupons/{coupon_id}")
async def update_coupon(
    coupon_id: uuid.UUID, body: CouponPatch, p: Principal = Depends(require_super_admin)
):
    async with admin_session(
        actor_user_id=p.user_id, reason=f"update coupon {coupon_id}", action="coupon.updated"
    ) as db:
        c = (
            await db.execute(select(Coupon).where(Coupon.id == coupon_id).with_for_update())
        ).scalar_one_or_none()
        if c is None:
            raise _err(404, "No such coupon.")
        if body.max_redemptions is not None and body.max_redemptions < c.current_redemptions:
            raise _err(
                422,
                f"{c.current_redemptions} redemptions have already happened; the limit cannot be lower.",
                "max_redemptions",
            )
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(c, k, v)
        await db.flush()
        return _coupon_json(c)


# --- tenants ----------------------------------------------------------------------------------


class AssignIn(BaseModel):
    plan_id: str
    status: Literal["TRIALING", "ACTIVE", "PAST_DUE", "LOCKED_READ_ONLY"] = "ACTIVE"
    billing_cycle: Literal["MONTHLY", "ANNUAL"] = "MONTHLY"
    comment: str = Field(min_length=1, max_length=500)


@router.get("/tenants")
async def tenant_directory(p: Principal = Depends(require_super_admin)):
    async with admin_session(
        actor_user_id=p.user_id, reason="tenant directory", action="admin.cross_tenant_access"
    ) as db:
        rows = (
            await db.execute(
                text(
                    "SELECT o.id, o.name, o.created_at, s.plan_id, s.status, s.trial_ends_at, s.locks_at, "
                    "(SELECT count(*) FROM users u WHERE u.organization_id = o.id AND u.is_active) AS users "
                    "FROM organizations o LEFT JOIN subscriptions s ON s.organization_id = o.id "
                    "ORDER BY o.created_at DESC LIMIT 500"
                )
            )
        ).all()
    out = []
    for r in rows:
        sub = (
            Subscription(
                plan_id=r.plan_id,
                status=r.status,
                trial_ends_at=r.trial_ends_at,
                locks_at=r.locks_at,
            )
            if r.status
            else None
        )
        out.append(
            {
                "id": str(r.id),
                "name": r.name,
                "created_at": r.created_at,
                "plan_id": r.plan_id,
                "status": billing.effective_status(sub) if sub else None,
                "trial_ends_at": r.trial_ends_at,
                "active_users": r.users,
            }
        )
    return out


@router.post("/tenants/{org_id}/plan")
async def assign_plan(
    org_id: uuid.UUID, body: AssignIn, p: Principal = Depends(require_super_admin)
):
    """Manual plan assignment (Phase 1 sells via manual invoices)."""
    async with admin_session(
        actor_user_id=p.user_id, reason=body.comment, action="tenant.plan_assigned"
    ) as db:
        plan = (await db.execute(select(Plan).where(Plan.id == body.plan_id))).scalar_one_or_none()
        if plan is None or not plan.is_active:
            raise _err(422, "That plan does not exist or is not active.", "plan_id")
        sub = (
            await db.execute(
                select(Subscription).where(Subscription.organization_id == org_id).with_for_update()
            )
        ).scalar_one_or_none()
        if sub is None:
            raise _err(404, "No such organisation.")
        before = {"plan_id": sub.plan_id, "status": sub.status}
        sub.plan_id, sub.status, sub.billing_cycle = body.plan_id, body.status, body.billing_cycle
        if body.status != "TRIALING":
            sub.trial_ends_at = sub.locks_at = None
        db.add(
            AuditLog(
                organization_id=org_id,
                actor_user_id=p.user_id,
                action="tenant.plan_assigned",
                detail={
                    "before": before,
                    "after": {"plan_id": body.plan_id, "status": body.status},
                    "comment": body.comment,
                },
            )
        )
        return {"organization_id": str(org_id), "plan_id": sub.plan_id, "status": sub.status}


@router.get("/trial-funnel")
async def trial_funnel(p: Principal = Depends(require_super_admin)):
    async with admin_session(
        actor_user_id=p.user_id, reason="trial funnel", action="admin.cross_tenant_access"
    ) as db:
        by_status = {
            r.status: r.n
            for r in (
                await db.execute(
                    text("SELECT status, count(*) AS n FROM subscriptions GROUP BY status")
                )
            ).all()
        }
        signups_30d = (
            await db.execute(
                text(
                    "SELECT count(*) FROM organizations WHERE created_at > now() - interval '30 days'"
                )
            )
        ).scalar_one()
        trialing_ending_7d = (
            await db.execute(
                text(
                    "SELECT count(*) FROM subscriptions WHERE status='TRIALING' AND trial_ends_at BETWEEN now() AND now() + interval '7 days'"
                )
            )
        ).scalar_one()
    return {
        "by_status": by_status,
        "signups_last_30_days": signups_30d,
        "trials_ending_within_7_days": trialing_ending_7d,
    }
