"""The ``web.scan`` Celery task: runs one scan end to end.

State machine: QUEUED -> RUNNING -> SUCCEEDED | FAILED. Properties (PROJECT_PLAN 3.15, layer 0):
* idempotent: a redelivered task on a finished scan does nothing; on a half-done scan it restarts
  cleanly (partial pages/findings are discarded first), so credits are never double-charged;
* heartbeat after every page, so the sweeper can tell a dead worker from a slow site;
* credit rule (PROJECT_PLAN 3.5): customer faults (bad URL, blocked, unreachable site) keep the
  credit, platform faults (browser/engine/worker failure) give it back;
* the engine versions, rule-registry version and config versions are recorded on the scan.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from a11y_core import billing, notify
from a11y_core.celery_app import celery_app
from a11y_core.config import definitions as _definitions  # noqa: F401
from a11y_core.config import get_config
from a11y_core.db import dispose_engines, tenant_session
from a11y_core.models import PageScreenshot, ScanFinding, ScanPage
from a11y_core.rules import get_registry
from a11y_core.scan_jobs import USAGE_FEATURE, fail_scan, is_customer_fault
from sqlalchemy import func, text

from .engines import load_bundles
from .scanner import PageResult, ScanOptions, scan_site

log = logging.getLogger(__name__)
MAX_SHOT_BYTES = (
    1_500_000  # below the table's 2 MB limit; a bigger image is dropped, the scan still succeeds
)
_is_customer_fault = is_customer_fault  # the rule lives in a11y_core so the sweeper can share it


async def run_scan(
    org_id: uuid.UUID, scan_id: uuid.UUID, *, opts_override: ScanOptions | None = None
) -> str:
    """Returns the final status. Never raises for scan-level problems."""
    async with tenant_session(org_id) as db:
        job = (
            await db.execute(
                text(
                    "SELECT status, start_url, max_pages, attempts FROM scan_jobs WHERE id=:i FOR UPDATE"
                ),
                {"i": scan_id},
            )
        ).first()
        if job is None:
            return "MISSING"
        if job.status in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return job.status  # redelivery after completion: nothing to do
        sub = await billing.load_subscription(db)
        plan_id = sub.plan_id
        if job.status == "RUNNING":  # redelivered mid-run: start over from a clean slate
            await db.execute(text("DELETE FROM scan_findings WHERE scan_id=:i"), {"i": scan_id})
            await db.execute(text("DELETE FROM scan_pages WHERE scan_id=:i"), {"i": scan_id})
        await db.execute(
            text(
                "UPDATE scan_jobs SET status='RUNNING', started_at=now(), heartbeat_at=now(), attempts=attempts+1, pages_scanned=0, findings_count=0 WHERE id=:i"
            ),
            {"i": scan_id},
        )
    cfg = get_config()
    eff = await cfg.effective("scan.engines", org_id=org_id, plan_id=plan_id)
    s = eff.value
    reg = get_registry()
    versions = load_bundles()[1]
    opts = opts_override or ScanOptions(
        engines=s.enabled(),
        page_timeout_s=s.page_timeout_seconds,
        politeness_delay_ms=s.politeness_delay_ms,
        respect_robots=s.respect_robots,
        screenshot=s.screenshots and s.screenshot_pages > 0,
        screenshot_quality=s.screenshot_quality,
        screenshot_max_height=s.screenshot_max_height,
    )
    async with tenant_session(org_id) as db:
        await db.execute(
            text(
                "UPDATE scan_jobs SET engine_versions=CAST(:v AS jsonb), rules_version=:r, config_refs=CAST(:c AS jsonb) WHERE id=:i"
            ),
            {
                "v": json.dumps(versions),
                "r": reg.standards_version,
                "c": json.dumps([eff.ref]),
                "i": scan_id,
            },
        )

    totals = {"pages": 0, "findings": 0, "shots": 0}
    first: list[PageResult] = []

    async def on_page(r: PageResult) -> None:
        if not first:
            first.append(r)
        async with tenant_session(org_id) as db:
            page = ScanPage(
                organization_id=org_id,
                scan_id=scan_id,
                url=r.url,
                final_url=r.final_url,
                status=r.status,
                error_code=r.error_code,
                error_detail=r.error_detail,
                http_status=r.http_status,
                title=r.title,
                lang=r.lang,
                engines=r.engines,
                duration_ms=r.duration_ms,
            )
            db.add(page)
            await db.flush()
            db.add_all(
                ScanFinding(
                    organization_id=org_id,
                    scan_id=scan_id,
                    page_id=page.id,
                    canonical_rule_id=f.canonical_rule_id,
                    title=f.title,
                    sc=f.sc,
                    kind=f.kind,
                    severity=f.severity,
                    confidence=f.confidence,
                    engines=f.engines,
                    covering=f.covering,
                    engine_rule_ids=f.engine_rule_ids,
                    xpath=f.xpath,
                    css=f.css,
                    tag=f.tag,
                    html=f.html,
                    message=f.message,
                    rect=f.rect,
                    cluster_key=f.cluster_key,
                    fingerprint=f.fingerprint,
                    help_url=f.help_url,
                    mapped=f.mapped,
                )
                for f in r.findings
            )
            if (
                r.screenshot
                and r.screenshot_meta
                and totals["shots"] < s.screenshot_pages
                and len(r.screenshot) <= MAX_SHOT_BYTES
            ):
                m = r.screenshot_meta
                db.add(
                    PageScreenshot(
                        organization_id=org_id,
                        scan_id=scan_id,
                        page_id=page.id,
                        content=r.screenshot,
                        width=m["width"],
                        height=m["height"],
                        page_height=m["page_height"],
                        truncated=m["truncated"],
                        size_bytes=len(r.screenshot),
                    )
                )
                totals["shots"] += 1
            if r.status == "OK":
                totals["pages"] += 1
                totals["findings"] += len(r.findings)
            await db.execute(
                text(
                    "UPDATE scan_jobs SET heartbeat_at=now(), pages_scanned=:p, findings_count=:f WHERE id=:i"
                ),
                {"p": totals["pages"], "f": totals["findings"], "i": scan_id},
            )

    try:
        await scan_site(job.start_url, max_pages=job.max_pages, opts=opts, on_page=on_page)
    except Exception as e:  # noqa: BLE001 - anything unexpected is OUR fault: fail cleanly, give the credit back
        log.exception("scan %s crashed", scan_id)
        await fail_scan(
            org_id,
            scan_id,
            "system_error",
            "Something went wrong on our side. Your credit was returned. Please try again.",
            system_fault=True,
        )
        return "FAILED" if not isinstance(e, asyncio.CancelledError) else "CANCELLED"

    start = first[0] if first else None
    if start is None or start.status != "OK":
        code = start.error_code if start else "no_result"
        detail = (start.error_detail if start else None) or "The scan produced no result."
        await fail_scan(
            org_id,
            scan_id,
            code or "scan_failed",
            detail,
            system_fault=not _is_customer_fault(code),
        )
        return "FAILED"
    async with tenant_session(org_id) as db:
        await db.execute(
            text(
                "UPDATE scan_jobs SET status='SUCCEEDED', finished_at=now() WHERE id=:i AND status='RUNNING'"
            ),
            {"i": scan_id},
        )
        await billing.commit_usage(db, USAGE_FEATURE, str(scan_id))
    await notify.notify_scan_done(org_id, scan_id)
    return "SUCCEEDED"


@celery_app.task(name="web.scan", acks_late=True, max_retries=0)
def scan_task(org_id: str, scan_id: str) -> str:
    async def run() -> str:
        try:
            return await run_scan(uuid.UUID(org_id), uuid.UUID(scan_id))
        finally:
            await dispose_engines()  # asyncio.run closes the loop; drop its connections

    return asyncio.run(run())


# -- AI code-fix suggestion (PROJECT_PLAN 3.13) ----------------------------------------------------
FIX_FAILED = "We could not check a fix right now. Please try again in a few minutes."


async def run_fix(org_id: uuid.UUID, fix_id: uuid.UUID) -> str:
    """Resolve one fix suggestion: recipe, then model, each judged by the re-scan oracle. Idempotent: a finished
    suggestion is never recomputed, so a redelivered task cannot change what the person already saw."""
    from a11y_core.ai import LLMRequest, get_gateway
    from a11y_core.models import FixSuggestion
    from playwright.async_api import async_playwright
    from sqlalchemy import select, update

    from .fixes.ladder import suggest

    async with tenant_session(org_id) as db:
        row = (
            await db.execute(select(FixSuggestion).where(FixSuggestion.id == fix_id))
        ).scalar_one_or_none()
        if row is None or row.status not in ("PENDING", "RUNNING"):
            return row.status if row else "MISSING"
        f = (
            await db.execute(
                text("SELECT title, sc, message FROM scan_findings WHERE id=:i"),
                {"i": row.finding_id},
            )
        ).first()
        sub = await billing.load_subscription(db)
        await db.execute(
            update(FixSuggestion).where(FixSuggestion.id == fix_id).values(status="RUNNING")
        )
        rule, original = row.rule, row.original_html

    gw = get_gateway()
    policy = (await get_config().effective("ai.code_fix", org_id=org_id, plan_id=sub.plan_id)).value

    async def complete(messages):
        return await gw.complete(
            LLMRequest(
                task="code_fix",
                messages=messages,
                org_id=org_id,
                job_id=str(fix_id),
                plan_id=sub.plan_id,
                json_mode=True,
            )
        )

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(chromium_sandbox=False)
            try:
                out = await suggest(
                    browser,
                    rule=rule,
                    title=f.title if f else rule,
                    criteria=list(f.sc) if f else [],
                    message=f.message if f else "",
                    original_html=original,
                    complete=complete if policy.use_ai else None,
                )
            finally:
                await browser.close()
    except Exception:  # noqa: BLE001 - a platform fault: say so plainly, keep the detail in our logs
        log.exception("fix %s failed", fix_id)
        async with tenant_session(org_id) as db:
            await db.execute(
                update(FixSuggestion)
                .where(FixSuggestion.id == fix_id)
                .values(status="FAILED", error_detail=FIX_FAILED, finished_at=func.now())
            )
        return "FAILED"

    from .fixes.ladder import REASONS

    async with tenant_session(org_id) as db:
        await db.execute(
            update(FixSuggestion)
            .where(FixSuggestion.id == fix_id)
            .values(
                status=out.status,
                rung=out.rung,
                fixed_html=out.fixed_html,
                explanation=out.explanation,
                notes=out.notes,
                checks=out.checks,
                reason=out.reason,
                model_id=out.model_id,
                attempts=out.attempts,
                error_detail=REASONS.get(out.reason or "") if out.status != "READY" else None,
                finished_at=func.now(),
            )
        )
    return out.status


@celery_app.task(name="web.suggest_fix", acks_late=True, max_retries=0)
def suggest_fix_task(org_id: str, fix_id: str) -> str:
    async def run() -> str:
        try:
            return await run_fix(uuid.UUID(org_id), uuid.UUID(fix_id))
        finally:
            await dispose_engines()

    return asyncio.run(run())
