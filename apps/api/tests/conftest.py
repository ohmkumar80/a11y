import os
import uuid
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from dotenv import load_dotenv  # noqa: F401  (pydantic-settings dependency)
from httpx import ASGITransport, AsyncClient

# Tests run against the docker-compose Postgres (make: `docker compose up -d postgres`).
for line in (Path(__file__).parents[3] / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k, v)

from a11y_core.db import dispose_engines, tenant_session  # noqa: E402
from a11y_core.models import Organization, Role, Subscription, User  # noqa: E402

from a11y_api import mail  # noqa: E402
from a11y_api.main import app  # noqa: E402
from a11y_api.security import hash_password  # noqa: E402

TEST_PREFIX = "test-"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _cleanup():
    yield
    await dispose_engines()
    # Superuser bypasses RLS; cascades remove users/tokens.
    conn = await asyncpg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        user="postgres",
        password=os.environ["POSTGRES_SUPERUSER_PASSWORD"],
        database=os.environ.get("POSTGRES_DB", "a11y"),
    )
    await conn.execute(f"DELETE FROM audit_log WHERE detail->>'reason' LIKE '{TEST_PREFIX}%'")
    await conn.execute(f"DELETE FROM organizations WHERE name LIKE '{TEST_PREFIX}%'")
    await conn.close()


@pytest.fixture
def outbox():
    box = mail.OutboxMailer()
    app.dependency_overrides[mail.get_mailer] = lambda: box
    yield box
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(outbox):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def sql(query: str, *args):
    """Run SQL as the superuser (bypasses RLS and grants) - for arranging/inspecting test state."""
    conn = await asyncpg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        user="postgres",
        password=os.environ["POSTGRES_SUPERUSER_PASSWORD"],
        database=os.environ.get("POSTGRES_DB", "a11y"),
    )
    try:
        return await conn.fetch(query, *args)
    finally:
        await conn.close()


async def make_org(
    name: str | None = None,
    *,
    email: str | None = None,
    role: str = Role.COMPANY_ADMIN,
    plan: str = "GROWTH",
    trial_days: int | None = None,
):
    """Create an org + verified user + subscription directly. Returns (org_id, user_id, email).
    ``trial_days=None`` => ACTIVE on ``plan``; otherwise a trial of that many days (may be negative)."""
    org_id, user_id = uuid.uuid4(), uuid.uuid4()
    email = email or f"u-{user_id.hex[:10]}@example.com"
    async with tenant_session(org_id) as db:
        db.add(Organization(id=org_id, name=name or f"{TEST_PREFIX}{org_id.hex[:8]}"))
        await db.flush()
        from datetime import UTC, datetime, timedelta

        from a11y_core import billing

        if trial_days is None:
            db.add(Subscription(organization_id=org_id, plan_id=plan, status="ACTIVE"))
        else:
            await billing.start_trial(
                db,
                org_id,
                plan_id=plan,
                length_days=0,
                grace_days=0,
                now=datetime.now(UTC) + timedelta(days=trial_days),
            )

        db.add(
            User(
                id=user_id,
                organization_id=org_id,
                email=email,
                hashed_password=hash_password("correct horse battery"),
                role=role,
                email_verified_at=datetime.now(UTC),
            )
        )
    return org_id, user_id, email


def super_admin_headers() -> dict[str, str]:
    """Bearer header for a Super Admin (no tenant). Minted directly: the admin sign-in flow with
    MFA ships with the /admin UI."""
    from a11y_api.security import Principal, issue_access_token

    token, _ = issue_access_token(Principal(uuid.uuid4(), None, Role.SUPER_ADMIN))
    return {"authorization": f"Bearer {token}"}
