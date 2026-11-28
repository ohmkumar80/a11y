"""API keys for the public API (/v1). PROJECT_PLAN 3.17.

A key looks like ``a11y_<organisation id, 32 hex>_<43 random characters>``. The organisation is in the key (not secret)
so we can open the right tenant session and look the key up under normal row-level security; the random part is the
secret and only a SHA-256 of the whole key is stored, so a database leak does not leak working keys. The ``a11y_``
prefix lets secret scanners (GitHub, trufflehog) recognise a leaked key."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

PREFIX = "a11y"
# Scope -> what it allows. A key gets only the scopes it was created with.
SCOPES: dict[str, str] = {
    "scans:read": "List scans and read their results and findings",
    "scans:write": "Start scans (uses scan credits)",
    "reports:read": "List and download reports",
    "reports:write": "Create reports",
    "audit:read": "Read your organisation's audit log",
}
ENTITLEMENT = "api_access"


def generate(org_id: uuid.UUID) -> tuple[str, str, str]:
    """(full key, sha256 hex, last four characters). The full key is shown to the person once and never stored."""
    key = f"{PREFIX}_{org_id.hex}_{secrets.token_urlsafe(32)}"
    return key, hash_key(key), key[-4:]


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def parse_org(key: str) -> uuid.UUID | None:
    """The organisation a key claims to belong to, or None if it is not shaped like one of ours."""
    parts = key.split("_", 2)
    if len(parts) != 3 or parts[0] != PREFIX or len(parts[1]) != 32 or len(parts[2]) < 32:
        return None
    try:
        return uuid.UUID(hex=parts[1])
    except ValueError:
        return None


def matches(key: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_key(key), stored_hash)
