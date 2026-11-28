"""Two-step verification: the sign-in steps (verify / enrol) and account security for people already signed in.

Policy lives in the admin-configurable ``auth.mfa`` setting (off / optional / required per group). Safeguards:
a half-finished sign-in is a token with audience "mfa" that cannot be used as a session; five wrong codes lock the
account for 15 minutes; a code can be used once (replay protection); every failure and every change is audit-logged;
the secret is encrypted at rest and shown only during enrolment; recovery codes are shown once."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from a11y_core import mfa
from a11y_core.config import definitions as _definitions  # noqa: F401
from a11y_core.config import get_config
from a11y_core.config.crypto import get_box
from a11y_core.db import admin_session, login_lookup_session, tenant_session
from a11y_core.models import AuditLog, Role, User
from a11y_core.settings import get_settings
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update

from ..deps import _decode
from ..schemas import (
    EnrolledSession,
    MfaChallenge,
    MfaCodeIn,
    MfaConfirmIn,
    MfaTokenIn,
    MfaVerifyIn,
    SessionOut,
)
from ..security import Principal, decode_mfa_token, issue_mfa_token
from .auth import finish_login

router = APIRouter(prefix="/auth/mfa", tags=["mfa"])
MAX_FAILURES = 5
LOCK_FOR = timedelta(minutes=15)
BAD_CODE = "That code is not correct. Check the code in your authenticator app and try again."


# --- policy ------------------------------------------------------------------------------------------------


async def policy_for(role: str) -> tuple[mfa.Mode, str]:
    """(mode, issuer) for a role. Production never allows 'off' for platform administrators, whatever is stored."""
    p = (await get_config().effective("auth.mfa")).value
    if role == Role.SUPER_ADMIN:
        mode = (
            "required"
            if (get_settings().env == "production" and p.super_admin == "off")
            else p.super_admin
        )
    elif role == Role.COMPANY_ADMIN:
        mode = p.org_admin
    else:
        mode = "off"
    return mode, p.issuer


async def challenge_for(user: User) -> MfaChallenge | None:
    mode, issuer = await policy_for(user.role)
    need = mfa.requirement(mode, user.mfa_enabled_at is not None)
    if need == "none":
        return None
    token, ttl = issue_mfa_token(user.id, user.organization_id, user.role, user.email, need)
    return MfaChallenge(mfa=need, mfa_token=token, expires_in=ttl, issuer=issuer)


# --- helpers -----------------------------------------------------------------------------------------------


@asynccontextmanager
async def _session(org_id: uuid.UUID | None, email: str):
    """The user's own row: tenant session for organisation users, email lookup for a Super Admin (no tenant)."""
    if org_id is not None:
        async with tenant_session(org_id) as db:
            yield db
    else:
        async with login_lookup_session(email) as db:
            yield db


async def _audit(
    org_id: uuid.UUID | None, user_id: uuid.UUID, action: str, detail: dict | None = None
) -> None:
    if org_id is not None:
        async with tenant_session(org_id) as db:
            db.add(
                AuditLog(
                    organization_id=org_id,
                    actor_user_id=user_id,
                    action=action,
                    detail=detail or {},
                )
            )
    else:  # platform operators have no tenant: the audited admin role writes the row
        async with admin_session(actor_user_id=user_id, reason=action, action=action):
            pass


def _bad(
    msg: str, field: str = "code", http: int = status.HTTP_422_UNPROCESSABLE_CONTENT, **extra
) -> HTTPException:
    return HTTPException(http, detail={"detail": msg, "field": field, **extra})


def _locked(user: User) -> HTTPException | None:
    if user.mfa_locked_until and user.mfa_locked_until > datetime.now(UTC):
        mins = max(1, int((user.mfa_locked_until - datetime.now(UTC)).total_seconds() // 60) + 1)
        return _bad(
            f"Too many incorrect codes. Try again in {mins} {'minute' if mins == 1 else 'minutes'}.",
            http=status.HTTP_429_TOO_MANY_REQUESTS,
            code="mfa_locked",
        )
    return None


async def _load(org_id: uuid.UUID | None, email: str, user_id: uuid.UUID) -> User:
    async with _session(org_id, email) as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in again.")
    return user


async def _fail(user: User) -> None:
    n = user.mfa_failed + 1
    lock = n >= MAX_FAILURES
    async with _session(user.organization_id, user.email) as db:
        await db.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                mfa_failed=0 if lock else n,
                mfa_locked_until=datetime.now(UTC) + LOCK_FOR if lock else None,
            )
        )
    await _audit(user.organization_id, user.id, "auth.mfa_locked" if lock else "auth.mfa_failed")


async def _check(user: User, code: str, recovery_code: str = "") -> bool:
    """Verify a TOTP code or spend a recovery code. Updates replay/lockout state."""
    if (e := _locked(user)) is not None:
        raise e
    secret = get_box().decrypt(user.mfa_secret_ct) if user.mfa_secret_ct else None
    step = (
        mfa.verify_totp(secret, code, last_step=user.mfa_last_step)
        if (secret and code.strip())
        else None
    )
    rest = (
        mfa.consume_recovery(list(user.mfa_recovery or []), recovery_code)
        if (recovery_code.strip() and secret)
        else None
    )
    if step is None and rest is None:
        await _fail(user)
        return False
    values: dict = {"mfa_failed": 0, "mfa_locked_until": None}
    if step is not None:
        values["mfa_last_step"] = step
    else:
        values["mfa_recovery"] = rest
    async with _session(user.organization_id, user.email) as db:
        await db.execute(update(User).where(User.id == user.id).values(**values))
    if step is None:
        await _audit(
            user.organization_id,
            user.id,
            "auth.mfa_recovery_code_used",
            {"remaining": len(rest or [])},
        )
    return True


def _setup_payload(user: User, secret: str, issuer: str) -> dict:
    return {
        "key": mfa.format_key(secret),
        "otpauth_uri": mfa.otpauth_uri(secret, user.email, issuer),
        "issuer": issuer,
        "account": user.email,
    }


async def _start_enrolment(user: User, issuer: str) -> dict:
    if user.mfa_enabled_at is not None:
        raise _bad(
            "Two-step verification is already on for this account.",
            field="",
            http=status.HTTP_409_CONFLICT,
            code="mfa_already_enrolled",
        )
    secret = mfa.new_secret()
    async with _session(user.organization_id, user.email) as db:
        await db.execute(
            update(User).where(User.id == user.id).values(mfa_pending_ct=get_box().encrypt(secret))
        )
    return _setup_payload(user, secret, issuer)


async def _confirm_enrolment(user: User, code: str) -> list[str]:
    if (e := _locked(user)) is not None:
        raise e
    if user.mfa_enabled_at is not None or not user.mfa_pending_ct:
        raise _bad(
            "Start setting up two-step verification first.",
            field="",
            http=status.HTTP_409_CONFLICT,
            code="mfa_not_started",
        )
    secret = get_box().decrypt(user.mfa_pending_ct)
    step = mfa.verify_totp(secret, code)
    if step is None:
        await _fail(user)
        raise _bad(BAD_CODE)
    codes = mfa.new_recovery_codes()
    async with _session(user.organization_id, user.email) as db:
        await db.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                mfa_secret_ct=user.mfa_pending_ct,
                mfa_pending_ct=None,
                mfa_enabled_at=datetime.now(UTC),
                mfa_last_step=step,
                mfa_recovery=[mfa.hash_recovery(c) for c in codes],
                mfa_failed=0,
                mfa_locked_until=None,
            )
        )
    await _audit(user.organization_id, user.id, "auth.mfa_enrolled")
    return codes


# --- sign-in steps (authenticated only by the short-lived mfa token) -----------------------------------------


@router.post("/verify", response_model=SessionOut)
async def verify(body: MfaVerifyIn, response: Response):
    t = decode_mfa_token(body.mfa_token, "verify")
    if t is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={
                "detail": "Your sign-in took too long. Sign in again.",
                "code": "mfa_token_expired",
            },
        )
    user = await _load(t.org_id, t.email, t.user_id)
    if user.mfa_enabled_at is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in again.")
    if not body.code.strip() and not body.recovery_code.strip():
        raise _bad("Enter the code from your authenticator app.")
    if not await _check(user, body.code, body.recovery_code):
        raise _bad(BAD_CODE, field="recovery_code" if body.recovery_code.strip() else "code")
    return await finish_login(user, response, mfa_verified=True)


@router.post("/enroll/start")
async def enroll_start(body: MfaTokenIn):
    t = decode_mfa_token(body.mfa_token, "enroll")
    if t is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={
                "detail": "Your sign-in took too long. Sign in again.",
                "code": "mfa_token_expired",
            },
        )
    user = await _load(t.org_id, t.email, t.user_id)
    _, issuer = await policy_for(user.role)
    return await _start_enrolment(user, issuer)


@router.post("/enroll/confirm", response_model=EnrolledSession)
async def enroll_confirm(body: MfaConfirmIn, response: Response):
    t = decode_mfa_token(body.mfa_token, "enroll")
    if t is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={
                "detail": "Your sign-in took too long. Sign in again.",
                "code": "mfa_token_expired",
            },
        )
    user = await _load(t.org_id, t.email, t.user_id)
    codes = await _confirm_enrolment(user, body.code)
    user = await _load(t.org_id, t.email, t.user_id)
    session = await finish_login(user, response, mfa_verified=True)
    return EnrolledSession(**session.model_dump(), recovery_codes=codes)


# --- account security for someone already signed in ---------------------------------------------------------------


async def _me(p: Principal) -> User:
    if p.email is None and p.org_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in again.")
    return await _load(p.org_id, p.email or "", p.user_id)


@router.get("/status")
async def mfa_status(p: Principal = Depends(_decode)):
    user = await _me(p)
    mode, _ = await policy_for(user.role)
    return {
        "enabled": user.mfa_enabled_at is not None,
        "mode": mode,
        "required": mode == "required",
        "recovery_codes_left": len(user.mfa_recovery or []),
        "available": user.role in (Role.SUPER_ADMIN, Role.COMPANY_ADMIN),
    }


@router.post("/setup/start")
async def setup_start(p: Principal = Depends(_decode)):
    user = await _me(p)
    if user.role not in (Role.SUPER_ADMIN, Role.COMPANY_ADMIN):
        raise _bad(
            "Two-step verification is available to administrators.",
            field="",
            http=status.HTTP_403_FORBIDDEN,
        )
    _, issuer = await policy_for(user.role)
    return await _start_enrolment(user, issuer)


@router.post("/setup/confirm")
async def setup_confirm(body: MfaCodeIn, p: Principal = Depends(_decode)):
    user = await _me(p)
    return {"recovery_codes": await _confirm_enrolment(user, body.code)}


@router.post("/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable(body: MfaCodeIn, p: Principal = Depends(_decode)):
    user = await _me(p)
    mode, _ = await policy_for(user.role)
    if mode == "required":
        raise _bad(
            "Your organisation requires two-step verification, so it cannot be turned off.",
            field="",
            http=status.HTTP_409_CONFLICT,
            code="mfa_required",
        )
    if user.mfa_enabled_at is None:
        return
    if not await _check(user, body.code, body.code if "-" in body.code else ""):
        raise _bad(BAD_CODE)
    async with _session(user.organization_id, user.email) as db:
        await db.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                mfa_secret_ct=None,
                mfa_pending_ct=None,
                mfa_enabled_at=None,
                mfa_recovery=[],
                mfa_last_step=0,
            )
        )
    await _audit(user.organization_id, user.id, "auth.mfa_disabled")


@router.post("/recovery-codes")
async def new_recovery_codes(body: MfaCodeIn, p: Principal = Depends(_decode)):
    user = await _me(p)
    if user.mfa_enabled_at is None:
        raise _bad(
            "Turn on two-step verification first.",
            field="",
            http=status.HTTP_409_CONFLICT,
            code="mfa_not_enabled",
        )
    if not await _check(user, body.code):
        raise _bad(BAD_CODE)
    codes = mfa.new_recovery_codes()
    async with _session(user.organization_id, user.email) as db:
        await db.execute(
            update(User)
            .where(User.id == user.id)
            .values(mfa_recovery=[mfa.hash_recovery(c) for c in codes])
        )
    await _audit(user.organization_id, user.id, "auth.mfa_recovery_codes_regenerated")
    return {"recovery_codes": codes}
