"""Cross-tenant isolation suite (PROJECT_PLAN 3.4). This is a merge gate: if you add a
tenant table and forget RLS, `test_every_tenant_table_has_forced_rls` fails the build."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from a11y_core.db import admin_session, app_engine, tenant_session
from a11y_core.models import AuditLog, AuthToken, TokenKind, User
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .conftest import TEST_PREFIX, make_org

TENANT_TABLES = [
    "organizations",
    "users",
    "auth_tokens",
    "audit_log",
    "subscriptions",
    "usage_ledger",
    "usage_reservations",
    "coupon_redemptions",
    "ai_usage",
    "scan_jobs",
    "scan_pages",
    "scan_findings",
    "verified_domains",
    "reports",
    "vpat_reports",
    "fix_suggestions",
    "page_screenshots",
    "notification_log",
    "api_keys",
    "webhook_endpoints",
    "webhook_deliveries",
]
# Tables that carry organization_id but intentionally also hold platform-wide rows (see policy).
PLATFORM_AND_TENANT_TABLES = ["setting_versions"]


async def _owner_conn():
    from a11y_core.settings import get_settings

    s = get_settings()
    return await asyncpg.connect(
        host=s.postgres_host,
        port=s.postgres_port,
        user="a11y_owner",
        password=s.a11y_owner_password,
        database=s.postgres_db,
    )


async def test_every_tenant_table_has_forced_rls():
    conn = await _owner_conn()
    try:
        with_org_col = {
            r["table_name"]
            for r in await conn.fetch(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema='public' AND column_name='organization_id'"
            )
        }
        tenant_tables = with_org_col | {"organizations"}
        assert set(TENANT_TABLES) | set(PLATFORM_AND_TENANT_TABLES) <= tenant_tables
        for t in tenant_tables:
            row = await conn.fetchrow(
                "SELECT relrowsecurity, relforcerowsecurity, "
                "(SELECT count(*) FROM pg_policy WHERE polrelid = c.oid) AS policies "
                "FROM pg_class c WHERE c.oid = $1::regclass",
                t,
            )
            assert row["relrowsecurity"], f"{t}: RLS not enabled"
            assert row["relforcerowsecurity"], f"{t}: RLS not forced"
            assert row["policies"] >= 1, f"{t}: no policy"
    finally:
        await conn.close()


async def test_app_role_cannot_bypass_rls_or_own_tables():
    async with app_engine().connect() as c:
        role = (
            await c.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
        assert (role.rolsuper, role.rolbypassrls) == (False, False)
        owned = (
            await c.execute(
                text(
                    "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner = current_user"
                )
            )
        ).scalar_one()
        assert owned == 0


@pytest.mark.parametrize("table", TENANT_TABLES)
async def test_no_tenant_context_returns_zero_rows(table):
    await make_org()
    async with app_engine().connect() as c:
        assert (await c.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0


async def test_org_a_cannot_see_org_b():
    a, a_user, _ = await make_org()
    b, b_user, _ = await make_org()
    async with tenant_session(b) as db:
        db.add(
            AuthToken(
                organization_id=b,
                user_id=b_user,
                kind=TokenKind.REFRESH,
                token_hash=uuid.uuid4().hex * 2,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        db.add(AuditLog(organization_id=b, action="x"))
    async with tenant_session(a) as db:
        assert [o.id for o in (await db.execute(text("SELECT id FROM organizations"))).all()] == [a]
        assert {u.id for u in (await db.execute(text("SELECT id FROM users"))).all()} == {a_user}
        assert (await db.execute(text("SELECT count(*) FROM auth_tokens"))).scalar_one() == 0
        assert (await db.execute(text("SELECT count(*) FROM audit_log"))).scalar_one() == 0
        # Even by explicit primary key:
        assert (
            await db.execute(text("SELECT count(*) FROM users WHERE id = :i"), {"i": b_user})
        ).scalar_one() == 0


async def test_org_a_cannot_write_into_org_b():
    a, *_ = await make_org()
    b, b_user, _ = await make_org()
    with pytest.raises(DBAPIError):  # WITH CHECK violation
        async with tenant_session(a) as db:
            db.add(
                User(
                    organization_id=b,
                    email=f"x{uuid.uuid4().hex[:8]}@example.com",
                    hashed_password="x",
                    role="STANDARD_USER",
                )
            )
            await db.flush()
    async with tenant_session(a) as db:
        upd = await db.execute(
            text("UPDATE users SET is_active = false WHERE id = :i"), {"i": b_user}
        )
        dele = await db.execute(text("DELETE FROM users WHERE id = :i"), {"i": b_user})
        assert (upd.rowcount, dele.rowcount) == (0, 0)
        org_upd = await db.execute(
            text("UPDATE organizations SET name = 'pwned' WHERE id = :i"), {"i": b}
        )
        assert org_upd.rowcount == 0
    async with tenant_session(b) as db:
        assert (
            await db.execute(text("SELECT is_active FROM users WHERE id=:i"), {"i": b_user})
        ).scalar_one() is True


async def test_tenant_setting_does_not_leak_across_pooled_connections():
    a, *_ = await make_org()
    async with tenant_session(a) as db:
        await db.execute(text("SELECT 1"))
    # Same pool, new transaction, no tenant: must see nothing (SET LOCAL was transaction-scoped).
    async with app_engine().connect() as c:
        assert (await c.execute(text("SELECT current_setting('app.org_id', true)"))).scalar() in (
            None,
            "",
        )
        assert (await c.execute(text("SELECT count(*) FROM organizations"))).scalar_one() == 0


async def test_login_lookup_sees_only_the_matching_email():
    from a11y_core.db import login_lookup_session

    _, _, email = await make_org()
    await make_org()
    async with login_lookup_session(email) as db:
        rows = (await db.execute(text("SELECT email FROM users"))).all()
        assert [r.email for r in rows] == [email]
        assert (await db.execute(text("SELECT count(*) FROM organizations"))).scalar_one() == 0


async def test_audit_log_is_append_only_for_app_role():
    a, *_ = await make_org()
    async with tenant_session(a) as db:
        db.add(AuditLog(organization_id=a, action="test"))
    for stmt in ("UPDATE audit_log SET action='y'", "DELETE FROM audit_log"):
        with pytest.raises(DBAPIError):
            async with tenant_session(a) as db:
                await db.execute(text(stmt))


async def test_admin_session_is_audited_and_sees_all_tenants():
    a, a_user, _ = await make_org()
    b, *_ = await make_org()
    with pytest.raises(ValueError):
        async with admin_session(actor_user_id=a_user, reason=" "):
            pass
    async with admin_session(actor_user_id=a_user, reason=f"{TEST_PREFIX}isolation check") as db:
        ids = {r.id for r in (await db.execute(text("SELECT id FROM organizations"))).all()}
        assert {a, b} <= ids
    conn = await asyncpg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        user="postgres",
        password=os.environ["POSTGRES_SUPERUSER_PASSWORD"],
        database=os.environ.get("POSTGRES_DB", "a11y"),
    )
    try:
        n = await conn.fetchval(
            "SELECT count(*) FROM audit_log WHERE actor_user_id=$1 AND action='admin.cross_tenant_access'",
            a_user,
        )
        assert n == 1
    finally:
        await conn.close()
