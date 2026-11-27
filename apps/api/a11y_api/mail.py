"""Transactional email for the API. The sending code lives in ``a11y_core.mail`` and the events, wording and layout in
``a11y_core.notify`` (so workers share them and admins can edit the wording). These helpers build the account emails."""

from a11y_core import notify
from a11y_core.mail import Mail, Mailer, OutboxMailer, get_mailer

__all__ = [
    "Mail",
    "Mailer",
    "OutboxMailer",
    "already_registered_mail",
    "get_mailer",
    "invite_mail",
    "reset_password_mail",
    "verify_email_mail",
]


async def _required(event: str, to: str, variables: dict[str, str]) -> Mail:
    mail = await notify.build(event, to, variables)
    assert mail is not None, f"{event} cannot be switched off"  # the setting's guard refuses it
    return mail


async def verify_email_mail(to: str, token: str) -> Mail:
    return await _required("auth.verify_email", to, {"token": token})


async def reset_password_mail(to: str, token: str) -> Mail:
    return await _required("auth.reset_password", to, {"token": token})


async def invite_mail(to: str, token: str, org_name: str) -> Mail:
    return await _required("auth.invite", to, {"token": token, "org_name": org_name})


async def already_registered_mail(to: str) -> Mail:
    return await _required("auth.already_registered", to, {})
