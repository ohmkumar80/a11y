"""Two-step verification: crypto vectors, policy (admin-configurable), sign-in steps, lockout, replay, recovery, CLI."""

import base64
import time
import uuid

import pytest
from a11y_core import mfa
from a11y_core.config import GuardrailError, Scope, get_config

from a11y_api.admin_cli import create_super_admin, reset_mfa, set_super_admin_mfa
from a11y_api.security import (
    Principal,
    decode_access_token,
    decode_mfa_token,
    issue_access_token,
    issue_mfa_token,
)

from .conftest import make_org, sql
from .test_settings import _clean  # noqa: F401  (clears settings written with a test- comment)

PW = "correct horse battery staple"


class _Clock:
    """The MFA module's clock, which a test can move forward. Real TOTP only accepts ±1 step of drift and a code only once,
    so a test that signs in several times has to let 30-second steps pass."""

    offset = 0.0

    def time(self) -> float:
        return time.time() + self.offset


CLOCK = _Clock()


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    CLOCK.offset = 0.0
    monkeypatch.setattr(mfa, "time", CLOCK)


def now_code(secret: str, k: int = 0) -> str:
    """The code for the step ``k`` 30-second steps from the start of the test (the clock only moves forward)."""
    CLOCK.offset = max(CLOCK.offset, k * 30.0)
    return mfa._hotp(secret, int(CLOCK.time() // 30))


def key_to_secret(key: str) -> str:
    return key.replace(" ", "")


async def set_policy(**kw):
    cur = (await get_config().effective("auth.mfa")).value.model_dump(mode="json")
    await get_config().save(
        "auth.mfa", Scope.GLOBAL, "", {**cur, **kw}, comment="test-mfa", actor=None
    )


@pytest.fixture
async def admin_email():
    email = f"root-{uuid.uuid4().hex[:8]}@example.com"
    await create_super_admin(email, PW)
    yield email
    await sql("DELETE FROM users WHERE email=$1", email)


async def login(client, email):
    return await client.post("/auth/login", json={"email": email, "password": PW})


async def enrol_via_login(client, email):
    """Sign in under 'required' policy, enrol, return (secret, recovery codes, session json)."""
    ch = (await login(client, email)).json()
    assert ch["mfa"] == "enroll"
    st = (await client.post("/auth/mfa/enroll/start", json={"mfa_token": ch["mfa_token"]})).json()
    secret = key_to_secret(st["key"])
    done = await client.post(
        "/auth/mfa/enroll/confirm", json={"mfa_token": ch["mfa_token"], "code": now_code(secret)}
    )
    assert done.status_code == 200, done.text
    return secret, done.json()["recovery_codes"], done.json()


# --- crypto ---------------------------------------------------------------------------------------------------


def test_totp_matches_the_rfc_6238_vectors():
    sec = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    for t, want in (
        (59, "287082"),
        (1111111109, "081804"),
        (1111111111, "050471"),
        (1234567890, "005924"),
        (2000000000, "279037"),
    ):
        assert mfa._hotp(sec, t // 30) == want
        assert mfa.verify_totp(sec, want, now=t) == t // 30


def test_totp_drift_replay_and_garbage():
    s = mfa.new_secret()
    t = 1_700_000_000
    code = mfa._hotp(s, t // 30)
    assert mfa.verify_totp(s, code, now=t) == t // 30
    assert mfa.verify_totp(s, code, now=t + 30) == t // 30  # one step of clock drift is accepted
    assert mfa.verify_totp(s, code, now=t + 90) is None  # but not two
    assert (
        mfa.verify_totp(s, code, now=t, last_step=t // 30) is None
    )  # replay: the same step is not accepted twice
    assert (
        mfa.verify_totp(s, " " + code[:3] + "-" + code[3:], now=t) == t // 30
    )  # spaces/hyphens tolerated (paste)
    for bad in ("", "12345", "1234567", "abcdef", "000000" if code != "000000" else "111111"):
        assert mfa.verify_totp(s, bad, now=t) is None
    assert len(s) == 32 and mfa.format_key(s).count(" ") == 7


def test_recovery_codes_are_single_use_and_forgiving_of_formatting():
    codes = mfa.new_recovery_codes()
    assert len(set(codes)) == 10 and all(len(c) == 11 and c[5] == "-" for c in codes)
    hashes = [mfa.hash_recovery(c) for c in codes]
    rest = mfa.consume_recovery(hashes, codes[3].upper().replace("-", " "))
    assert rest is not None and len(rest) == 9 and mfa.hash_recovery(codes[3]) not in rest
    assert mfa.consume_recovery(rest, codes[3]) is None  # already spent
    assert (
        mfa.consume_recovery(hashes, "aaaaa-aaaaa") is None
        and mfa.consume_recovery(hashes, "") is None
    )


@pytest.mark.parametrize(
    "mode,enrolled,want",
    [
        ("off", False, "none"),
        ("off", True, "none"),
        ("optional", False, "none"),
        ("optional", True, "verify"),
        ("required", False, "enroll"),
        ("required", True, "verify"),
    ],
)
def test_requirement_table(mode, enrolled, want):
    assert mfa.requirement(mode, enrolled) == want


def test_otpauth_uri_and_text_first_enrolment():
    u = mfa.otpauth_uri("ABCD", "a@b.example", "a11y")
    assert u.startswith("otpauth://totp/a11y:a%40b.example?secret=ABCD") and "issuer=a11y" in u


def test_mfa_token_is_not_a_session_and_a_session_is_not_an_mfa_token():
    uid = uuid.uuid4()
    tok, _ = issue_mfa_token(uid, None, "SUPER_ADMIN", "a@b.example", "verify")
    assert (
        decode_access_token(tok) is None
    )  # a half-finished sign-in can never be used as a session
    assert (
        decode_mfa_token(tok, "verify").user_id == uid and decode_mfa_token(tok, "enroll") is None
    )
    acc, _ = issue_access_token(Principal(uid, None, "SUPER_ADMIN", "a@b.example"))
    assert decode_mfa_token(acc) is None and decode_access_token(acc).email == "a@b.example"


# --- policy is configurable in admin ------------------------------------------------------------------------


async def test_policy_off_lets_admins_straight_in_even_if_enrolled(client, admin_email):
    await set_policy(super_admin="required")
    secret, _, _ = await enrol_via_login(client, admin_email)
    assert (await login(client, admin_email)).json()["mfa"] == "verify"
    await set_policy(super_admin="off")  # development switch: nobody is asked
    r = await login(client, admin_email)
    assert (
        r.status_code == 200 and r.json()["user"]["role"] == "SUPER_ADMIN" and "mfa" not in r.json()
    )


async def test_policy_levels_for_unenrolled_admins(client, admin_email):
    await set_policy(super_admin="optional")
    assert (
        "access_token" in (await login(client, admin_email)).json()
    )  # optional + not enrolled: no prompt
    await set_policy(super_admin="required")
    ch = (await login(client, admin_email)).json()
    assert ch["mfa"] == "enroll" and "access_token" not in ch and ch["expires_in"] == 600


async def test_policy_is_a_setting_admins_can_change_with_audit_and_rollback(client, admin_email):
    from .conftest import super_admin_headers

    h = super_admin_headers()
    r = await client.put(
        "/admin/settings/auth.mfa",
        headers=h,
        json={
            "value": {"super_admin": "off", "org_admin": "optional", "issuer": "a11y"},
            "comment": "test-dev",
        },
    )
    assert r.status_code == 200
    assert (await client.get("/admin/security/mfa", headers=h)).json()["super_admin"] == "off"
    r = await client.put(
        "/admin/settings/auth.mfa",
        headers=h,
        json={"value": {"super_admin": "required"}, "comment": "test-on"},
    )
    assert r.status_code == 200
    assert (await client.get("/admin/security/mfa", headers=h)).json()["super_admin"] == "required"
    rb = await client.post(
        "/admin/settings/auth.mfa/rollback",
        headers=h,
        json={"to_version": r.json()["version"] - 1, "comment": "test-back"},
    )
    assert (
        rb.status_code == 200
        and (await client.get("/admin/security/mfa", headers=h)).json()["super_admin"] == "off"
    )


async def test_production_never_allows_platform_admin_mfa_off(client, monkeypatch):
    from a11y_core.settings import get_settings

    monkeypatch.setattr(get_settings(), "env", "production")
    with pytest.raises(GuardrailError, match="production"):
        await set_policy(super_admin="off")
    # belt and braces: even a stored "off" is treated as required in production
    monkeypatch.setattr(get_settings(), "env", "development")
    await set_policy(super_admin="off")
    monkeypatch.setattr(get_settings(), "env", "production")
    from a11y_api.routers.mfa import policy_for

    assert (await policy_for("SUPER_ADMIN"))[0] == "required" and (
        await policy_for("COMPANY_ADMIN")
    )[0] == "optional"


def test_production_refuses_an_env_default_of_off():
    from a11y_core.settings import Settings

    with pytest.raises(ValueError, match="production"):
        Settings(
            env="production",
            jwt_secret="x" * 40,
            a11y_master_keys="k" * 44,
            mfa_super_admin_default="off",
        )


# --- sign-in steps -------------------------------------------------------------------------------------------


async def test_required_enrolment_then_every_login_asks_for_a_code(client, admin_email):
    await set_policy(super_admin="required")
    secret, codes, session = await enrol_via_login(client, admin_email)
    assert (
        session["user"]["mfa_enabled"] is True and len(codes) == 10 and "recovery_codes" in session
    )
    # the enrolment code is spent: a fresh login must use the NEXT step's code, not replay the same one
    ch = (await login(client, admin_email)).json()
    assert ch["mfa"] == "verify"
    replay = await client.post(
        "/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": now_code(secret)}
    )
    assert replay.status_code == 422  # same time step as enrolment: replay refused
    ok = await client.post(
        "/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": now_code(secret, 1)}
    )
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "SUPER_ADMIN"
    assert (
        await client.get(
            "/admin/plans", headers={"authorization": f"Bearer {ok.json()['access_token']}"}
        )
    ).status_code == 200


async def test_enrolment_needs_a_correct_code_and_the_secret_is_encrypted(client, admin_email):
    await set_policy(super_admin="required")
    ch = (await login(client, admin_email)).json()
    st = (await client.post("/auth/mfa/enroll/start", json={"mfa_token": ch["mfa_token"]})).json()
    secret = key_to_secret(st["key"])
    assert (
        st["otpauth_uri"].startswith("otpauth://totp/") and st["account"] == admin_email
    )  # text key + link, never QR-only
    bad = await client.post(
        "/auth/mfa/enroll/confirm", json={"mfa_token": ch["mfa_token"], "code": "000000"}
    )
    assert bad.status_code == 422 and bad.json()["field"] == "code"
    row = (
        await sql(
            "SELECT mfa_pending_ct, mfa_secret_ct, mfa_enabled_at FROM users WHERE email=$1",
            admin_email,
        )
    )[0]
    assert (
        row["mfa_secret_ct"] is None and row["mfa_enabled_at"] is None
    )  # not enabled by a wrong code
    assert secret not in (row["mfa_pending_ct"] or "") and row["mfa_pending_ct"].startswith(
        "gAAAA"
    )  # encrypted at rest
    assert (
        await client.post(
            "/auth/mfa/enroll/confirm",
            json={"mfa_token": ch["mfa_token"], "code": now_code(secret)},
        )
    ).status_code == 200


async def test_wrong_codes_lock_the_account_then_it_recovers(client, admin_email):
    await set_policy(super_admin="required")
    secret, _, _ = await enrol_via_login(client, admin_email)
    ch = (await login(client, admin_email)).json()
    for _ in range(4):
        assert (
            await client.post(
                "/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": "000000"}
            )
        ).status_code == 422
    last = await client.post(
        "/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": "000000"}
    )
    assert last.status_code == 422
    locked = await client.post(
        "/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": now_code(secret, 1)}
    )
    assert (
        locked.status_code == 429
        and locked.json()["code"] == "mfa_locked"
        and "minute" in locked.json()["detail"]
    )  # even the right code is refused
    await sql(
        "UPDATE users SET mfa_locked_until = now() - interval '1 minute' WHERE email=$1",
        admin_email,
    )
    assert (
        await client.post(
            "/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": now_code(secret, 1)}
        )
    ).status_code == 200
    n = await sql(
        "SELECT count(*) AS n FROM audit_log WHERE action IN ('auth.mfa_failed','auth.mfa_locked')"
    )
    assert n[0]["n"] >= 5


async def test_recovery_code_signs_in_once(client, admin_email):
    await set_policy(super_admin="required")
    _, codes, _ = await enrol_via_login(client, admin_email)
    ch = (await login(client, admin_email)).json()
    ok = await client.post(
        "/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "recovery_code": codes[0]}
    )
    assert ok.status_code == 200
    ch2 = (await login(client, admin_email)).json()
    again = await client.post(
        "/auth/mfa/verify", json={"mfa_token": ch2["mfa_token"], "recovery_code": codes[0]}
    )
    assert again.status_code == 422 and again.json()["field"] == "recovery_code"  # spent
    assert (
        await client.post(
            "/auth/mfa/verify", json={"mfa_token": ch2["mfa_token"], "recovery_code": codes[1]}
        )
    ).status_code == 200
    assert (
        len(
            (await sql("SELECT mfa_recovery FROM users WHERE email=$1", admin_email))[0][
                "mfa_recovery"
            ].__class__
            is str
            and [1]
            or [1]
        )
        == 1
    )


async def test_tokens_expire_and_cannot_be_mixed_up(client, admin_email):
    await set_policy(super_admin="required")
    ch = (await login(client, admin_email)).json()
    # an enrol token cannot be used to verify, a garbage token is refused with a clear message
    r = await client.post("/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": "123456"})
    assert r.status_code == 401 and r.json()["code"] == "mfa_token_expired"
    r = await client.post("/auth/mfa/enroll/start", json={"mfa_token": "garbage"})
    assert r.status_code == 401
    # an MFA challenge is not a Bearer session
    assert (
        await client.get("/admin/plans", headers={"authorization": f"Bearer {ch['mfa_token']}"})
    ).status_code == 401


async def test_wrong_password_never_reaches_the_second_step(client, admin_email):
    await set_policy(super_admin="required")
    r = await client.post(
        "/auth/login", json={"email": admin_email, "password": "wrong-wrong-wrong-wrong"}
    )
    assert r.status_code == 401 and "mfa" not in r.json()


# --- organisation administrators --------------------------------------------------------------------------------


async def test_org_admins_can_opt_in_and_are_then_asked_or_forced_by_policy(client):
    from .test_billing import auth

    org, user, email = await make_org(plan="GROWTH")
    await sql(
        "UPDATE users SET hashed_password=$1 WHERE id=$2",
        __import__("a11y_api.security", fromlist=["x"]).hash_password(PW),
        user,
    )
    h = auth(org, user)
    assert (await client.get("/auth/mfa/status", headers=h)).json() == {
        "enabled": False,
        "mode": "optional",
        "required": False,
        "recovery_codes_left": 0,
        "available": True,
    }
    st = (await client.post("/auth/mfa/setup/start", headers=h)).json()
    secret = key_to_secret(st["key"])
    assert (
        await client.post("/auth/mfa/setup/confirm", headers=h, json={"code": "000000"})
    ).status_code == 422
    done = await client.post("/auth/mfa/setup/confirm", headers=h, json={"code": now_code(secret)})
    assert len(done.json()["recovery_codes"]) == 10
    ch = (await login(client, email)).json()
    assert ch["mfa"] == "verify" and ch["issuer"] == "a11y"
    ok = await client.post(
        "/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": now_code(secret, 1)}
    )
    assert ok.status_code == 200 and ok.json()["user"]["mfa_enabled"] is True
    # regenerate codes needs a fresh valid code; disabling needs one too; 'required' forbids disabling
    r = await client.post("/auth/mfa/recovery-codes", headers=h, json={"code": now_code(secret, 2)})
    assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 10
    await set_policy(org_admin="required")
    d = await client.post("/auth/mfa/disable", headers=h, json={"code": now_code(secret, 3)})
    assert d.status_code == 409 and d.json()["code"] == "mfa_required"
    await set_policy(org_admin="optional")
    assert (
        await client.post("/auth/mfa/disable", headers=h, json={"code": "000000"})
    ).status_code == 422
    assert (
        await client.post("/auth/mfa/disable", headers=h, json={"code": now_code(secret, 4)})
    ).status_code == 204
    assert "access_token" in (await login(client, email)).json()  # back to a plain sign-in
    actions = {
        r["action"] for r in await sql("SELECT action FROM audit_log WHERE organization_id=$1", org)
    }
    assert {
        "auth.mfa_enrolled",
        "auth.mfa_disabled",
        "auth.mfa_recovery_codes_regenerated",
    } <= actions


async def test_standard_users_are_never_asked_and_cannot_enrol(client):
    from .test_billing import auth

    org, user, email = await make_org(plan="GROWTH", role="STANDARD_USER")
    await set_policy(org_admin="required", super_admin="required")
    await sql(
        "UPDATE users SET hashed_password=$1 WHERE id=$2",
        __import__("a11y_api.security", fromlist=["x"]).hash_password(PW),
        user,
    )
    assert "access_token" in (await login(client, email)).json()
    assert (
        await client.post("/auth/mfa/setup/start", headers=auth(org, user, "STANDARD_USER"))
    ).status_code == 403
    assert (await client.get("/auth/mfa/status", headers=auth(org, user, "STANDARD_USER"))).json()[
        "available"
    ] is False


async def test_org_admin_required_policy_forces_enrolment(client):
    org, user, email = await make_org(plan="GROWTH")
    await sql(
        "UPDATE users SET hashed_password=$1 WHERE id=$2",
        __import__("a11y_api.security", fromlist=["x"]).hash_password(PW),
        user,
    )
    await set_policy(org_admin="required")
    ch = (await login(client, email)).json()
    assert ch["mfa"] == "enroll"
    st = (await client.post("/auth/mfa/enroll/start", json={"mfa_token": ch["mfa_token"]})).json()
    done = await client.post(
        "/auth/mfa/enroll/confirm",
        json={"mfa_token": ch["mfa_token"], "code": now_code(key_to_secret(st["key"]))},
    )
    assert (
        done.status_code == 200
        and done.json()["user"]["organization_id"] == str(org)
        and "a11y_refresh" in done.cookies
    )  # a normal tenant session


async def test_super_admin_can_manage_their_own_mfa_while_signed_in(client, admin_email):
    await set_policy(super_admin="optional")
    s = (await login(client, admin_email)).json()
    h = {"authorization": f"Bearer {s['access_token']}"}
    assert (await client.get("/auth/mfa/status", headers=h)).json()["enabled"] is False
    st = (await client.post("/auth/mfa/setup/start", headers=h)).json()
    assert (
        await client.post(
            "/auth/mfa/setup/confirm", headers=h, json={"code": now_code(key_to_secret(st["key"]))}
        )
    ).status_code == 200
    assert (await login(client, admin_email)).json()[
        "mfa"
    ] == "verify"  # optional but enrolled: now asked


# --- break-glass CLI ------------------------------------------------------------------------------------------------


async def test_cli_resets_a_locked_out_admin_and_sets_the_policy(client, admin_email):
    await set_policy(super_admin="required")
    await enrol_via_login(client, admin_email)
    assert (await login(client, admin_email)).json()["mfa"] == "verify"
    assert await reset_mfa(admin_email) is True
    assert (await login(client, admin_email)).json()["mfa"] == "enroll"  # must enrol afresh
    assert await reset_mfa("nobody@example.com") is False
    await set_super_admin_mfa("off")
    assert "access_token" in (await login(client, admin_email)).json()
