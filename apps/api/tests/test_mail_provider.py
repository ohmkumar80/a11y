"""The mail server is an admin setting: used at send time, password encrypted and never shown, unsafe setups refused."""

import logging

import pytest
from a11y_core import mail as mail_mod
from a11y_core.config import Scope, get_config
from a11y_core.config.registry import GuardrailError
from a11y_core.mail import Mail, Mailer
from a11y_core.settings import get_settings

from .conftest import sql, super_admin_headers

PW = "smtp-pass-0123456789-SECRET"
MAIL = Mail(to="ada@example.com", subject="Hello", text="plain", html="<p>html</p>")


@pytest.fixture(autouse=True)
async def _clean():
    async def wipe():
        await sql("DELETE FROM setting_versions WHERE comment LIKE 'test-%'")
        r = get_config()._r()
        for k in await r.keys("cfg:*"):
            await r.delete(k)

    await wipe()
    yield
    await wipe()


@pytest.fixture
def smtp(monkeypatch):
    sent = []

    async def fake(msg, **kw):
        sent.append((msg, kw))

    monkeypatch.setattr(mail_mod.aiosmtplib, "send", fake)
    return sent


async def save(value, comment="test-mp"):
    await get_config().save("notify.provider", Scope.GLOBAL, "", value, comment=comment, actor=None)


async def test_without_settings_the_environment_is_used(smtp):
    await Mailer().send(MAIL)
    msg, kw = smtp[0]
    env = get_settings()
    assert kw["hostname"] == env.smtp_host and kw["port"] == env.smtp_port
    assert "start_tls" not in kw and "username" not in kw and msg["From"] == env.mail_from


async def test_smtp_settings_are_used_at_send_time_with_the_decrypted_password(smtp):
    await save(
        {
            "mode": "smtp",
            "host": "smtp.example.com",
            "port": 587,
            "security": "starttls",
            "username": "apikey",
            "password": {"$secret": True, "plaintext": PW},
            "from_address": "alerts@example.com",
            "from_name": "a11y",
            "reply_to": "help@example.com",
        }
    )
    await Mailer().send(MAIL)  # no redeploy, no restart
    msg, kw = smtp[0]
    assert (kw["hostname"], kw["port"], kw["start_tls"], kw["use_tls"]) == (
        "smtp.example.com",
        587,
        True,
        False,
    )
    assert (kw["username"], kw["password"]) == ("apikey", PW)
    assert (
        msg["From"] == "a11y <alerts@example.com>"
        and msg["Reply-To"] == "help@example.com"
        and msg["To"] == "ada@example.com"
    )
    await save(
        {"mode": "smtp", "host": "smtp.example.com", "port": 465, "security": "tls"},
        comment="test-mp2",
    )
    await Mailer().send(MAIL)
    assert (
        smtp[1][1]["use_tls"] is True
        and smtp[1][1]["start_tls"] is False
        and "username" not in smtp[1][1]
    )


async def test_a_failed_send_is_logged_without_the_password_and_raised_only_when_asked(
    monkeypatch, caplog
):
    async def boom(msg, **kw):
        raise ConnectionError("535 authentication failed")

    monkeypatch.setattr(mail_mod.aiosmtplib, "send", boom)
    await save(
        {
            "mode": "smtp",
            "host": "smtp.example.com",
            "security": "starttls",
            "username": "u",
            "password": {"$secret": True, "plaintext": PW},
        }
    )
    with caplog.at_level(logging.DEBUG):
        await Mailer().send(MAIL)  # the API's request must not fail because mail is down
        with pytest.raises(ConnectionError):
            await Mailer().send(MAIL, raise_errors=True)
    assert PW not in caplog.text


@pytest.mark.parametrize(
    "value,why",
    [
        ({"mode": "smtp", "host": ""}, "SMTP server"),
        (
            {"mode": "smtp", "host": "smtp.example.com", "security": "none"},
            "only allowed for a local",
        ),
        (
            {"mode": "smtp", "host": "smtp.example.com", "security": "none", "username": "u"},
            "unencrypted",
        ),
        (
            {"mode": "smtp", "host": "smtp.example.com", "from_address": "not-an-address"},
            "not a valid email",
        ),
        (
            {"mode": "smtp", "host": "smtp.example.com", "from_name": "Evil\nBcc: x@evil.example"},
            "Line breaks",
        ),
        (
            {"mode": "smtp", "host": "smtp.example.com", "reply_to": "a@b.c\r\nBcc: x@y.z"},
            "not a valid email",
        ),
    ],
)
async def test_unsafe_or_invalid_setups_are_refused(value, why):
    with pytest.raises(GuardrailError, match=why):
        await save(value)


async def test_a_local_development_inbox_needs_no_tls_or_password(smtp):
    await save({"mode": "smtp", "host": "mailpit", "port": 1025, "security": "none"})
    await Mailer().send(MAIL)
    assert smtp[0][1]["use_tls"] is False and smtp[0][1]["start_tls"] is False


async def test_the_password_is_encrypted_at_rest_write_only_and_kept_when_not_resubmitted(client):
    h = super_admin_headers()
    body = {
        "scope": "global",
        "scope_id": "",
        "comment": "test-mp",
        "publish": True,
        "value": {
            "mode": "smtp",
            "host": "smtp.example.com",
            "security": "starttls",
            "username": "u",
            "password": {"$secret": True, "plaintext": PW},
        },
    }
    assert (
        await client.put("/admin/settings/notify.provider", headers=h, json=body)
    ).status_code == 200
    shown = (await client.get("/admin/settings/notify.provider", headers=h)).text
    assert PW not in shown  # the API never returns the password, only whether one is set
    stored = (
        await sql(
            "SELECT value::text AS v FROM setting_versions WHERE key='notify.provider' ORDER BY version DESC LIMIT 1"
        )
    )[0]["v"]
    assert PW not in stored and '"ct"' in stored  # only ciphertext in the database
    # editing the host without re-entering the password keeps it
    body["value"]["host"] = "smtp2.example.com"
    body["value"]["password"] = {"$secret": True}
    body["comment"] = "test-mp2"
    assert (
        await client.put("/admin/settings/notify.provider", headers=h, json=body)
    ).status_code == 200
    cur = (await get_config().effective("notify.provider")).value
    assert cur.host == "smtp2.example.com" and cur.password.value() == PW


async def test_high_risk_flag_marks_the_setting_in_the_admin_list(client):
    defs = {
        d["key"]: d
        for d in (await client.get("/admin/settings", headers=super_admin_headers())).json()
    }
    assert defs["notify.provider"]["high_risk"] is True
