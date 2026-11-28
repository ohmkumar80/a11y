"""Database access with Postgres Row-Level Security.

Rules (PROJECT_PLAN 3.4):
* The app connects as ``a11y_app`` - not the table owner, no BYPASSRLS.
* Each request/job runs in ONE transaction that starts with ``set_config(..., true)``
  (== SET LOCAL), so the tenant id can never leak across pooled connections, including
  PgBouncer in transaction mode.
* No tenant id set => policies evaluate to NULL => zero rows. It fails closed.
* Cross-tenant access goes through ``admin_session`` and is always audit-logged.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import AuditLog
from .settings import get_settings

_engines: dict[str, AsyncEngine] = {}


def _engine(kind: str) -> AsyncEngine:
    if kind not in _engines:
        s = get_settings()
        url = {
            "app": s.app_database_url,
            "owner": s.owner_database_url,
            "admin": s.admin_database_url,
        }[kind]
        _engines[kind] = create_async_engine(url, pool_pre_ping=True)
    return _engines[kind]


def app_engine() -> AsyncEngine:
    return _engine("app")


def admin_engine() -> AsyncEngine:
    return _engine("admin")


def owner_engine() -> AsyncEngine:
    return _engine("owner")


async def dispose_engines() -> None:
    for e in _engines.values():
        await e.dispose()
    _engines.clear()


async def _set(session: AsyncSession, key: str, value: str) -> None:
    # is_local=true -> transaction-scoped. Bound parameter, never string-formatted.
    await session.execute(text("SELECT set_config(:k, :v, true)"), {"k": key, "v": value})


@asynccontextmanager
async def tenant_session(org_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Transaction scoped to one organisation. Commits on success, rolls back on error."""
    if not isinstance(org_id, uuid.UUID):
        raise TypeError("org_id must be a uuid.UUID")
    maker = async_sessionmaker(app_engine(), expire_on_commit=False)
    async with maker() as session, session.begin():
        await _set(session, "app.org_id", str(org_id))
        yield session


@asynccontextmanager
async def login_lookup_session(email: str) -> AsyncIterator[AsyncSession]:
    """Pre-authentication session that can see exactly one ``users`` row: the one whose
    email matches. Used by login and password reset, where the tenant is not yet known."""
    maker = async_sessionmaker(app_engine(), expire_on_commit=False)
    async with maker() as session, session.begin():
        await _set(session, "app.auth_email", email.strip().lower())
        yield session


@asynccontextmanager
async def reviewer_session(reviewer_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """A session for a platform reviewer (ADR 0023). It sees only the review requests nobody has claimed yet and the ones
    this reviewer holds, and nothing else: it has no organisation, so every other table returns no rows. To read a document
    the caller must first prove the review is theirs, then open an ordinary `tenant_session` for that one organisation."""
    maker = async_sessionmaker(app_engine(), expire_on_commit=False)
    async with maker() as session, session.begin():
        await _set(session, "app.reviewer_id", str(reviewer_id))
        yield session


@asynccontextmanager
async def platform_session(token_hash: str) -> AsyncIterator[AsyncSession]:
    """Pre-authentication session for Super Admin refresh tokens: sees only the row whose hash matches (and, once the
    caller sets it with ``set_platform_family``, that token's family so a replay can revoke all of it)."""
    maker = async_sessionmaker(app_engine(), expire_on_commit=False)
    async with maker() as session, session.begin():
        await _set(session, "app.platform_token", token_hash)
        yield session


async def set_platform_token(session: AsyncSession, token_hash: str) -> None:
    await _set(session, "app.platform_token", token_hash)


async def set_platform_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await _set(session, "app.platform_family", str(family_id))


@asynccontextmanager
async def admin_session(
    *, actor_user_id: uuid.UUID | None, reason: str, action: str = "admin.cross_tenant_access"
) -> AsyncIterator[AsyncSession]:
    """Cross-tenant (BYPASSRLS) session for Super Admin. The audit row is written first, in
    the same transaction, so a read cannot happen without a record."""
    if not reason.strip():
        raise ValueError("a reason is required for cross-tenant access")
    maker = async_sessionmaker(_engine("admin"), expire_on_commit=False)
    async with maker() as session, session.begin():
        session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                detail={"reason": reason},
            )
        )
        await session.flush()
        yield session
