"""Sending email. Lives in the core library so the API and the workers share it.

``send`` never raises by default: an API response must not change because the mail server is down. The delivery
job asks for ``raise_errors`` so a failed send is retried and logged instead of silently lost."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from email.message import EmailMessage

import aiosmtplib

from .settings import get_settings

log = logging.getLogger(__name__)


@dataclass
class Mail:
    to: str
    subject: str
    text: str
    html: str


class Mailer:
    async def send(self, mail: Mail, *, raise_errors: bool = False) -> None:
        s = get_settings()
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.mail_from, mail.to, mail.subject
        msg.set_content(mail.text)
        msg.add_alternative(mail.html, subtype="html")
        try:
            await aiosmtplib.send(msg, hostname=s.smtp_host, port=s.smtp_port, timeout=10)
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
