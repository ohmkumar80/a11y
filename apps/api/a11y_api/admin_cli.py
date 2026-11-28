"""Platform-operator commands.

  python -m a11y_api.admin_cli EMAIL                 create a Super Admin
  python -m a11y_api.admin_cli --reset-mfa EMAIL     break-glass: clear someone's two-step verification (locked out)
  python -m a11y_api.admin_cli --mfa-super-admin off|optional|required
                                                     break-glass: set the platform-admin MFA policy ("off" is refused
                                                     when ENV=production)

Create a Super Admin (platform operator): ``python -m a11y_api.admin_cli EMAIL``.

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
from sqlalchemy import select, update

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


async def reset_mfa(email: str) -> bool:
    """Clear MFA for an account. Used when an administrator lost their authenticator AND their recovery codes."""
    email = email.strip().lower()
    async with login_lookup_session(email) as db:
        res = await db.execute(
            update(User)
            .where(User.email == email)
            .values(
                mfa_secret_ct=None,
                mfa_pending_ct=None,
                mfa_enabled_at=None,
                mfa_recovery=[],
                mfa_last_step=0,
                mfa_failed=0,
                mfa_locked_until=None,
            )
        )
    return bool(res.rowcount)


async def set_super_admin_mfa(mode: str) -> None:
    from a11y_core.config import Scope, get_config  # noqa: PLC0415

    cfg = get_config()
    cur = (await cfg.effective("auth.mfa")).value.model_dump(mode="json")
    cur["super_admin"] = mode
    await cfg.save(
        "auth.mfa",
        Scope.GLOBAL,
        "",
        cur,
        comment=f"CLI: platform-admin MFA set to {mode}",
        actor=None,
    )


async def _main(email: str) -> None:
    password = os.environ.get("A11Y_ADMIN_PASSWORD_INPUT") or getpass.getpass("Password: ")
    try:
        created = await create_super_admin(email, password)
    finally:
        await dispose_engines()
    print("created" if created else "already exists")


async def _run(argv: list[str]) -> None:
    try:
        if argv[:1] == ["--reset-mfa"] and len(argv) == 2:
            print(
                "two-step verification cleared" if await reset_mfa(argv[1]) else "no such account"
            )
        elif (
            argv[:1] == ["--mfa-super-admin"]
            and len(argv) == 2
            and argv[1] in ("off", "optional", "required")
        ):
            await set_super_admin_mfa(argv[1])
            print(f"platform-admin MFA policy is now: {argv[1]}")
        elif len(argv) == 1 and not argv[0].startswith("--"):
            await _main(argv[0])
        else:
            raise SystemExit(
                "usage: python -m a11y_api.admin_cli EMAIL | --reset-mfa EMAIL | --mfa-super-admin off|optional|required"
            )
    finally:
        await dispose_engines()


if __name__ == "__main__":
    asyncio.run(_run(sys.argv[1:]))
