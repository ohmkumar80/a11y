"""Authentication for the public API: ``Authorization: Bearer a11y_...`` keys (PROJECT_PLAN 3.17).

A key is checked on every request: its shape, its hash, that it is neither revoked nor expired, that the person who
created it is still an active member, that the organisation's plan still includes API access, that it has the scope the
endpoint needs, and that it is under its rate limit. Every failure of the first group gives the SAME answer, so nobody
can learn which part of a guess was right."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import timedelta

from a11y_core import api_keys, billing
from a11y_core.config import get_config
from a11y_core.db import tenant_session
from a11y_core.settings import get_settings
from fastapi import HTTPException, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy import text

from .security import Principal

log = logging.getLogger(__name__)
INVALID = "The API key is not valid. Check that you copied it completely, and that it has not been revoked or expired."
TOUCH_AFTER = timedelta(
    minutes=5
)  # last_used_at is a hint for people, not a ledger: do not write on every request


def _problem(http_status: int, detail: str, code: str, **extra) -> HTTPException:
    headers = extra.pop("headers", None)
    return HTTPException(
        http_status, detail={"detail": detail, "code": code, **extra}, headers=headers
    )


def _invalid() -> HTTPException:
    return _problem(
        status.HTTP_401_UNAUTHORIZED,
        INVALID,
        "invalid_api_key",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _within_rate(key_id: uuid.UUID, per_minute: int, response: Response) -> None:
    window = int(time.time() // 60)
    r = Redis.from_url(get_settings().redis_url)
    try:
        n = await r.incr(f"rl:api:{key_id}:{window}")
        if n == 1:
            await r.expire(f"rl:api:{key_id}:{window}", 90)
    except Exception:  # noqa: BLE001 - if Redis is down we do not lock customers out of their data
        log.warning("api rate limit unavailable")
        return
    finally:
        await r.aclose()
    response.headers["X-RateLimit-Limit"] = str(per_minute)
    response.headers["X-RateLimit-Remaining"] = str(max(0, per_minute - n))
    if n > per_minute:
        raise _problem(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"You have made more than {per_minute} requests this minute. Wait and try again.",
            "rate_limited",
            headers={
                "Retry-After": str(60 - int(time.time()) % 60),
                "X-RateLimit-Limit": str(per_minute),
                "X-RateLimit-Remaining": "0",
            },
        )


class ApiCaller:
    """Who is calling: the organisation, the key and what it may do."""

    def __init__(
        self, principal: Principal, key_id: uuid.UUID, scopes: list[str], name: str
    ) -> None:
        self.principal, self.key_id, self.scopes, self.name = principal, key_id, scopes, name


async def authenticate(request: Request, response: Response) -> ApiCaller:
    header = request.headers.get("authorization", "")
    scheme, _, key = header.partition(" ")
    org = api_keys.parse_org(key.strip()) if scheme.lower() == "bearer" else None
    if org is None:
        raise _invalid()
    async with tenant_session(org) as db:
        row = (
            await db.execute(
                text(
                    "SELECT k.id, k.name, k.key_hash, k.scopes, k.created_by, k.expires_at, k.revoked_at, "
                    "u.is_active, u.role, u.email, s.plan_id, (k.last_used_at IS NULL OR k.last_used_at < now() - CAST(:t AS interval)) AS stale "
                    "FROM api_keys k JOIN users u ON u.id = k.created_by LEFT JOIN subscriptions s ON s.organization_id = k.organization_id "
                    "WHERE k.key_hash = :h"
                ),
                {"h": api_keys.hash_key(key.strip()), "t": TOUCH_AFTER},
            )
        ).first()
        if (
            row is None
            or not api_keys.matches(key.strip(), row.key_hash)
            or row.revoked_at
            or not row.is_active
        ):
            raise _invalid()
        if (
            row.expires_at is not None
            and row.expires_at <= (await db.execute(text("SELECT now()"))).scalar_one()
        ):
            raise _invalid()
        ent = (
            await billing.entitlement(db, row.plan_id, api_keys.ENTITLEMENT)
            if row.plan_id
            else None
        )
        if ent is None or not ent.enabled:
            raise _problem(
                status.HTTP_403_FORBIDDEN,
                "Your plan does not include API access.",
                "api_not_in_plan",
                upgrade_url="/org#plan",
            )
        if row.stale:
            await db.execute(
                text("UPDATE api_keys SET last_used_at = now() WHERE id = :i"), {"i": row.id}
            )
    limits = (await get_config().effective("api.limits", org_id=org, plan_id=row.plan_id)).value
    await _within_rate(row.id, limits.requests_per_minute, response)
    # Member-level, never an administrator: an API key cannot reach admin-only behaviour, whatever its creator is.
    return ApiCaller(
        Principal(row.created_by, org, "STANDARD_USER", row.email),
        row.id,
        list(row.scopes),
        row.name,
    )


def require_scope(scope: str):
    """FastAPI dependency: authenticate, then insist on one scope. Returns the member-level principal."""

    async def dep(request: Request, response: Response) -> Principal:
        caller = await authenticate(request, response)
        if scope not in caller.scopes:
            raise _problem(
                status.HTTP_403_FORBIDDEN,
                f"This API key does not have the {scope} scope.",
                "scope_missing",
                required_scope=scope,
            )
        request.state.api_caller = caller
        return caller.principal

    dep.__name__ = f"require_{scope.replace(':', '_')}"
    return dep


async def any_valid_key(request: Request, response: Response) -> ApiCaller:
    caller = await authenticate(request, response)
    request.state.api_caller = caller
    return caller
