import re
import uuid

from .conftest import TEST_PREFIX

PW = "a long enough passphrase"


def _token(outbox, to):
    mail = next(m for m in reversed(outbox.sent) if m.to == to)
    return re.search(r"token=([\w.\-]+)", mail.text).group(1)


def _cookie(r):
    return {"cookie": f"a11y_refresh={r.cookies['a11y_refresh']}"}


async def _signup_verified(client, outbox):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/auth/signup",
        json={"organization_name": f"{TEST_PREFIX}{email}", "email": email, "password": PW},
    )
    assert r.status_code == 202
    assert (
        await client.post("/auth/verify-email", json={"token": _token(outbox, email)})
    ).status_code == 204
    return email


async def test_signup_verify_login_me(client, outbox):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    await client.post(
        "/auth/signup",
        json={"organization_name": f"{TEST_PREFIX}a", "email": email, "password": PW},
    )
    # unverified accounts cannot log in, and the error is machine-readable
    r = await client.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 403 and r.json()["code"] == "email_not_verified"
    await client.post("/auth/verify-email", json={"token": _token(outbox, email)})
    r = await client.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/api/auth" in cookie
    me = await client.get("/me", headers={"authorization": f"Bearer {r.json()['access_token']}"})
    assert me.json()["email"] == email and me.json()["role"] == "COMPANY_ADMIN"


async def test_verification_token_is_single_use(client, outbox):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    await client.post(
        "/auth/signup",
        json={"organization_name": f"{TEST_PREFIX}b", "email": email, "password": PW},
    )
    t = _token(outbox, email)
    assert (await client.post("/auth/verify-email", json={"token": t})).status_code == 204
    assert (await client.post("/auth/verify-email", json={"token": t})).status_code == 400


async def test_wrong_password_and_unknown_user_look_identical(client, outbox):
    email = await _signup_verified(client, outbox)
    a = await client.post("/auth/login", json={"email": email, "password": "wrong password here"})
    b = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "wrong password here"}
    )
    assert (
        (a.status_code, a.json())
        == (b.status_code, b.json())
        == (401, {"detail": "Email or password is incorrect."})
    )


async def test_signup_does_not_reveal_existing_accounts(client, outbox):
    email = await _signup_verified(client, outbox)
    again = await client.post(
        "/auth/signup",
        json={"organization_name": f"{TEST_PREFIX}dup", "email": email, "password": PW},
    )
    notice = outbox.sent[-1]
    fresh = await client.post(
        "/auth/signup",
        json={
            "organization_name": f"{TEST_PREFIX}new",
            "email": f"{uuid.uuid4().hex[:8]}@example.com",
            "password": PW,
        },
    )
    assert (again.status_code, again.json()) == (fresh.status_code, fresh.json())
    assert notice.to == email and "already have an account" in notice.subject


async def test_password_rules_allow_passphrases_and_reject_short(client):
    r = await client.post(
        "/auth/signup",
        json={"organization_name": "x", "email": "s@example.com", "password": "short"},
    )
    assert r.status_code == 422 and r.json()["field"] == "password"
    # No composition rules (SC 3.3.8): all-lowercase words with spaces are fine.
    r = await client.post(
        "/auth/signup",
        json={
            "organization_name": f"{TEST_PREFIX}pp",
            "email": f"{uuid.uuid4().hex[:8]}@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert r.status_code == 202


async def test_validation_errors_use_the_common_shape(client):
    r = await client.post("/auth/login", json={"email": "not-an-email", "password": "x"})
    assert r.status_code == 422 and r.json() == {
        "detail": "Enter a valid email address.",
        "field": "email",
    }


async def test_refresh_rotates_and_reuse_revokes_family(client, outbox):
    email = await _signup_verified(client, outbox)
    login = await client.post("/auth/login", json={"email": email, "password": PW})
    first = _cookie(login)
    r2 = await client.post("/auth/refresh", headers=first)
    assert r2.status_code == 200
    second = _cookie(r2)
    assert first != second
    # Replaying the old token = theft signal: it fails AND kills the new one.
    assert (await client.post("/auth/refresh", headers=first)).status_code == 401
    assert (await client.post("/auth/refresh", headers=second)).status_code == 401


async def test_logout_revokes_refresh_token(client, outbox):
    email = await _signup_verified(client, outbox)
    c = _cookie(await client.post("/auth/login", json={"email": email, "password": PW}))
    assert (await client.post("/auth/logout", headers=c)).status_code == 204
    assert (await client.post("/auth/refresh", headers=c)).status_code == 401


async def test_password_reset_flow_signs_out_other_sessions(client, outbox):
    email = await _signup_verified(client, outbox)
    old = _cookie(await client.post("/auth/login", json={"email": email, "password": PW}))
    unknown = await client.post("/auth/password-reset/request", json={"email": "ghost@example.com"})
    known = await client.post("/auth/password-reset/request", json={"email": email})
    assert unknown.json() == known.json() and known.status_code == 202
    t = _token(outbox, email)
    weak = await client.post("/auth/password-reset/confirm", json={"token": t, "password": "short"})
    assert weak.status_code == 422  # token NOT consumed by a rejected password
    new_pw = "another long passphrase"
    assert (
        await client.post("/auth/password-reset/confirm", json={"token": t, "password": new_pw})
    ).status_code == 204
    assert (
        await client.post("/auth/password-reset/confirm", json={"token": t, "password": new_pw})
    ).status_code == 400
    assert (await client.post("/auth/refresh", headers=old)).status_code == 401
    assert (
        await client.post("/auth/login", json={"email": email, "password": new_pw})
    ).status_code == 200
    assert (
        await client.post("/auth/login", json={"email": email, "password": PW})
    ).status_code == 401


async def test_forged_or_cross_tenant_tokens_are_rejected(client, outbox):
    a = await _signup_verified(client, outbox)
    ta = _token(outbox, a)  # already used, but also test org-prefix swapping
    b = await _signup_verified(client, outbox)
    await client.post("/auth/password-reset/request", json={"email": b})
    tb = _token(outbox, b)
    forged = ta.split(".")[0] + "." + tb.split(".", 1)[1]  # A's org prefix + B's secret
    assert (
        await client.post(
            "/auth/password-reset/confirm", json={"token": forged, "password": "x" * 14}
        )
    ).status_code == 400
    assert (await client.post("/auth/verify-email", json={"token": "garbage"})).status_code == 400


async def test_invite_flow_and_role_enforcement(client, outbox):
    admin = await _signup_verified(client, outbox)
    access = (await client.post("/auth/login", json={"email": admin, "password": PW})).json()[
        "access_token"
    ]
    h = {"authorization": f"Bearer {access}"}
    invitee = f"{uuid.uuid4().hex[:10]}@example.com"
    assert (await client.post("/invites", json={"email": invitee}, headers=h)).status_code == 202
    assert (await client.post("/invites", json={"email": invitee})).status_code == 401
    t = _token(outbox, invitee)
    prev = (await client.get(f"/invites/{t}")).json()
    assert prev["email"] == invitee  # pre-filled on the accept page (SC 3.3.7)
    assert (
        await client.post("/invites/accept", json={"token": t, "password": PW})
    ).status_code == 204
    assert (
        await client.post("/invites/accept", json={"token": t, "password": PW})
    ).status_code == 400
    member = (await client.post("/auth/login", json={"email": invitee, "password": PW})).json()
    assert member["user"]["role"] == "STANDARD_USER"
    mh = {"authorization": f"Bearer {member['access_token']}"}
    assert (await client.get("/org/users", headers=mh)).status_code == 403
    users = (await client.get("/org/users", headers=h)).json()
    assert {u["email"] for u in users} == {admin, invitee}
    assert (
        await client.post("/invites", json={"email": "z@example.com"}, headers=mh)
    ).status_code == 403


async def test_org_users_endpoint_never_leaks_other_tenants(client, outbox):
    a = await _signup_verified(client, outbox)
    await _signup_verified(client, outbox)
    access = (await client.post("/auth/login", json={"email": a, "password": PW})).json()[
        "access_token"
    ]
    users = (await client.get("/org/users", headers={"authorization": f"Bearer {access}"})).json()
    assert [u["email"] for u in users] == [a]


async def test_tampered_or_missing_jwt_rejected(client):
    assert (await client.get("/me")).status_code == 401
    assert (
        await client.get("/me", headers={"authorization": "Bearer abc.def.ghi"})
    ).status_code == 401
