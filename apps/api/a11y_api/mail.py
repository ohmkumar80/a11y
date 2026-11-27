"""Transactional email. Emails must themselves be accessible (PROJECT_PLAN 2.4): semantic
HTML with real text, sufficient contrast, a visible URL fallback and a plain-text part."""

import logging
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape

import aiosmtplib
from a11y_core.settings import get_settings

log = logging.getLogger(__name__)


@dataclass
class Mail:
    to: str
    subject: str
    text: str
    html: str


class Mailer:
    async def send(self, mail: Mail) -> None:
        s = get_settings()
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.mail_from, mail.to, mail.subject
        msg.set_content(mail.text)
        msg.add_alternative(mail.html, subtype="html")
        try:
            await aiosmtplib.send(msg, hostname=s.smtp_host, port=s.smtp_port, timeout=10)
        except Exception:  # noqa: BLE001 - never let mail failure change the HTTP response
            log.exception("failed to send mail")


class OutboxMailer(Mailer):
    """Test double."""

    def __init__(self) -> None:
        self.sent: list[Mail] = []

    async def send(self, mail: Mail) -> None:
        self.sent.append(mail)


_mailer: Mailer = Mailer()


def get_mailer() -> Mailer:
    return _mailer


def _render(title: str, intro: str, action_label: str, url: str, outro: str) -> Mail:
    # Link text says what the link does (SC 2.4.4); the raw URL is repeated for clients
    # that strip links. Colours: #1a1a1a on #fff = 17:1; link #0b4f9e on #fff = 8.6:1.
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{escape(title)}</title></head>
<body style="margin:0;padding:24px;background:#ffffff;color:#1a1a1a;font:16px/1.5 Arial,Helvetica,sans-serif">
<main style="max-width:36rem;margin:0 auto">
<h1 style="font-size:24px;line-height:1.3;margin:0 0 16px">{escape(title)}</h1>
<p>{escape(intro)}</p>
<p><a href="{escape(url)}" style="color:#0b4f9e;font-weight:bold;text-decoration:underline">{escape(action_label)}</a></p>
<p>If the link does not work, copy this address into your browser:<br>{escape(url)}</p>
<p>{escape(outro)}</p>
</main></body></html>"""
    text = f"{title}\n\n{intro}\n\n{action_label}: {url}\n\n{outro}\n"
    return Mail(to="", subject=title, text=text, html=html)


def _build(to: str, **kw: str) -> Mail:
    m = _render(**kw)
    m.to = to
    return m


def verify_email_mail(to: str, token: str) -> Mail:
    url = f"{get_settings().public_web_url}/verify-email?token={token}"
    return _build(
        to,
        title="Confirm your email address",
        intro="Confirm your email address to finish creating your account.",
        action_label="Confirm email address",
        url=url,
        outro="This link works for 24 hours. If you did not sign up, you can ignore this email.",
    )


def reset_password_mail(to: str, token: str) -> Mail:
    url = f"{get_settings().public_web_url}/reset-password?token={token}"
    return _build(
        to,
        title="Reset your password",
        intro="We received a request to reset your password.",
        action_label="Choose a new password",
        url=url,
        outro="This link works for 1 hour. If you did not ask for this, you can ignore this email.",
    )


def invite_mail(to: str, token: str, org_name: str) -> Mail:
    url = f"{get_settings().public_web_url}/accept-invite?token={token}"
    return _build(
        to,
        title=f"You are invited to join {org_name}",
        intro=f"{org_name} invited you to join their team.",
        action_label="Accept the invitation",
        url=url,
        outro="This invitation works for 7 days.",
    )


def already_registered_mail(to: str) -> Mail:
    url = f"{get_settings().public_web_url}/login"
    return _build(
        to,
        title="You already have an account",
        intro="Someone tried to sign up with this email address, but an account already exists.",
        action_label="Log in",
        url=url,
        outro="If this was you, log in or reset your password. If not, no action is needed.",
    )
