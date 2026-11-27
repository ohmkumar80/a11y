"""Scheduled billing work. Runs as a system job, so it uses the audited cross-tenant session."""

import asyncio
import logging
import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from . import notify
from .celery_app import celery_app
from .config import get_config
from .db import admin_session

log = logging.getLogger(__name__)


async def expire_trials() -> int:
    """Persist LOCKED_READ_ONLY for trials past their deadline. Returns how many changed.

    The request guard (billing.effective_status) already refuses work from the deadline on, so
    this only keeps the stored status, admin dashboards and funnel counts truthful. A late or
    missed run cannot extend anyone's trial."""
    async with admin_session(
        actor_user_id=None, reason="hourly trial expiry", action="system.expire_trials"
    ) as db:
        rows = (
            await db.execute(
                text(
                    "UPDATE subscriptions s SET status='LOCKED_READ_ONLY', updated_at=now() "
                    "FROM plans p WHERE s.plan_id = p.id AND s.status='TRIALING' "
                    "AND coalesce(s.locks_at, s.trial_ends_at) <= now() RETURNING s.organization_id, p.name"
                )
            )
        ).all()
    n = len(rows)
    if n:
        log.info("locked %s expired trial(s)", n)
    for r in rows:  # once per organisation, however often this job runs
        await notify.notify_trial(
            r.organization_id,
            "trial.expired",
            {"plan_name": r.name},
            f"trial.expired:{r.organization_id}",
        )
    return n


async def send_trial_reminders() -> int:
    """Email the organisation's admins as a trial nears its end. The days come from ``billing.trial``
    (reminder_days_before). Only the tightest threshold already crossed is sent, once, so a late sign-up does not get
    several emails at the same moment and a missed run still sends the right one."""
    async with admin_session(
        actor_user_id=None, reason="trial reminders", action="system.trial_reminders"
    ) as db:
        subs = (
            await db.execute(
                text(
                    "SELECT s.organization_id, s.trial_ends_at, p.name FROM subscriptions s JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.status='TRIALING' AND s.trial_ends_at > now() AND s.trial_ends_at <= now() + interval '31 days'"
                )
            )
        ).all()
    sent = 0
    cfg = get_config()
    now = datetime.now(UTC)
    for s in subs:
        days = (
            await cfg.effective("billing.trial", org_id=s.organization_id)
        ).value.reminder_days_before
        remaining = s.trial_ends_at - now
        crossed = [d for d in days if remaining <= timedelta(days=d)]
        if not crossed:
            continue
        d = min(crossed)
        left = max(1, math.ceil(remaining / timedelta(days=1)))
        queued = await notify.emit(
            "trial.ending",
            org_id=s.organization_id,
            recipients=await notify.org_admin_emails(s.organization_id),
            variables={
                "days_left_text": f"{left} day{'s' if left != 1 else ''}",
                "ends_on": f"{s.trial_ends_at:%d %B %Y}".lstrip("0"),
                "plan_name": s.name,
            },
            dedupe_key=f"trial.ending:{d}",
        )
        sent += len(queued)
    return sent


async def purge_platform_sessions() -> int:
    """Delete Super Admin refresh rows a week past expiry. Audited like every cross-tenant action."""
    async with admin_session(
        actor_user_id=None,
        reason="purge expired platform sessions",
        action="system.purge_platform_sessions",
    ) as db:
        res = await db.execute(
            text("DELETE FROM platform_sessions WHERE expires_at < now() - interval '7 days'")
        )
        return res.rowcount or 0


@celery_app.task(name="billing.purge_platform_sessions")
def purge_platform_sessions_task() -> int:
    from .db import dispose_engines

    async def run() -> int:
        try:
            return await purge_platform_sessions()
        finally:
            await dispose_engines()

    return asyncio.run(run())


@celery_app.task(name="billing.trial_reminders")
def trial_reminders_task() -> int:
    from .db import dispose_engines

    async def run() -> int:
        try:
            return await send_trial_reminders()
        finally:
            await dispose_engines()

    return asyncio.run(run())


@celery_app.task(name="billing.expire_trials")
def expire_trials_task() -> int:
    from .db import dispose_engines

    async def run() -> int:
        try:
            return await expire_trials()
        finally:
            await dispose_engines()  # asyncio.run closes the loop; don't keep its connections

    return asyncio.run(run())


celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    "expire-trials-hourly": {"task": "billing.expire_trials", "schedule": 3600.0},
    "trial-reminders-hourly": {"task": "billing.trial_reminders", "schedule": 3600.0},
    "purge-platform-sessions": {"task": "billing.purge_platform_sessions", "schedule": 6 * 3600.0},
}
