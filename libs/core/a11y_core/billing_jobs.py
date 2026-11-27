"""Scheduled billing work. Runs as a system job, so it uses the audited cross-tenant session."""

import asyncio
import logging

from sqlalchemy import text

from .celery_app import celery_app
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
        res = await db.execute(
            text(
                "UPDATE subscriptions SET status='LOCKED_READ_ONLY', updated_at=now() "
                "WHERE status='TRIALING' AND coalesce(locks_at, trial_ends_at) <= now()"
            )
        )
        n = res.rowcount or 0
    if n:
        log.info("locked %s expired trial(s)", n)
    return n


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
}
