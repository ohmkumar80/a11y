"""Super Admin: a read-only operations overview (PROJECT_PLAN 3.15). It shows whether the platform is healthy, how deep the
queues are, what the synthetic canaries last found, and a short list of INCIDENTS computed from live data, each linked to
a runbook. It changes nothing; every read is audit-logged like any cross-tenant read."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path

from a11y_core import canaries
from a11y_core.db import admin_session, app_engine
from a11y_core.scan_jobs import is_customer_fault
from a11y_core.settings import get_settings
from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import text

from ..deps import require_super_admin
from ..security import Principal

router = APIRouter(prefix="/admin/ops", tags=["admin"])
QUEUES = ("system", "web", "docs", "media", "mobile", "ai")
WATCHED = (
    "system",
    "web",
    "docs",
)  # queues whose depth raises an incident (the others are not used yet)
BACKLOG = 100  # waiting jobs in one queue that count as a backlog
SLUG = re.compile(r"^[a-z0-9-]{1,60}$")


def runbooks_dir() -> Path:
    if env := os.environ.get("A11Y_RUNBOOKS_DIR"):
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        if (parent / "docs" / "runbooks").is_dir():
            return parent / "docs" / "runbooks"
    return Path("/app/docs/runbooks")


def _incident(key: str, severity: str, title: str, count: int, detail: str, runbook: str) -> dict:
    return {
        "key": key,
        "severity": severity,
        "title": title,
        "count": count,
        "detail": detail,
        "runbook": runbook,
    }


async def _health() -> dict[str, str]:
    out = {}
    try:
        async with app_engine().connect() as c:
            await c.execute(text("SELECT 1"))
        out["postgres"] = "ok"
    except Exception:  # noqa: BLE001
        out["postgres"] = "down"
    try:
        r = Redis.from_url(get_settings().redis_url)
        await r.ping()
        await r.aclose()
        out["redis"] = "ok"
    except Exception:  # noqa: BLE001
        out["redis"] = "down"
    return out


async def _queue_depths() -> dict[str, int | None]:
    r = Redis.from_url(get_settings().redis_url)
    try:
        return {q: int(await r.llen(q)) for q in QUEUES}
    except Exception:  # noqa: BLE001
        return dict.fromkeys(QUEUES)
    finally:
        await r.aclose()


@router.get("")
async def overview(p: Principal = Depends(require_super_admin)):
    health = await _health()
    queues = await _queue_depths()
    cans = await canaries.status()
    incidents: list[dict] = []

    if health["postgres"] != "ok" or health["redis"] != "ok":
        down = ", ".join(k for k, v in health.items() if v != "ok")
        incidents.append(
            _incident(
                "platform_down",
                "critical",
                "A core service is down",
                1,
                f"Not reachable: {down}.",
                "database-or-redis-down",
            )
        )
    for q, depth in queues.items():
        if depth is not None and depth > BACKLOG and q in WATCHED:
            incidents.append(
                _incident(
                    f"backlog_{q}",
                    "warning",
                    f"The {q} queue is backing up",
                    depth,
                    f"{depth} jobs are waiting.",
                    "queue-backlog",
                )
            )
    for c in cans:
        slug = {
            "web_scan": "canary-web-scan",
            "docs_pdf": "canary-docs-pdf",
            "email_smtp": "canary-email",
        }[c["key"]]
        if c["state"] == "failing":
            incidents.append(
                _incident(
                    f"canary_{c['key']}",
                    "critical",
                    f"Canary failing: {c['label']}",
                    1,
                    c["detail"],
                    slug,
                )
            )
        elif c["state"] == "stale":
            incidents.append(
                _incident(
                    f"canary_{c['key']}",
                    "warning",
                    f"Canary has stopped reporting: {c['label']}",
                    1,
                    f"Last reported {c['at']}.",
                    slug,
                )
            )

    stats: dict[str, int] = {}
    if health["postgres"] == "ok":
        async with admin_session(
            actor_user_id=p.user_id, reason="operations overview", action="admin.read"
        ) as db:
            one = lambda sql, **kw: db.execute(text(sql), kw)  # noqa: E731
            stuck = (
                await one(
                    "SELECT count(*) FROM scan_jobs WHERE (status='RUNNING' AND coalesce(heartbeat_at, started_at) < now() - interval '10 minutes') "
                    "OR (status='QUEUED' AND created_at < now() - interval '45 minutes')"
                )
            ).scalar_one()
            if stuck:
                incidents.append(
                    _incident(
                        "stuck_scans",
                        "critical",
                        "Scans are stuck",
                        stuck,
                        "The stuck-scan sweeper should have failed these.",
                        "stuck-scans",
                    )
                )

            failed = (
                await one(
                    "SELECT error_code, count(*) AS n FROM scan_jobs WHERE status='FAILED' AND finished_at > now() - interval '24 hours' GROUP BY error_code"
                )
            ).all()
            ours = {r.error_code: r.n for r in failed if not is_customer_fault(r.error_code)}
            if ours:
                incidents.append(
                    _incident(
                        "failed_scans",
                        "warning",
                        "Scans failed for platform reasons (24 hours)",
                        sum(ours.values()),
                        ", ".join(f"{k}: {v}" for k, v in sorted(ours.items())),
                        "failed-scans",
                    )
                )

            for key, sev, title, sql, slug in (
                (
                    "failed_reports",
                    "warning",
                    "Reports failed (24 hours)",
                    "SELECT count(*) FROM reports WHERE status='FAILED' AND finished_at > now() - interval '24 hours'",
                    "report-failures",
                ),
                (
                    "failed_emails",
                    "warning",
                    "Emails could not be delivered (24 hours)",
                    "SELECT count(*) FROM notification_log WHERE status='FAILED' AND created_at > now() - interval '24 hours'",
                    "email-failures",
                ),
                (
                    "queued_emails",
                    "warning",
                    "Emails waiting more than an hour",
                    "SELECT count(*) FROM notification_log WHERE status='QUEUED' AND created_at < now() - interval '1 hour'",
                    "email-failures",
                ),
                (
                    "abandoned_webhooks",
                    "info",
                    "Webhook deliveries given up on (24 hours)",
                    "SELECT count(*) FROM webhook_deliveries WHERE status='ABANDONED' AND created_at > now() - interval '24 hours'",
                    "webhook-failures",
                ),
                (
                    "disabled_webhooks",
                    "info",
                    "Webhooks switched off after repeated failures",
                    "SELECT count(*) FROM webhook_endpoints WHERE NOT enabled AND consecutive_failures > 0",
                    "webhook-failures",
                ),
                (
                    "failed_fixes",
                    "warning",
                    "Code-fix suggestions failed (24 hours)",
                    "SELECT count(*) FROM fix_suggestions WHERE status='FAILED' AND finished_at > now() - interval '24 hours'",
                    "fix-failures",
                ),
                (
                    "orphaned_reservations",
                    "warning",
                    "Credits left reserved after their scan ended",
                    "SELECT count(*) FROM usage_reservations r LEFT JOIN scan_jobs s ON s.id::text = r.job_id WHERE r.status='RESERVED' AND r.feature_key='urls_monthly' "
                    "AND r.created_at < now() - interval '2 hours' AND (s.id IS NULL OR s.status IN ('SUCCEEDED','FAILED','CANCELLED'))",
                    "orphaned-reservations",
                ),
            ):
                n = (await one(sql)).scalar_one()
                if n:
                    incidents.append(_incident(key, sev, title, n, "", slug))

            for name, sql in (
                (
                    "scans_24h",
                    "SELECT count(*) FROM scan_jobs WHERE created_at > now() - interval '24 hours'",
                ),
                (
                    "scans_succeeded_24h",
                    "SELECT count(*) FROM scan_jobs WHERE status='SUCCEEDED' AND finished_at > now() - interval '24 hours'",
                ),
                (
                    "reports_ready_24h",
                    "SELECT count(*) FROM reports WHERE status='READY' AND finished_at > now() - interval '24 hours'",
                ),
                (
                    "emails_sent_24h",
                    "SELECT count(*) FROM notification_log WHERE status='SENT' AND sent_at > now() - interval '24 hours'",
                ),
                (
                    "webhooks_delivered_24h",
                    "SELECT count(*) FROM webhook_deliveries WHERE status='SENT' AND delivered_at > now() - interval '24 hours'",
                ),
                (
                    "ai_calls_24h",
                    "SELECT count(*) FROM ai_usage WHERE created_at > now() - interval '24 hours'",
                ),
            ):
                stats[name] = (await one(sql)).scalar_one()

    order = {"critical": 0, "warning": 1, "info": 2}
    incidents.sort(key=lambda i: (order[i["severity"]], i["key"]))
    return {
        "generated_at": datetime.now(UTC),
        "status": "down"
        if any(i["severity"] == "critical" for i in incidents)
        else "degraded"
        if any(i["severity"] == "warning" for i in incidents)
        else "ok",
        "health": health,
        "queues": queues,
        "canaries": cans,
        "incidents": incidents,
        "stats": stats,
    }


@router.get("/runbooks/{slug}")
async def runbook(slug: str, _: Principal = Depends(require_super_admin)):
    """The text of one runbook. Only files that exist in the runbooks folder, by a plain name: never a path."""
    f = runbooks_dir() / f"{slug}.md"
    if not SLUG.match(slug) or not f.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no such runbook.")
    return {"slug": slug, "markdown": f.read_text()}
