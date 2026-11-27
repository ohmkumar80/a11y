"""Sending email. Lives in the core library so the API and the workers share it.

``send`` never raises by default: an API response must not change because the mail server is down. The delivery
job asks for ``raise_errors`` so a failed send is retried and logged instead of silently lost."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Literal

import aiosmtplib
from pydantic import BaseModel, Field, model_validator

from .config import get_config
from .config.registry import GuardrailError, Secret, SettingDef, register
from .settings import get_settings

log = logging.getLogger(__name__)


_LOCAL = {
    "localhost",
    "127.0.0.1",
    "::1",
    "mailpit",
}  # development inboxes: no passwords, no TLS needed
_EMAIL = re.compile(r"^[^\s@<>\r\n]+@[^\s@<>\r\n]+\.[^\s@<>\r\n]+$")


class MailProvider(BaseModel):
    """Where email goes. ``environment`` (the default) uses the SMTP_* and MAIL_FROM environment variables; ``smtp`` uses
    these settings, so a platform admin can change the mail server without a redeploy."""

    mode: Literal["environment", "smtp"] = "environment"
    host: str = Field("", max_length=253, description="SMTP server, for example smtp.example.com")
    port: int = Field(587, ge=1, le=65535)
    security: Literal["starttls", "tls", "none"] = Field(
        "starttls",
        description="starttls (port 587), tls (port 465) or none (development inboxes only)",
    )
    username: str = Field("", max_length=200)
    password: Secret = Field(default_factory=Secret)
    from_address: str = Field(
        "", max_length=320, description="Empty = the MAIL_FROM environment value"
    )
    from_name: str = Field(
        "", max_length=100, description="Shown beside the address, for example the product name"
    )
    reply_to: str = Field("", max_length=320)

    @model_validator(mode="after")
    def _valid(self):
        if self.mode == "smtp" and not self.host.strip():
            raise ValueError("Enter the SMTP server address.")
        for label, value in (
            ("From address", self.from_address),
            ("Reply-to address", self.reply_to),
        ):
            if value and not _EMAIL.match(value):
                raise ValueError(f"{label} is not a valid email address.")
        if re.search(r"[\r\n]", self.from_name + self.host + self.username):
            raise ValueError("Line breaks are not allowed here.")
        return self


def _provider_guard(new: MailProvider, prev: MailProvider) -> None:
    if new.mode != "smtp":
        return
    secured = new.security in ("starttls", "tls")
    if (
        (new.username or new.password.is_set or new.password.plaintext)
        and not secured
        and new.host.lower() not in _LOCAL
    ):
        raise GuardrailError(
            "A username and password would be sent unencrypted. Choose starttls or tls, or remove the credentials."
        )
    if new.security == "none" and new.host.lower() not in _LOCAL:
        raise GuardrailError(
            "Unencrypted mail is only allowed for a local development inbox (localhost or mailpit)."
        )


register(
    SettingDef(
        key="notify.provider",
        model=MailProvider,
        default=MailProvider(),
        description="The mail server and sender address. Use the Emails tab to send yourself a test after changing it. "
        "The password is write-only.",
        guard=_provider_guard,
        high_risk=True,
        owner_role="PLATFORM_OWNER",
        tags=("notifications",),
    )
)


@dataclass
class Mail:
    to: str
    subject: str
    text: str
    html: str


class Mailer:
    async def send(self, mail: Mail, *, raise_errors: bool = False) -> None:
        env = get_settings()
        try:
            p = (await get_config().effective("notify.provider")).value
        except Exception:  # noqa: BLE001 - never let a settings problem stop mail: fall back to the environment
            log.exception("mail provider settings unavailable; using the environment")
            p = MailProvider()
        use = p.mode == "smtp"
        sender = p.from_address if use and p.from_address else env.mail_from
        msg = EmailMessage()
        msg["From"] = formataddr((p.from_name, sender)) if use and p.from_name else sender
        msg["To"], msg["Subject"] = mail.to, mail.subject
        if use and p.reply_to:
            msg["Reply-To"] = p.reply_to
        msg.set_content(mail.text)
        msg.add_alternative(mail.html, subtype="html")
        kwargs: dict = {
            "hostname": p.host if use else env.smtp_host,
            "port": p.port if use else env.smtp_port,
            "timeout": 10,
        }
        if use:
            kwargs["use_tls"] = p.security == "tls"
            kwargs["start_tls"] = p.security == "starttls"
            if p.username:
                kwargs["username"] = p.username
                kwargs["password"] = p.password.value() if p.password.is_set else ""
        try:
            await aiosmtplib.send(msg, **kwargs)
        except Exception:
            log.exception("failed to send mail")
            if raise_errors:
                raise


class OutboxMailer(Mailer):
    """Test double: collects mail instead of sending it."""

    def __init__(self) -> None:
        self.sent: list[Mail] = []

    async def send(self, mail: Mail, *, raise_errors: bool = False) -> None:
        self.sent.append(mail)


_mailer: Mailer = Mailer()


def get_mailer() -> Mailer:
    return _mailer


def set_mailer(m: Mailer) -> Mailer:
    """Swap the process-wide mailer (tests, or a different provider). Returns the previous one."""
    global _mailer
    prev, _mailer = _mailer, m
    return prev
