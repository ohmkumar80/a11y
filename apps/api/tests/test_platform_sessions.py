"""Super Admin sessions: rotating refresh cookie, replay detection, absolute lifetime, MFA interplay, isolation."""

import asyncio
import uuid

import pytest
from a11y_core.db import app_engine, platform_session
from sqlalchemy import text

from a11y_api.admin_cli import create_super_admin
from a11y_api.security import hash_password, hash_token

from .conftest import make_org, sql
from .test_mfa import CLOCK, PW, _clock, enrol_via_login, key_to_secret, now_code, set_policy  # noqa: F401
from .test_settings import _clean  # noqa: F401


@pytest.fixture
async def admin_email():
    email = f"root-{uuid.uuid4().hex[:8]}@example.com"
    await create_super_admin(email, PW)
    yield email
    await sql("DELETE FROM platform_sessions WHERE email=$1", email)
    await sql("DELETE FROM users WHERE email=$1", email)


def cookie(r, name="a11y_platform"):
    return {"cookie": f"{name}={r.cookies[name]}"}


async def login(client, email):
    return await client.post("/auth/login", json={"email": email, "password": PW})


async def test_login_sets_a_rotating_http_only_cookie_and_refresh_issues_a_new_session(
    client, admin_email
):
    r = await login(client, admin_email)
    sc = r.headers["set-cookie"].lower()
    assert (
        "a11y_platform=" in sc
        and "httponly" in sc
        and "samesite=lax" in sc
        and "path=/api/auth" in sc
    )
    ref = await client.post("/auth/refresh", headers=cookie(r))
    assert (
        ref.status_code == 200
        and ref.json()["user"]["role"] == "SUPER_ADMIN"
        and ref.json()["expires_in"] == 900
    )
    assert ref.cookies["a11y_platform"] != r.cookies["a11y_platform"]  # rotated
    assert (
        await client.get(
            "/admin/plans", headers={"authorization": f"Bearer {ref.json()['access_token']}"}
        )
    ).status_code == 200
    again = await client.post("/auth/refresh", headers=cookie(ref))  # and the chain continues
    assert again.status_code == 200


async def test_tokens_are_stored_hashed_never_raw(client, admin_email):
    r = await login(client, admin_email)
    raw = r.cookies["a11y_platform"]
    rows = await sql("SELECT token_hash FROM platform_sessions WHERE email=$1", admin_email)
    assert [x["token_hash"] for x in rows] == [hash_token(raw)] and raw not in rows[0]["token_hash"]


async def test_replaying_a_rotated_token_revokes_the_whole_sign_in(client, admin_email):
    first = await login(client, admin_email)
    second = await client.post("/auth/refresh", headers=cookie(first))
    assert second.status_code == 200
    replay = await client.post(
        "/auth/refresh", headers=cookie(first)
    )  # the old token comes back: theft
    assert replay.status_code == 401
    assert (
        await client.post("/auth/refresh", headers=cookie(second))
    ).status_code == 401  # the legitimate one is dead too
    assert all(
        x["revoked_at"] is not None
        for x in await sql("SELECT revoked_at FROM platform_sessions WHERE email=$1", admin_email)
    )


async def test_concurrent_refreshes_cannot_both_win(client, admin_email):
    r = await login(client, admin_email)
    res = await asyncio.gather(*[client.post("/auth/refresh", headers=cookie(r)) for _ in range(6)])
    assert (
        sorted(x.status_code for x in res).count(200) == 1
    )  # one rotation; the rest look like replays


async def test_expiry_and_the_absolute_lifetime(client, admin_email):
    r = await login(client, admin_email)
    await sql(
        "UPDATE platform_sessions SET expires_at = now() - interval '1 minute' WHERE email=$1",
        admin_email,
    )
    assert (await client.post("/auth/refresh", headers=cookie(r))).status_code == 401
    r2 = await login(client, admin_email)
    cur = r2
    await sql(
        "UPDATE platform_sessions SET family_started_at = now() - interval '25 hours' WHERE token_hash=$1",
        hash_token(cur.cookies["a11y_platform"]),
    )
    assert (
        await client.post("/auth/refresh", headers=cookie(cur))
    ).status_code == 401  # however often it refreshes, 24 h is the cap


async def test_logout_ends_the_sign_in(client, admin_email):
    r = await login(client, admin_email)
    out = await client.post("/auth/logout", headers=cookie(r))
    assert out.status_code == 204 and "a11y_platform=" in out.headers["set-cookie"]  # cleared
    assert (await client.post("/auth/refresh", headers=cookie(r))).status_code == 401


async def test_a_deactivated_or_demoted_admin_cannot_refresh(client, admin_email):
    a = await login(client, admin_email)
    await sql("UPDATE users SET is_active=false WHERE email=$1", admin_email)
    assert (await client.post("/auth/refresh", headers=cookie(a))).status_code == 401
    await sql("UPDATE users SET is_active=true WHERE email=$1", admin_email)
    b = await login(client, admin_email)
    await sql(
        "UPDATE platform_sessions SET email='nobody@example.com' WHERE token_hash=$1",
        hash_token(b.cookies["a11y_platform"]),
    )
    assert (
        await client.post("/auth/refresh", headers=cookie(b))
    ).status_code == 401  # no such account


async def test_no_cookie_or_garbage_is_unauthorised(client):
    assert (await client.post("/auth/refresh")).status_code == 401
    assert (
        await client.post("/auth/refresh", headers={"cookie": "a11y_platform=not-a-token"})
    ).status_code == 401


# --- MFA interplay ------------------------------------------------------------------------------------------------


async def test_a_session_that_never_passed_mfa_cannot_refresh_once_policy_requires_it(
    client, admin_email
):
    await set_policy(super_admin="off")
    r = await login(client, admin_email)  # signed in while MFA was off
    first = await client.post("/auth/refresh", headers=cookie(r))
    assert first.status_code == 200
    await set_policy(super_admin="required")
    cur = await client.post("/auth/refresh", headers=cookie(first))
    assert cur.status_code == 401 and cur.json()["code"] == "mfa_required"
    assert "a11y_platform=" in cur.headers["set-cookie"]


async def test_a_session_that_passed_mfa_keeps_refreshing_under_required(client, admin_email):
    await set_policy(super_admin="required")
    secret, _, session = await enrol_via_login(
        client, admin_email
    )  # enrolment signs in WITH mfa verified
    assert session["user"]["mfa_enabled"] is True
    # the enrolment response carried the platform cookie
    r = await client.post(
        "/auth/refresh", headers={"cookie": f"a11y_platform={_last_cookie(client, admin_email)}"}
    )
    assert r.status_code == 200


def _last_cookie(client, email):
    return client.cookies.get("a11y_platform")


async def test_organisation_admin_sessions_are_also_cut_off_when_policy_becomes_required(client):
    org, user, email = await make_org(plan="GROWTH")
    await sql("UPDATE users SET hashed_password=$1 WHERE id=$2", hash_password(PW), user)
    r = await login(client, email)  # org_admin policy is "optional": plain sign-in
    assert "a11y_refresh" in r.cookies
    assert (
        await client.post("/auth/refresh", headers=cookie(r, "a11y_refresh"))
    ).status_code == 200
    ok = await client.post(
        "/auth/refresh", headers=cookie(r, "a11y_refresh")
    )  # (old token replayed: dead) -> sign in again
    r = await login(client, email)
    await set_policy(org_admin="required")
    blocked = await client.post("/auth/refresh", headers=cookie(r, "a11y_refresh"))
    assert (
        ok.status_code == 401
        and blocked.status_code == 401
        and blocked.json()["code"] == "mfa_required"
    )


async def test_standard_users_are_unaffected_by_the_policy(client):
    org, user, email = await make_org(plan="GROWTH", role="STANDARD_USER")
    await sql("UPDATE users SET hashed_password=$1 WHERE id=$2", hash_password(PW), user)
    await set_policy(org_admin="required", super_admin="required")
    r = await login(client, email)
    assert (
        await client.post("/auth/refresh", headers=cookie(r, "a11y_refresh"))
    ).status_code == 200


# --- isolation ----------------------------------------------------------------------------------------------------


async def test_platform_sessions_are_invisible_without_the_token(client, admin_email):
    a = await login(client, admin_email)
    other = f"root-{uuid.uuid4().hex[:8]}@example.com"
    await create_super_admin(other, PW)
    try:
        b = await login(client, other)
        async with app_engine().connect() as c:  # no token presented: the table looks empty
            assert (
                await c.execute(text("SELECT count(*) FROM platform_sessions"))
            ).scalar_one() == 0
        async with platform_session(hash_token(a.cookies["a11y_platform"])) as db:
            rows = (await db.execute(text("SELECT email FROM platform_sessions"))).all()
            assert [r.email for r in rows] == [
                admin_email
            ]  # only the presented token's row, not the other admin's
            with pytest.raises(Exception):  # noqa: B017, PT011  - cannot write a row for a different token
                await db.execute(
                    text(
                        "INSERT INTO platform_sessions (id, token_hash, family_id, user_id, email, family_started_at, expires_at) "
                        "VALUES (gen_random_uuid(), 'someone-elses', gen_random_uuid(), gen_random_uuid(), 'x@y.z', now(), now())"
                    )
                )
        assert b.cookies["a11y_platform"] != a.cookies["a11y_platform"]
    finally:
        await sql("DELETE FROM platform_sessions WHERE email=$1", other)
        await sql("DELETE FROM users WHERE email=$1", other)


async def test_app_role_cannot_delete_sessions_but_the_purge_job_can(client, admin_email):
    from a11y_core.billing_jobs import purge_platform_sessions

    r = await login(client, admin_email)
    async with platform_session(hash_token(r.cookies["a11y_platform"])) as db:
        with pytest.raises(Exception):  # noqa: B017, PT011
            await db.execute(text("DELETE FROM platform_sessions"))
    await sql(
        "INSERT INTO platform_sessions (id, token_hash, family_id, user_id, email, family_started_at, expires_at) VALUES (gen_random_uuid(), 'old-expired-x', gen_random_uuid(), gen_random_uuid(), $1, now() - interval '9 days', now() - interval '8 days')",
        admin_email,
    )
    assert await purge_platform_sessions() >= 1
    left = {
        x["token_hash"]
        for x in await sql("SELECT token_hash FROM platform_sessions WHERE email=$1", admin_email)
    }
    assert (
        "old-expired-x" not in left and hash_token(r.cookies["a11y_platform"]) in left
    )  # only the stale row went
