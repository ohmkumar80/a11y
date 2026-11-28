import secrets
import uuid
from datetime import UTC, datetime, timedelta

from a11y_core import billing
from a11y_core import mfa as mfalib
from a11y_core.config import definitions as _definitions  # noqa: F401
from a11y_core.config import get_config
from a11y_core.db import (
    app_engine,
    login_lookup_session,
    platform_session,
    set_platform_family,
    tenant_session,
)
from a11y_core.models import (
    PLATFORM_ROLES,
    AuthToken,
    Organization,
    PlatformSession,
    Role,
    TokenKind,
    User,
)
from a11y_core.settings import get_settings
from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from .. import mail as mailmod
from ..schemas import (
    EmailIn,
    LoginIn,
    MfaChallenge,
    ResetConfirmIn,
    SessionOut,
    SignupIn,
    TokenIn,
    UserOut,
)
from ..security import (
    Principal,
    hash_password,
    hash_token,
    issue_access_token,
    needs_rehash,
    new_token,
    password_problem,
    token_org,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "a11y_refresh"
# The web app proxies the API under /api, so the cookie is only ever sent to auth endpoints.
REFRESH_COOKIE_PATH = "/api/auth"
VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(hours=1)

ACCEPTED = {"message": "If that is possible, we have sent an email. Check your inbox."}
INVALID_LINK = HTTPException(
    status.HTTP_400_BAD_REQUEST,
    detail="This link is invalid or has expired. Request a new one.",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _bad_password(msg: str) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"detail": msg, "field": "password"}
    )


def _set_refresh_cookie(response: Response, raw: str) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=s.refresh_token_ttl_days * 86400,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


PLATFORM_COOKIE = "a11y_platform"
PLATFORM_TTL = timedelta(hours=12)  # one token; it rotates on every refresh
PLATFORM_MAX_AGE = timedelta(
    hours=24
)  # a sign-in can never be extended past this, however often it refreshes


def _set_platform_cookie(response: Response, raw: str) -> None:
    s = get_settings()
    response.set_cookie(
        PLATFORM_COOKIE,
        raw,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=int(PLATFORM_TTL.total_seconds()),
    )


def _clear_platform_cookie(response: Response) -> None:
    response.delete_cookie(PLATFORM_COOKIE, path=REFRESH_COOKIE_PATH)


async def _start_platform_session(
    user: User,
    response: Response,
    *,
    family: uuid.UUID | None = None,
    started: datetime | None = None,
    mfa_verified: bool = False,
) -> None:
    """A Super Admin has no tenant, so their refresh token lives in platform_sessions (see migration 0010)."""
    raw = secrets.token_urlsafe(32)
    h = hash_token(raw)
    now = _now()
    started = started or now
    async with platform_session(h) as db:
        db.add(
            PlatformSession(
                token_hash=h,
                family_id=family or uuid.uuid4(),
                user_id=user.id,
                email=user.email,
                mfa_verified=mfa_verified,
                family_started_at=started,
                expires_at=min(now + PLATFORM_TTL, started + PLATFORM_MAX_AGE),
            )
        )
    _set_platform_cookie(response, raw)


def _user_out(u: User, org_name: str) -> UserOut:
    return UserOut(
        id=str(u.id),
        email=u.email,
        role=u.role,
        organization_id=str(u.organization_id),
        organization_name=org_name,
        mfa_enabled=u.mfa_enabled_at is not None,
    )


async def _start_session(
    user: User,
    org_name: str,
    response: Response,
    family: uuid.UUID | None = None,
    mfa_verified: bool = False,
) -> SessionOut:
    """Issue refresh token (new row in the user's tenant) + access JWT."""
    s = get_settings()
    raw, hashed = new_token(user.organization_id)
    async with tenant_session(user.organization_id) as db:
        db.add(
            AuthToken(
                organization_id=user.organization_id,
                user_id=user.id,
                kind=TokenKind.REFRESH,
                token_hash=hashed,
                family_id=family or uuid.uuid4(),
                mfa_verified=mfa_verified,
                expires_at=_now() + timedelta(days=s.refresh_token_ttl_days),
            )
        )
    _set_refresh_cookie(response, raw)
    access, ttl = issue_access_token(Principal(user.id, user.organization_id, user.role))
    return SessionOut(access_token=access, expires_in=ttl, user=_user_out(user, org_name))


async def _issue_email_token(
    org_id: uuid.UUID, user_id: uuid.UUID, kind: TokenKind, ttl: timedelta
) -> str:
    raw, hashed = new_token(org_id)
    async with tenant_session(org_id) as db:
        db.add(
            AuthToken(
                organization_id=org_id,
                user_id=user_id,
                kind=kind,
                token_hash=hashed,
                expires_at=_now() + ttl,
            )
        )
    return raw


async def _consume(db, raw: str, kind: TokenKind) -> AuthToken | None:
    """Atomically mark a one-time token used. Returns it only if it was valid and unused."""
    row = (
        await db.execute(
            update(AuthToken)
            .where(
                AuthToken.token_hash == hash_token(raw),
                AuthToken.kind == kind,
                AuthToken.used_at.is_(None),
                AuthToken.revoked_at.is_(None),
                AuthToken.expires_at > _now(),
            )
            .values(used_at=_now())
            .returning(AuthToken)
        )
    ).scalar_one_or_none()
    return row


@router.post("/signup", status_code=status.HTTP_202_ACCEPTED)
async def signup(
    body: SignupIn, bg: BackgroundTasks, mailer: mailmod.Mailer = Depends(mailmod.get_mailer)
):
    email = body.email.lower()
    if problem := password_problem(body.password, email):
        raise _bad_password(problem)
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    trial = (await get_config().effective("billing.trial")).value
    async with app_engine().connect() as conn:
        plan_ok = (
            await conn.execute(
                text("SELECT 1 FROM plans WHERE id = :p AND is_active"), {"p": trial.plan_id}
            )
        ).first()
    # An admin pointing the trial at a missing plan must not break signup.
    trial_plan = trial.plan_id if plan_ok else "TRIAL"
    try:
        async with tenant_session(org_id) as db:
            db.add(Organization(id=org_id, name=body.organization_name.strip()))
            await db.flush()
            await billing.start_trial(
                db,
                org_id,
                plan_id=trial_plan,
                length_days=trial.length_days,
                grace_days=trial.grace_days,
            )
            db.add(
                User(
                    id=user_id,
                    organization_id=org_id,
                    email=email,
                    hashed_password=hash_password(body.password),
                    role=Role.COMPANY_ADMIN,
                )
            )
    except IntegrityError:
        # Same response as success: signup must not reveal which emails are registered.
        bg.add_task(mailer.send, await mailmod.already_registered_mail(email))
        return ACCEPTED
    raw = await _issue_email_token(org_id, user_id, TokenKind.EMAIL_VERIFY, VERIFY_TTL)
    bg.add_task(mailer.send, await mailmod.verify_email_mail(email, raw))
    return ACCEPTED


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(body: TokenIn):
    org_id = token_org(body.token)
    if org_id is None:
        raise INVALID_LINK
    async with tenant_session(org_id) as db:
        tok = await _consume(db, body.token, TokenKind.EMAIL_VERIFY)
        if tok is None:
            raise INVALID_LINK
        await db.execute(
            update(User).where(User.id == tok.user_id).values(email_verified_at=_now())
        )


async def finish_login(
    user: User, response: Response, *, password: str | None = None, mfa_verified: bool = False
) -> SessionOut:
    """The final step of signing in, after the password (and any second step) succeeded."""
    if user.role in PLATFORM_ROLES:
        # No tenant: the refresh token lives in platform_sessions and its cookie rotates like a tenant one.
        await _start_platform_session(user, response, mfa_verified=mfa_verified)
        access, ttl = issue_access_token(Principal(user.id, None, user.role, user.email))
        return SessionOut(
            access_token=access,
            expires_in=ttl,
            user=UserOut(
                id=str(user.id),
                email=user.email,
                role=user.role,
                organization_id="",
                organization_name="",
                mfa_enabled=user.mfa_enabled_at is not None,
            ),
        )
    async with tenant_session(user.organization_id) as db:
        if password is not None and needs_rehash(user.hashed_password):
            await db.execute(
                update(User)
                .where(User.id == user.id)
                .values(hashed_password=hash_password(password))
            )
        org_name = (await db.execute(select(Organization.name))).scalar_one()
    return await _start_session(user, org_name, response, mfa_verified=mfa_verified)


@router.post("/login", response_model=SessionOut | MfaChallenge)
async def login(body: LoginIn, response: Response):
    async with login_lookup_session(body.email) as db:
        user = (
            await db.execute(select(User).where(User.email == body.email.lower()))
        ).scalar_one_or_none()
    ok = verify_password(body.password, user.hashed_password if user else None)
    if not (ok and user and user.is_active):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect.")
    if user.role not in PLATFORM_ROLES:
        if not user.organization_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect.")
        if user.email_verified_at is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={
                    "detail": "Confirm your email address before logging in. Check your inbox.",
                    "code": "email_not_verified",
                },
            )
    from .mfa import challenge_for  # noqa: PLC0415  (mfa imports finish_login from this module)

    if (challenge := await challenge_for(user)) is not None:
        return challenge
    return await finish_login(user, response, password=body.password)


def _fail_clearing(
    cookie: str, detail: str = "Session expired. Log in again.", code: str | None = None
) -> JSONResponse:
    """A 401 that really deletes the cookie (headers set on an injected Response are dropped when an exception is raised)."""
    r = JSONResponse(
        {"detail": detail, **({"code": code} if code else {})},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )
    r.delete_cookie(cookie, path=REFRESH_COOKIE_PATH)
    return r


async def _mfa_policy_blocks(user: User, verified: bool) -> bool:
    """True when policy now requires two-step verification but this session never passed it."""
    if verified or user.role not in (*PLATFORM_ROLES, Role.COMPANY_ADMIN):
        return False
    from .mfa import policy_for  # noqa: PLC0415  (mfa imports finish_login from this module)

    mode, _ = await policy_for(user.role)
    return mfalib.requirement(mode, user.mfa_enabled_at is not None) != "none"


async def _platform_refresh(raw: str, response: Response) -> SessionOut | JSONResponse:
    unauthorised = HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Log in again.")
    h = hash_token(raw)
    bad = False
    async with platform_session(h) as db:
        tok = (
            await db.execute(select(PlatformSession).where(PlatformSession.token_hash == h))
        ).scalar_one_or_none()
        if tok is None:
            raise unauthorised
        if tok.used_at is not None or tok.revoked_at is not None:
            # A rotated token came back: assume theft and revoke the whole sign-in.
            await set_platform_family(db, tok.family_id)
            await db.execute(
                update(PlatformSession)
                .where(PlatformSession.family_id == tok.family_id)
                .values(revoked_at=_now())
            )
            bad = True
        elif tok.expires_at <= _now() or tok.family_started_at + PLATFORM_MAX_AGE <= _now():
            raise unauthorised
        else:
            claimed = (
                await db.execute(
                    update(PlatformSession)
                    .where(PlatformSession.id == tok.id, PlatformSession.used_at.is_(None))
                    .values(used_at=_now())
                    .returning(PlatformSession.id)
                )
            ).scalar_one_or_none()
            bad = claimed is None
    if bad:
        return _fail_clearing(PLATFORM_COOKIE)
    async with login_lookup_session(tok.email) as db:
        user = (await db.execute(select(User).where(User.id == tok.user_id))).scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or user.role not in PLATFORM_ROLES
        or await _mfa_policy_blocks(user, tok.mfa_verified)
    ):
        async with platform_session(h) as db:  # end this sign-in
            await set_platform_family(db, tok.family_id)
            await db.execute(
                update(PlatformSession)
                .where(PlatformSession.family_id == tok.family_id)
                .values(revoked_at=_now())
            )
        if user is not None and user.is_active and user.role in PLATFORM_ROLES:
            return _fail_clearing(
                PLATFORM_COOKIE,
                "Two-step verification is now required. Sign in again.",
                "mfa_required",
            )
        return _fail_clearing(PLATFORM_COOKIE)
    await _start_platform_session(
        user,
        response,
        family=tok.family_id,
        started=tok.family_started_at,
        mfa_verified=tok.mfa_verified,
    )
    access, ttl = issue_access_token(Principal(user.id, None, user.role, user.email))
    return SessionOut(
        access_token=access,
        expires_in=ttl,
        user=UserOut(
            id=str(user.id),
            email=user.email,
            role=user.role,
            organization_id="",
            organization_name="",
            mfa_enabled=user.mfa_enabled_at is not None,
        ),
    )


@router.post("/refresh", response_model=SessionOut)
async def refresh(
    response: Response,
    a11y_refresh: str | None = Cookie(default=None),
    a11y_platform: str | None = Cookie(default=None),
):
    unauthorised = HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Log in again.")
    if a11y_refresh is None and a11y_platform:
        return await _platform_refresh(a11y_platform, response)
    org_id = token_org(a11y_refresh)
    if org_id is None:
        raise unauthorised
    reuse = False
    async with tenant_session(org_id) as db:
        tok = (
            await db.execute(
                select(AuthToken).where(
                    AuthToken.token_hash == hash_token(a11y_refresh),
                    AuthToken.kind == TokenKind.REFRESH,
                )
            )
        ).scalar_one_or_none()
        if tok is None:
            raise unauthorised
        if tok.used_at is not None or tok.revoked_at is not None:
            # A rotated token came back: assume theft and kill the whole family.
            await db.execute(
                update(AuthToken)
                .where(AuthToken.family_id == tok.family_id)
                .values(revoked_at=_now())
            )
            reuse = True
        elif tok.expires_at <= _now():
            raise unauthorised
        else:
            # Conditional update so two concurrent refreshes can't both rotate the same token.
            claimed = (
                await db.execute(
                    update(AuthToken)
                    .where(AuthToken.id == tok.id, AuthToken.used_at.is_(None))
                    .values(used_at=_now())
                    .returning(AuthToken.id)
                )
            ).scalar_one_or_none()
            if claimed is None:
                reuse = True
            else:
                user = (
                    await db.execute(select(User).where(User.id == tok.user_id))
                ).scalar_one_or_none()
                org_name = (await db.execute(select(Organization.name))).scalar_one()
    if reuse or user is None or not user.is_active:
        return _fail_clearing(REFRESH_COOKIE)
    if await _mfa_policy_blocks(user, tok.mfa_verified):
        async with tenant_session(org_id) as db:
            await db.execute(
                update(AuthToken)
                .where(AuthToken.family_id == tok.family_id)
                .values(revoked_at=_now())
            )
        return _fail_clearing(
            REFRESH_COOKIE, "Two-step verification is now required. Sign in again.", "mfa_required"
        )
    return await _start_session(
        user, org_name, response, family=tok.family_id, mfa_verified=tok.mfa_verified
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    a11y_refresh: str | None = Cookie(default=None),
    a11y_platform: str | None = Cookie(default=None),
):
    org_id = token_org(a11y_refresh)
    if org_id:
        async with tenant_session(org_id) as db:
            fam = (
                await db.execute(
                    select(AuthToken.family_id).where(
                        AuthToken.token_hash == hash_token(a11y_refresh)
                    )
                )
            ).scalar_one_or_none()
            if fam:
                await db.execute(
                    update(AuthToken).where(AuthToken.family_id == fam).values(revoked_at=_now())
                )
    if a11y_platform:
        h = hash_token(a11y_platform)
        async with platform_session(h) as db:
            fam = (
                await db.execute(
                    select(PlatformSession.family_id).where(PlatformSession.token_hash == h)
                )
            ).scalar_one_or_none()
            if fam:
                await set_platform_family(db, fam)
                await db.execute(
                    update(PlatformSession)
                    .where(PlatformSession.family_id == fam)
                    .values(revoked_at=_now())
                )
    _clear_refresh_cookie(response)
    _clear_platform_cookie(response)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    body: EmailIn, bg: BackgroundTasks, mailer: mailmod.Mailer = Depends(mailmod.get_mailer)
):
    async with login_lookup_session(body.email) as db:
        user = (
            await db.execute(select(User).where(User.email == body.email.lower()))
        ).scalar_one_or_none()
    if user and user.is_active and user.organization_id:
        raw = await _issue_email_token(
            user.organization_id, user.id, TokenKind.PASSWORD_RESET, RESET_TTL
        )
        bg.add_task(mailer.send, await mailmod.reset_password_mail(user.email, raw))
    return ACCEPTED


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(body: ResetConfirmIn):
    org_id = token_org(body.token)
    if org_id is None:
        raise INVALID_LINK
    async with tenant_session(org_id) as db:
        # Check password strength before burning the one-time token.
        peek = (
            await db.execute(
                select(AuthToken).where(
                    AuthToken.token_hash == hash_token(body.token),
                    AuthToken.kind == TokenKind.PASSWORD_RESET,
                )
            )
        ).scalar_one_or_none()
        if peek is None or peek.used_at or peek.revoked_at or peek.expires_at <= _now():
            raise INVALID_LINK
        email = (await db.execute(select(User.email).where(User.id == peek.user_id))).scalar_one()
        if problem := password_problem(body.password, email):
            raise _bad_password(problem)
        tok = await _consume(db, body.token, TokenKind.PASSWORD_RESET)
        if tok is None:
            raise INVALID_LINK
        await db.execute(
            update(User)
            .where(User.id == tok.user_id)
            .values(hashed_password=hash_password(body.password), email_verified_at=_now())
        )
        # Password change signs out every device.
        await db.execute(
            update(AuthToken)
            .where(
                AuthToken.user_id == tok.user_id,
                AuthToken.kind == TokenKind.REFRESH,
                AuthToken.revoked_at.is_(None),
            )
            .values(revoked_at=_now())
        )
