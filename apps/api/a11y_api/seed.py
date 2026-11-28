"""Idempotent development seed data: one demo organisation with an admin and a member.
Never runs when ENV=production."""

import asyncio
import os
import uuid
from datetime import UTC, datetime

from a11y_core.db import admin_session, dispose_engines, login_lookup_session, tenant_session
from a11y_core.models import Organization, Role, User
from sqlalchemy import select, text

from .security import hash_password

DEMO_ORG_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEMO_PASSWORD = os.environ.get("SEED_DEMO_PASSWORD", "demo-passphrase-123")
USERS = [
    ("admin@demo.example.com", Role.COMPANY_ADMIN),
    ("member@demo.example.com", Role.STANDARD_USER),
]


async def main() -> None:
    if os.environ.get("ENV") == "production":
        raise SystemExit("refusing to seed demo data in production")
    async with tenant_session(DEMO_ORG_ID) as db:
        if (await db.execute(select(Organization.id))).first() is None:
            db.add(Organization(id=DEMO_ORG_ID, name="Demo Organisation"))
            await db.flush()
    # Plan changes are admin-only, so the demo org's plan is set through the audited admin role.
    async with admin_session(actor_user_id=None, reason="dev seed", action="system.seed") as db:
        await db.execute(
            text(
                "INSERT INTO subscriptions (organization_id, plan_id, status) VALUES (:o, 'GROWTH', 'ACTIVE') "
                "ON CONFLICT (organization_id) DO UPDATE SET plan_id='GROWTH', status='ACTIVE', "
                "trial_ends_at=NULL, locks_at=NULL"
            ),
            {"o": DEMO_ORG_ID},
        )
        await db.execute(
            text(
                "INSERT INTO coupons (id, code, discount_type, discount_value, max_redemptions) "
                "VALUES (gen_random_uuid(), 'DEMO20', 'PERCENTAGE', 20, 100) ON CONFLICT (code) DO NOTHING"
            )
        )
    for email, role in USERS:
        async with login_lookup_session(email) as db:
            if (await db.execute(select(User.id).where(User.email == email))).first():
                continue
        async with tenant_session(DEMO_ORG_ID) as db:
            db.add(
                User(
                    organization_id=DEMO_ORG_ID,
                    email=email,
                    hashed_password=hash_password(DEMO_PASSWORD),
                    role=role,
                    email_verified_at=datetime.now(UTC),
                )
            )
    await dispose_engines()
    print(f"seeded demo org; log in as admin@demo.example.com / {DEMO_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
