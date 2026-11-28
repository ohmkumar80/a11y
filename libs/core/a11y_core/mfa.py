"""Two-step verification: TOTP (RFC 6238) and one-time recovery codes. Standard library only.

* TOTP: HMAC-SHA1, 6 digits, 30 s step, one step of clock drift either way. A code can be used once: the
  accepted step is stored and only a LATER step is accepted next time (replay protection).
* Recovery codes: 10 random codes, shown once, stored as SHA-256 hashes (they are high-entropy random, so a fast
  hash is appropriate), each usable once.
* Enrolment is text-first: the secret is shown as a key to type into an authenticator app (plus an otpauth link).
  A QR code alone would exclude blind and low-vision users, so it is never the only way.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Literal
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
RECOVERY_COUNT = 10
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alikes (i, l, o, 0, 1)

Mode = Literal["required", "optional", "off"]
Requirement = Literal["none", "verify", "enroll"]


def new_secret() -> str:
    """160-bit secret, base32 without padding (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()  # noqa: S324 - RFC 6238 default
    off = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[off : off + 4])[0] & 0x7FFFFFFF) % 10**DIGITS
    return f"{value:0{DIGITS}d}"


def normalise_code(code: str) -> str:
    return "".join(ch for ch in code if ch.isdigit())


def verify_totp(
    secret_b32: str, code: str, *, last_step: int = 0, now: float | None = None
) -> int | None:
    """The accepted time step, or None. Only a step greater than ``last_step`` is accepted (no replay)."""
    c = normalise_code(code)
    if len(c) != DIGITS:
        return None
    step_now = int((time.time() if now is None else now) // STEP_SECONDS)
    matched: int | None = None
    for step in range(
        step_now - DRIFT_STEPS, step_now + DRIFT_STEPS + 1
    ):  # check all: constant work
        if hmac.compare_digest(_hotp(secret_b32, step), c) and step > last_step:
            matched = step if matched is None else max(matched, step)
    return matched


def format_key(secret_b32: str) -> str:
    """Groups of four, easier to read aloud and type: ABCD EFGH ..."""
    return " ".join(secret_b32[i : i + 4] for i in range(0, len(secret_b32), 4))


def otpauth_uri(secret_b32: str, account: str, issuer: str) -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret_b32}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP_SECONDS}"


# --- recovery codes ----------------------------------------------------------------------------------------


def new_recovery_codes(n: int = RECOVERY_COUNT) -> list[str]:
    return [
        "".join(secrets.choice(_ALPHABET) for _ in range(5))
        + "-"
        + "".join(secrets.choice(_ALPHABET) for _ in range(5))
        for _ in range(n)
    ]


def _norm_recovery(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch in _ALPHABET)


def hash_recovery(code: str) -> str:
    return hashlib.sha256(_norm_recovery(code).encode()).hexdigest()


def consume_recovery(hashes: list[str], code: str) -> list[str] | None:
    """The remaining hashes if ``code`` matched one (which is then spent), else None."""
    h = hash_recovery(code)
    if len(_norm_recovery(code)) != 10:
        return None
    hit = None
    for x in hashes:  # compare against all, constant time each
        if hmac.compare_digest(x, h):
            hit = x
    if hit is None:
        return None
    rest = list(hashes)
    rest.remove(hit)
    return rest


# --- policy ------------------------------------------------------------------------------------------------


def requirement(mode: Mode, enrolled: bool) -> Requirement:
    """What a sign-in must do. 'off' asks nobody (development); 'optional' asks only people who enrolled;
    'required' asks everyone, and sends people who have not enrolled to enrol first."""
    if mode == "off":
        return "none"
    if enrolled:
        return "verify"
    return "enroll" if mode == "required" else "none"
