"""Create a Super Admin (platform operator): ``python -m a11y_api.admin_cli EMAIL``.

Super Admins have no tenant. The password is read from the A11Y_ADMIN_PASSWORD_INPUT env var or
prompted for, never taken from argv (shell history). TODO before production: mandatory MFA for
this role (PROJECT_PLAN 3.11.1 / Phase 2 auth policy)."""

import asyncio
import getpass
import os
import sys
from datetime import UTC, datetime

from a11y_core.db import dispose_engines, login_lookup_session
from a11y_core.models import Role, User
from sqlalchemy import select

from .security import hash_password, password_problem


async def create_super_admin(email: str, password: str) -> bool:
    """Returns False if the account already exists."""
    email = email.strip().lower()
    if problem := password_problem(password, email):
        raise ValueError(problem)
    async with login_lookup_session(email) as db:
        if (await db.execute(select(User.id).where(User.email == email))).first():
            return False
        db.add(
            User(
                organization_id=None,
                email=email,
                hashed_password=hash_password(password),
                role=Role.SUPER_ADMIN,
                email_verified_at=datetime.now(UTC),
            )
        )
    return True


async def _main(email: str) -> None:
    password = os.environ.get("A11Y_ADMIN_PASSWORD_INPUT") or getpass.getpass("Password: ")
    try:
        created = await create_super_admin(email, password)
    finally:
        await dispose_engines()
    print("created" if created else "already exists")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m a11y_api.admin_cli EMAIL")
    asyncio.run(_main(sys.argv[1]))
