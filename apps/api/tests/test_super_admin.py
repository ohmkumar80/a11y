import uuid

import pytest

from a11y_api.admin_cli import create_super_admin

from .conftest import sql


@pytest.fixture
async def admin_email():
    email = f"root-{uuid.uuid4().hex[:8]}@example.com"
    yield email
    await sql("DELETE FROM users WHERE email=$1", email)


async def test_create_and_login_super_admin_then_use_admin_api(client, admin_email):
    pw = "correct horse battery staple"
    assert await create_super_admin(admin_email, pw) is True
    assert await create_super_admin(admin_email, pw) is False  # idempotent
    r = await client.post("/auth/login", json={"email": admin_email, "password": pw})
    assert r.status_code == 200 and r.json()["user"]["role"] == "SUPER_ADMIN"
    assert (
        "a11y_refresh" not in r.cookies and "a11y_platform" in r.cookies
    )  # no tenant cookie; a platform one instead
    h = {"authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/admin/plans", headers=h)).status_code == 200
    assert (await client.get("/me", headers=h)).status_code == 403  # not a tenant member


async def test_super_admin_wrong_password_and_weak_password(client, admin_email):
    await create_super_admin(admin_email, "correct horse battery staple")
    r = await client.post(
        "/auth/login", json={"email": admin_email, "password": "nope-nope-nope-nope"}
    )
    assert r.status_code == 401
    with pytest.raises(ValueError):
        await create_super_admin("x@example.com", "short")
