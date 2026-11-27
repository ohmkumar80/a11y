"""Password hashing, opaque one-time tokens and short-lived JWT access tokens."""

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from a11y_core.settings import get_settings
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()
# Verified against when the account does not exist, so response time doesn't reveal it.
_DUMMY_HASH = _hasher.hash("not-a-real-password-just-for-timing")

# WCAG 3.3.8: no composition rules or cognitive tests. Length + a small denylist only.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
_COMMON = {
    "password1234",
    "123456789012",
    "qwertyuiop12",
    "iloveyou1234",
    "administrator",
    "passwordpassword",
    "letmeinletmein",
    "welcome12345",
}


def password_problem(password: str, email: str = "") -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters. A passphrase works well."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Use at most {MAX_PASSWORD_LENGTH} characters."
    if password.lower() in _COMMON or (email and password.lower() == email.lower()):
        return "That password is too easy to guess. Choose a different one."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    try:
        return _hasher.verify(hashed or _DUMMY_HASH, password) and hashed is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


# --- opaque tokens: "<org uuid hex>.<secret>" -----------------------------------------------
# The org prefix lets us open the right tenant session before we can look the token up
# (RLS hides auth_tokens from sessions without a tenant). It is not secret; the part after
# the dot is. Only the SHA-256 of the whole string is stored.


def new_token(org_id: uuid.UUID) -> tuple[str, str]:
    raw = f"{org_id.hex}.{secrets.token_urlsafe(32)}"
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


_TOKEN_RE = re.compile(r"^([0-9a-f]{32})\.[A-Za-z0-9_-]{20,100}$")


def token_org(raw: str | None) -> uuid.UUID | None:
    m = _TOKEN_RE.match(raw or "")
    return uuid.UUID(m.group(1)) if m else None


# --- JWT access tokens ------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """``org_id`` is None only for SUPER_ADMIN, who has no tenant. Tenant routes reject such a
    principal (see deps.current_principal) so a missing tenant can never reach a query."""

    user_id: uuid.UUID
    org_id: uuid.UUID | None
    role: str
    email: str | None = (
        None  # lets a Super Admin (no tenant) find their own row for account-security actions
    )


def issue_access_token(p: Principal) -> tuple[str, int]:
    s = get_settings()
    ttl = timedelta(minutes=s.access_token_ttl_minutes)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(p.user_id),
            "org": str(p.org_id) if p.org_id else "",
            "role": p.role,
            "eml": p.email or "",
            "iat": now,
            "exp": now + ttl,
        },
        s.jwt_secret,
        algorithm="HS256",
    )
    return token, int(ttl.total_seconds())


def decode_access_token(token: str) -> Principal | None:
    try:
        c = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "org", "role"]},
        )
        org = uuid.UUID(c["org"]) if c["org"] else None
        if (c["role"] == "SUPER_ADMIN") != (org is None):
            return None
        return Principal(uuid.UUID(c["sub"]), org, c["role"], c.get("eml") or None)
    except (jwt.PyJWTError, ValueError):
        return None


# --- short-lived tokens for the two-step verification sign-in steps -------------------------------------------
# Audience "mfa": decode_access_token() refuses these (PyJWT rejects an unexpected audience), so a half-finished
# sign-in can never be used as a session. 10 minutes, announced on screen (WCAG 2.2.1).

MFA_TOKEN_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class MfaChallengeToken:
    user_id: uuid.UUID
    org_id: uuid.UUID | None
    role: str
    email: str
    purpose: str  # "verify" | "enroll"


def issue_mfa_token(
    user_id: uuid.UUID, org_id: uuid.UUID | None, role: str, email: str, purpose: str
) -> tuple[str, int]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "aud": "mfa",
            "sub": str(user_id),
            "org": str(org_id) if org_id else "",
            "role": role,
            "eml": email,
            "pur": purpose,
            "iat": now,
            "exp": now + MFA_TOKEN_TTL,
        },
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    return token, int(MFA_TOKEN_TTL.total_seconds())


def decode_mfa_token(token: str, purpose: str | None = None) -> MfaChallengeToken | None:
    try:
        c = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            audience="mfa",
            options={"require": ["exp", "sub", "pur", "eml"]},
        )
        if purpose and c["pur"] != purpose:
            return None
        return MfaChallengeToken(
            uuid.UUID(c["sub"]),
            uuid.UUID(c["org"]) if c["org"] else None,
            c["role"],
            c["eml"],
            c["pur"],
        )
    except (jwt.PyJWTError, ValueError):
        return None
