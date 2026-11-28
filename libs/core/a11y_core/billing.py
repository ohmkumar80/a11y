"""Subscriptions, seats, quota reservations and coupons (PROJECT_PLAN 3.5).

Every function takes a tenant-scoped ``AsyncSession`` (``tenant_session``) so RLS confines it to
one organisation, and does its checks with a single atomic statement or a row lock - never
read-then-write - so parallel requests cannot overspend a quota, a seat limit or a coupon.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Coupon,
    CouponRedemption,
    PlanEntitlement,
    ReservationStatus,
    Subscription,
    SubscriptionStatus,
    UsageReservation,
)

SEATS = "seats"
UPGRADE_PATH = "/org#plan"
FIX_FEATURE = (
    "ai_code_fixes_monthly"  # one credit per fix an AI model produced and our checks accepted
)
# Entitlements that are switches, not monthly counters: they never appear as usage meters.
NON_METERS = frozenset({"api_access", "byok_ai"})


class BillingError(Exception):
    """Base for errors the API turns into a structured, user-facing response."""

    code = "billing_error"
    status_code = 409
    field: str | None = None

    def __init__(self, message: str, **extra) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra

    def body(self) -> dict:
        b = {"detail": self.message, "code": self.code, **self.extra}
        if self.field:
            b["field"] = self.field
        return b


class SubscriptionLocked(BillingError):
    code = "subscription_locked"
    status_code = 403


class QuotaExceeded(BillingError):
    code = "quota_exceeded"
    status_code = 402


class FeatureNotInPlan(QuotaExceeded):
    code = "feature_not_in_plan"


class SeatLimitReached(QuotaExceeded):
    code = "seat_limit_reached"


class CouponError(BillingError):
    code = "coupon_invalid"
    status_code = 422
    field = "code"


def now_utc() -> datetime:
    return datetime.now(UTC)


def period_start(now: datetime | None = None) -> date:
    n = now or now_utc()
    return date(n.year, n.month, 1)


def effective_status(sub: Subscription, now: datetime | None = None) -> str:
    """Stored status, corrected for a trial that has run out. The request guard uses THIS, so a
    missed or late cron job can never extend a trial (the hourly job only persists it)."""
    n = now or now_utc()
    if sub.status == SubscriptionStatus.TRIALING:
        deadline = sub.locks_at or sub.trial_ends_at
        if deadline is not None and n >= deadline:
            return SubscriptionStatus.LOCKED_READ_ONLY
    return sub.status


def is_writable(status: str) -> bool:
    return status in (
        SubscriptionStatus.TRIALING,
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.PAST_DUE,
    )


async def load_subscription(db: AsyncSession, *, lock: bool = False) -> Subscription:
    q = select(Subscription)
    if lock:
        q = q.with_for_update()
    sub = (await db.execute(q)).scalar_one_or_none()
    if sub is None:
        raise SubscriptionLocked("This organisation has no subscription.")
    return sub


async def require_writable(db: AsyncSession, *, lock: bool = False) -> Subscription:
    sub = await load_subscription(db, lock=lock)
    if not is_writable(effective_status(sub)):
        raise SubscriptionLocked(
            "Your trial has ended, so this organisation is read-only. Upgrade to continue.",
            upgrade_url=UPGRADE_PATH,
        )
    return sub


@dataclass(frozen=True)
class Entitlement:
    enabled: bool
    limit: int | None  # None = unlimited
    custom: bool = (
        False  # True when a platform administrator set an exception for this organisation
    )


async def entitlement(db: AsyncSession, plan_id: str, feature: str) -> Entitlement:
    """What this organisation may do with ``feature``: its plan's row, unless a platform administrator set an unexpired
    override for this organisation (a negotiated exception). ``app_org_id()`` limits the lookup to the organisation the
    session belongs to, so cross-tenant admin reads never pick up somebody else's override."""
    ov = (
        await db.execute(
            text(
                "SELECT enabled, limit_value FROM entitlement_overrides WHERE organization_id = app_org_id() "
                "AND feature_key = :f AND (expires_at IS NULL OR expires_at > now())"
            ),
            {"f": feature},
        )
    ).first()
    if ov is not None:
        return Entitlement(ov.enabled, ov.limit_value, custom=True)
    row = (
        await db.execute(
            select(PlanEntitlement).where(
                PlanEntitlement.plan_id == plan_id, PlanEntitlement.feature_key == feature
            )
        )
    ).scalar_one_or_none()
    return Entitlement(False, 0) if row is None else Entitlement(row.enabled, row.limit_value)


# --- trial -------------------------------------------------------------------------------------


async def start_trial(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    plan_id: str,
    length_days: int,
    grace_days: int,
    now: datetime | None = None,
) -> Subscription:
    n = now or now_utc()
    ends = n + timedelta(days=length_days)
    sub = Subscription(
        organization_id=org_id,
        plan_id=plan_id,
        status=SubscriptionStatus.TRIALING,
        trial_ends_at=ends,
        locks_at=ends + timedelta(days=grace_days),
    )
    db.add(sub)
    await db.flush()
    return sub


# --- seats -------------------------------------------------------------------------------------


async def seat_usage(
    db: AsyncSession, plan_id: str, now: datetime | None = None
) -> tuple[int, int | None]:
    """(seats taken, limit). Taken = active users + invitations still open."""
    n = now or now_utc()
    users = (await db.execute(text("SELECT count(*) FROM users WHERE is_active"))).scalar_one()
    invites = (
        await db.execute(
            text(
                "SELECT count(*) FROM auth_tokens WHERE kind='INVITE' AND used_at IS NULL "
                "AND revoked_at IS NULL AND expires_at > :n"
            ),
            {"n": n},
        )
    ).scalar_one()
    ent = await entitlement(db, plan_id, SEATS)
    return users + invites, (ent.limit if ent.enabled else 0)


async def check_seat_available(db: AsyncSession, *, accepting_invite: bool = False) -> None:
    """Call inside the transaction that adds the user/invite. Locks the subscription row so two
    concurrent invites cannot both take the last seat.

    ``accepting_invite``: the invitation being redeemed already holds a seat, so only the
    active-user count matters (it is re-checked in case the plan was downgraded meanwhile)."""
    sub = await require_writable(db, lock=True)
    used, limit = await seat_usage(db, sub.plan_id)
    if accepting_invite:
        used = (await db.execute(text("SELECT count(*) FROM users WHERE is_active"))).scalar_one()
    if limit is not None and used >= limit:
        raise SeatLimitReached(
            f"All {limit} seats are in use. Upgrade your plan to add more people.",
            used=used,
            limit=limit,
            upgrade_url=UPGRADE_PATH,
        )


# --- quota reservations ------------------------------------------------------------------------


@dataclass(frozen=True)
class Reservation:
    job_id: str
    feature: str
    amount: int
    status: str
    created: bool  # False when this job had already reserved (idempotent retry)


async def reserve(
    db: AsyncSession,
    org_id: uuid.UUID,
    feature: str,
    job_id: str,
    amount: int = 1,
    now: datetime | None = None,
) -> Reservation:
    """Atomically reserve credits before enqueuing a job. Raises QuotaExceeded (and the caller's
    transaction rolls back, so no reservation row is left behind)."""
    if amount < 1:
        raise ValueError("amount must be positive")
    sub = await require_writable(db)
    ent = await entitlement(db, sub.plan_id, feature)
    if not ent.enabled:
        raise QuotaExceeded(
            f"Your plan does not include {feature}.", feature=feature, upgrade_url=UPGRADE_PATH
        )
    period = period_start(now)
    inserted = (
        await db.execute(
            text(
                "INSERT INTO usage_reservations (id, organization_id, feature_key, job_id, period_start, amount, status) "
                "VALUES (gen_random_uuid(), :o, :f, :j, :p, :a, 'RESERVED') "
                "ON CONFLICT (organization_id, feature_key, job_id) DO NOTHING RETURNING status"
            ),
            {"o": org_id, "f": feature, "j": job_id, "p": period, "a": amount},
        )
    ).first()
    if inserted is None:  # this job already reserved: don't charge twice
        existing = (
            await db.execute(
                select(UsageReservation).where(
                    UsageReservation.feature_key == feature, UsageReservation.job_id == job_id
                )
            )
        ).scalar_one()
        return Reservation(job_id, feature, existing.amount, existing.status, created=False)
    await db.execute(
        text(
            "INSERT INTO usage_ledger (organization_id, feature_key, period_start, used) "
            "VALUES (:o, :f, :p, 0) ON CONFLICT DO NOTHING"
        ),
        {"o": org_id, "f": feature, "p": period},
    )
    # The whole check is this one conditional UPDATE: it row-locks the ledger entry, so a
    # concurrent reserve waits, re-evaluates `used + n <= limit`, and fails if it no longer fits.
    got = (
        await db.execute(
            text(
                "UPDATE usage_ledger SET used = used + :a "
                "WHERE organization_id=:o AND feature_key=:f AND period_start=:p "
                "AND (CAST(:lim AS bigint) IS NULL OR used + :a <= CAST(:lim AS bigint)) RETURNING used"
            ),
            {"o": org_id, "f": feature, "p": period, "a": amount, "lim": ent.limit},
        )
    ).first()
    if got is None:
        used = (
            await db.execute(
                text(
                    "SELECT used FROM usage_ledger WHERE organization_id=:o AND feature_key=:f AND period_start=:p"
                ),
                {"o": org_id, "f": feature, "p": period},
            )
        ).scalar_one()
        raise QuotaExceeded(
            f"You have used {used} of {ent.limit} this month. Upgrade your plan for more.",
            feature=feature,
            used=used,
            limit=ent.limit,
            upgrade_url=UPGRADE_PATH,
        )
    return Reservation(job_id, feature, amount, ReservationStatus.RESERVED, created=True)


async def _settle(db: AsyncSession, feature: str, job_id: str, to: ReservationStatus) -> bool:
    row = (
        await db.execute(
            update(UsageReservation)
            .where(
                UsageReservation.feature_key == feature,
                UsageReservation.job_id == job_id,
                UsageReservation.status == ReservationStatus.RESERVED,
            )
            .values(status=to, settled_at=func.now())
            .returning(
                UsageReservation.organization_id,
                UsageReservation.period_start,
                UsageReservation.amount,
            )
        )
    ).first()
    if row is None:
        return False  # unknown or already settled: idempotent
    if to is ReservationStatus.RELEASED:
        await db.execute(
            text(
                "UPDATE usage_ledger SET used = used - :a "
                "WHERE organization_id=:o AND feature_key=:f AND period_start=:p"
            ),
            {"a": row.amount, "o": row.organization_id, "f": feature, "p": row.period_start},
        )
    return True


async def commit_usage(db: AsyncSession, feature: str, job_id: str) -> bool:
    """The job ran (including failures caused by the user, e.g. a bad URL): keep the charge."""
    return await _settle(db, feature, job_id, ReservationStatus.COMMITTED)


async def release_usage(db: AsyncSession, feature: str, job_id: str) -> bool:
    """The platform failed the job: give the credit back."""
    return await _settle(db, feature, job_id, ReservationStatus.RELEASED)


async def usage_used(db: AsyncSession, feature: str, now: datetime | None = None) -> int:
    return (
        await db.execute(
            text(
                "SELECT coalesce(sum(used), 0) FROM usage_ledger WHERE feature_key=:f AND period_start=:p"
            ),
            {"f": feature, "p": period_start(now)},
        )
    ).scalar_one()


# --- coupons -----------------------------------------------------------------------------------


def normalise_code(code: str) -> str:
    return "".join(code.split()).upper()


async def redeem_coupon(db: AsyncSession, org_id: uuid.UUID, code: str) -> dict:
    """Apply a coupon to the organisation. The counter bump is one conditional UPDATE, and the
    unique (coupon, org) constraint stops a repeat; if either fails the whole transaction (and
    the counter increment) rolls back."""
    sub = await require_writable(db, lock=True)
    n = now_utc()
    coupon = (
        await db.execute(select(Coupon).where(Coupon.code == normalise_code(code)))
    ).scalar_one_or_none()
    if coupon is None or not coupon.is_active:
        raise CouponError("That coupon code is not valid. Check it and try again.")
    if coupon.valid_from and n < coupon.valid_from:
        raise CouponError("That coupon is not valid yet.")
    if coupon.valid_until and n >= coupon.valid_until:
        raise CouponError("That coupon has expired.")
    if coupon.applicable_plan_ids and sub.plan_id not in coupon.applicable_plan_ids:
        raise CouponError("That coupon does not apply to your current plan.")
    if sub.applied_coupon_id is not None:
        raise CouponError("This organisation already has a coupon applied.")
    bumped = (
        await db.execute(
            text(
                "UPDATE coupons SET current_redemptions = current_redemptions + 1 "
                "WHERE id=:id AND is_active AND (max_redemptions IS NULL OR current_redemptions < max_redemptions) "
                "RETURNING id"
            ),
            {"id": coupon.id},
        )
    ).first()
    if bumped is None:
        raise CouponError("That coupon has reached its redemption limit.")
    terms = {"code": coupon.code, "type": coupon.discount_type, "value": coupon.discount_value}
    try:
        async with db.begin_nested():
            db.add(CouponRedemption(coupon_id=coupon.id, organization_id=org_id, terms=terms))
            await db.flush()
    except IntegrityError:
        raise CouponError("This organisation has already used that coupon.") from None
    await db.execute(
        update(Subscription)
        .where(Subscription.organization_id == org_id)
        .values(applied_coupon_id=coupon.id, updated_at=func.now())
    )
    return terms
