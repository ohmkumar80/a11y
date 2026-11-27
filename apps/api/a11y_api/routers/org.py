import uuid
from datetime import UTC, datetime, timedelta

from a11y_core import billing
from a11y_core.db import login_lookup_session, tenant_session
from a11y_core.models import AuthToken, Organization, PlanEntitlement, TokenKind, User
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from .. import mail as mailmod
from ..deps import current_principal, require_company_admin
from ..schemas import InviteAcceptIn, InviteIn, UserOut
from ..security import Principal, hash_password, hash_token, new_token, password_problem, token_org
from .auth import ACCEPTED, INVALID_LINK, _bad_password, _consume

router = APIRouter(tags=["org"])
INVITE_TTL = timedelta(days=7)


@router.get("/me", response_model=UserOut)
async def me(p: Principal = Depends(current_principal)):
    async with tenant_session(p.org_id) as db:
        u = (await db.execute(select(User).where(User.id == p.user_id))).scalar_one_or_none()
        org = (await db.execute(select(Organization.name))).scalar_one_or_none()
    if u is None or not u.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return UserOut(
        id=str(u.id),
        email=u.email,
        role=u.role,
        organization_id=str(p.org_id),
        organization_name=org or "",
        mfa_enabled=u.mfa_enabled_at is not None,
    )


@router.get("/org/flags")
async def my_flags(p: Principal = Depends(current_principal)):
    """Which features are switched on for this organisation, so the UI can leave out what is off."""
    from a11y_core import flags  # noqa: PLC0415

    async with tenant_session(p.org_id) as db:
        plan_id = (await billing.load_subscription(db)).plan_id
    return (await flags.effective_flags(p.org_id, plan_id)).model_dump()


@router.get("/org/subscription")
async def subscription(p: Principal = Depends(current_principal)):
    """Everything the plan/quota UI needs: status, trial end, seats used of limit, quota meters."""
    async with tenant_session(p.org_id) as db:
        sub = await billing.load_subscription(db)
        plan = (
            await db.execute(text("SELECT name FROM plans WHERE id=:i"), {"i": sub.plan_id})
        ).scalar_one()
        used, limit = await billing.seat_usage(db, sub.plan_id)
        ents = (
            (
                await db.execute(
                    select(PlanEntitlement)
                    .where(PlanEntitlement.plan_id == sub.plan_id)
                    .order_by(PlanEntitlement.feature_key)
                )
            )
            .scalars()
            .all()
        )
        meters = []
        for e in ents:
            if e.feature_key == billing.SEATS or e.feature_key.startswith("pages_per"):
                continue  # not a monthly meter
            meters.append(
                {
                    "feature": e.feature_key,
                    "enabled": e.enabled,
                    "used": await billing.usage_used(db, e.feature_key),
                    "limit": e.limit_value,
                }
            )
        coupon = None
        if sub.applied_coupon_id:
            coupon = (
                await db.execute(
                    text("SELECT terms FROM coupon_redemptions WHERE coupon_id=:c"),
                    {"c": sub.applied_coupon_id},
                )
            ).scalar_one_or_none()
        return {
            "plan": {"id": sub.plan_id, "name": plan},
            "status": billing.effective_status(sub),
            "trial_ends_at": sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
            "seats": {"used": used, "limit": limit},
            "quotas": meters,
            "coupon": coupon,
        }


class CouponIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)


@router.post("/org/coupon")
async def redeem_coupon(body: CouponIn, p: Principal = Depends(require_company_admin)):
    async with tenant_session(p.org_id) as db:
        terms = await billing.redeem_coupon(db, p.org_id, body.code)
    return {"applied": terms}


@router.get("/org/users", response_model=list[UserOut])
async def list_users(p: Principal = Depends(require_company_admin)):
    async with tenant_session(p.org_id) as db:
        rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
        org = (await db.execute(select(Organization.name))).scalar_one()
    return [
        UserOut(
            id=str(u.id),
            email=u.email,
            role=u.role,
            organization_id=str(p.org_id),
            organization_name=org,
        )
        for u in rows
    ]


@router.post("/invites", status_code=status.HTTP_202_ACCEPTED)
async def create_invite(
    body: InviteIn,
    bg: BackgroundTasks,
    p: Principal = Depends(require_company_admin),
    mailer: mailmod.Mailer = Depends(mailmod.get_mailer),
):
    email = body.email.lower()
    async with login_lookup_session(email) as db:
        exists = (await db.execute(select(User.id).where(User.email == email))).first() is not None
    if exists:
        return ACCEPTED  # don't reveal that the address already has an account
    raw, hashed = new_token(p.org_id)
    async with tenant_session(p.org_id) as db:
        # Locks the subscription row: two simultaneous invites cannot both take the last seat.
        await billing.check_seat_available(db)
        db.add(
            AuthToken(
                organization_id=p.org_id,
                kind=TokenKind.INVITE,
                token_hash=hashed,
                invited_email=email,
                invited_role=body.role,
                expires_at=datetime.now(UTC) + INVITE_TTL,
            )
        )
        org_name = (await db.execute(select(Organization.name))).scalar_one()
    bg.add_task(mailer.send, await mailmod.invite_mail(email, raw, org_name))
    return ACCEPTED


@router.get("/invites/{token}")
async def preview_invite(token: str):
    """Lets the accept page show the org and pre-fill the email (SC 3.3.7 Redundant Entry)."""
    org_id = token_org(token)
    if org_id is None:
        raise INVALID_LINK
    async with tenant_session(org_id) as db:
        tok = (
            await db.execute(
                select(AuthToken).where(
                    AuthToken.token_hash == hash_token(token), AuthToken.kind == TokenKind.INVITE
                )
            )
        ).scalar_one_or_none()
        if tok is None or tok.used_at or tok.revoked_at or tok.expires_at <= datetime.now(UTC):
            raise INVALID_LINK
        org = (await db.execute(select(Organization.name))).scalar_one()
    return {"email": tok.invited_email, "organization_name": org}


@router.post("/invites/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_invite(body: InviteAcceptIn):
    org_id = token_org(body.token)
    if org_id is None:
        raise INVALID_LINK
    try:
        async with tenant_session(org_id) as db:
            peek = (
                await db.execute(
                    select(AuthToken).where(
                        AuthToken.token_hash == hash_token(body.token),
                        AuthToken.kind == TokenKind.INVITE,
                    )
                )
            ).scalar_one_or_none()
            if (
                peek is None
                or peek.used_at
                or peek.revoked_at
                or peek.expires_at <= datetime.now(UTC)
            ):
                raise INVALID_LINK
            if problem := password_problem(body.password, peek.invited_email):
                raise _bad_password(problem)
            await billing.check_seat_available(db, accepting_invite=True)
            tok = await _consume(db, body.token, TokenKind.INVITE)
            if tok is None:
                raise INVALID_LINK
            db.add(
                User(
                    id=uuid.uuid4(),
                    organization_id=org_id,
                    email=tok.invited_email,
                    hashed_password=hash_password(body.password),
                    role=tok.invited_role,
                    email_verified_at=datetime.now(UTC),
                )
            )
            await db.flush()
    except IntegrityError:
        raise INVALID_LINK from None
