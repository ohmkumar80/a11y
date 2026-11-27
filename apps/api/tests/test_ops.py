"""Operations overview: canaries, queue depths, incidents from live data, and runbooks."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from a11y_core import canaries

from a11y_api.routers.admin_ops import runbooks_dir

from .conftest import make_org, sql, super_admin_headers
from .test_billing import auth


@pytest.fixture(autouse=True)
async def _clean_canaries():
    async def wipe():
        r = canaries._redis()
        try:
            for k in await r.keys("canary:*"):
                await r.delete(k)
        finally:
            await r.aclose()

    await wipe()
    yield
    await wipe()


async def put_canary(name, ok=True, age=0, detail="fine"):
    r = canaries._redis()
    try:
        at = (datetime.now(UTC) - timedelta(seconds=age)).isoformat()
        await r.set(
            f"canary:{name}",
            json.dumps({"ok": ok, "at": at, "detail": detail, "duration_ms": 12}),
            ex=3600,
        )
    finally:
        await r.aclose()


async def counts(client):
    body = (await client.get("/admin/ops", headers=super_admin_headers())).json()
    return body, {i["key"]: i["count"] for i in body["incidents"]}


# -- access -----------------------------------------------------------------------------------------
async def test_only_platform_administrators_can_see_it(client):
    org, user, _ = await make_org()
    for url in ("/admin/ops", "/admin/ops/runbooks/stuck-scans"):
        assert (await client.get(url, headers=auth(org, user))).status_code == 403
        assert (await client.get(url)).status_code == 401


async def test_reading_it_is_audited(client):
    await client.get("/admin/ops", headers=super_admin_headers())
    assert (
        await sql(
            "SELECT count(*) AS n FROM audit_log WHERE action='admin.read' AND detail->>'reason'='operations overview'"
        )
    )[0]["n"] >= 1


# -- canaries ---------------------------------------------------------------------------------------
async def test_canary_states_are_ok_failing_stale_or_never():
    assert {c["state"] for c in await canaries.status()} == {"never"}
    await put_canary("web_scan", ok=True)
    await put_canary("docs_pdf", ok=False, detail="PDF/UA-1 failed: 7.1#3 x2")
    await put_canary(
        "email_smtp", ok=True, age=int(canaries.CANARIES["email_smtp"].interval * 2.6)
    )  # missed its schedule
    by = {c["key"]: c for c in await canaries.status()}
    assert (
        by["web_scan"]["state"] == "ok"
        and by["docs_pdf"]["state"] == "failing"
        and by["email_smtp"]["state"] == "stale"
    )
    assert by["docs_pdf"]["detail"].startswith("PDF/UA-1 failed")


async def test_running_a_check_records_success_or_failure_and_never_raises():
    async def good():
        return "all fine"

    async def bad():
        raise RuntimeError("the engines no longer find the planted problem")

    assert await canaries.run_timed("web_scan", good) is True
    assert await canaries.run_timed("docs_pdf", bad) is False
    by = {c["key"]: c for c in await canaries.status()}
    assert by["web_scan"]["state"] == "ok" and by["docs_pdf"]["state"] == "failing"
    assert (
        "planted problem" in by["docs_pdf"]["detail"] and by["web_scan"]["duration_ms"] is not None
    )


async def test_the_schedules_exist_and_docs_jobs_route_to_the_docs_queue():
    from a11y_core.celery_app import celery_app

    sched = {v["task"]: v["schedule"] for v in celery_app.conf.beat_schedule.values()}
    assert {"web.canary", "docs.canary", "canary.email"} <= set(sched)
    assert celery_app.conf.task_routes["docs.*"] == {"queue": "docs"}


async def test_the_overview_reports_canary_incidents(client):
    await put_canary("web_scan", ok=False, detail="RuntimeError: chromium crashed")
    await put_canary("docs_pdf", ok=True)
    await put_canary("email_smtp", ok=True, age=5000)
    body, c = await counts(client)
    by = {i["key"]: i for i in body["incidents"]}
    assert (
        by["canary_web_scan"]["severity"] == "critical"
        and by["canary_web_scan"]["runbook"] == "canary-web-scan"
    )
    assert "chromium crashed" in by["canary_web_scan"]["detail"]
    assert (
        by["canary_email_smtp"]["severity"] == "warning"
        and by["canary_email_smtp"]["runbook"] == "canary-email"
    )
    assert "canary_docs_pdf" not in by and body["status"] == "down"


# -- incidents from live data -----------------------------------------------------------------------
async def test_incidents_are_computed_from_the_data_and_ignore_customer_faults(client):
    _, before = await counts(client)
    org, user, email = await make_org(plan="GROWTH")

    def scan(status, code=None, heartbeat=None, created="now()", finished="now()"):
        return sql(
            "INSERT INTO scan_jobs (id, organization_id, created_by, start_url, mode, max_pages, standards, status, error_code, heartbeat_at, created_at, finished_at) "
            f"VALUES ($1,$2,$3,'http://127.0.0.1:1/','single',1,ARRAY['WCAG_2_2_AA'],$4,$5,$6,{created},{finished})",
            uuid.uuid4(),
            org,
            user,
            status,
            code,
            heartbeat,
        )

    await scan(
        "RUNNING", heartbeat=datetime.now(UTC) - timedelta(minutes=30), finished="NULL"
    )  # stuck
    await scan("FAILED", "system_error")  # ours
    await scan("FAILED", "worker_lost")
    await scan("FAILED", "dns_failed")  # the customer's: must not count
    await scan("FAILED", "http_404")  # the customer's
    await scan("FAILED", "system_error", finished="now() - interval '2 days'")  # too old
    await sql(
        "INSERT INTO notification_log (id, organization_id, event, to_email, status, dedupe_key) VALUES (gen_random_uuid(),$1,'quota.reached','a@example.com','FAILED','k1')",
        org,
    )
    await sql(
        "INSERT INTO notification_log (id, organization_id, event, to_email, status, dedupe_key, created_at) VALUES (gen_random_uuid(),$1,'quota.reached','b@example.com','QUEUED','k2', now() - interval '3 hours')",
        org,
    )
    await sql(
        "INSERT INTO notification_log (id, organization_id, event, to_email, status, dedupe_key) VALUES (gen_random_uuid(),$1,'quota.reached','c@example.com','SENT','k3')",
        org,
    )
    body, after = await counts(client)
    d = {k: after.get(k, 0) - before.get(k, 0) for k in after}
    assert d["stuck_scans"] == 1
    assert (
        d["failed_scans"] == 2
    )  # system_error + worker_lost, nothing for the customer's faults or the old one
    assert d["failed_emails"] == 1 and d["queued_emails"] == 1
    fs = next(i for i in body["incidents"] if i["key"] == "failed_scans")
    assert "system_error" in fs["detail"] and "dns_failed" not in fs["detail"]
    assert body["incidents"][0]["severity"] == "critical"  # worst first
    assert body["stats"]["scans_24h"] >= 5 and set(body["stats"]) >= {
        "emails_sent_24h",
        "ai_calls_24h",
        "webhooks_delivered_24h",
    }


async def test_webhook_fix_and_reservation_incidents(client):
    from a11y_core import billing
    from a11y_core.db import tenant_session

    _, before = await counts(client)
    org, user, email = await make_org(plan="GROWTH")
    ep = uuid.uuid4()
    await sql(
        "INSERT INTO webhook_endpoints (id, organization_id, url, events, secret_ct, secret_hint, enabled, consecutive_failures, created_by) VALUES ($1,$2,'https://x.example/h',ARRAY['scan.completed'],'ct','abcd',false,20,$3)",
        ep,
        org,
        user,
    )
    await sql(
        "INSERT INTO webhook_deliveries (id, organization_id, endpoint_id, event_id, event_type, payload, status) VALUES (gen_random_uuid(),$1,$2,gen_random_uuid(),'scan.completed','{}','ABANDONED')",
        org,
        ep,
    )
    sid = uuid.uuid4()
    async with tenant_session(org) as db:
        await billing.reserve(
            db, org, "urls_monthly", str(sid)
        )  # a credit whose scan never existed
    await sql(
        "UPDATE usage_reservations SET created_at = now() - interval '3 hours' WHERE job_id=$1",
        str(sid),
    )
    _, after = await counts(client)
    d = {k: after.get(k, 0) - before.get(k, 0) for k in after}
    assert (
        d["abandoned_webhooks"] == 1
        and d["disabled_webhooks"] == 1
        and d["orphaned_reservations"] == 1
    )


async def test_queue_depths_are_shown_and_a_backlog_is_an_incident(client, monkeypatch):
    from a11y_api.routers import admin_ops

    q = f"zz-test-{uuid.uuid4().hex[:8]}"  # a private queue: never push test jobs into one a real worker is reading
    monkeypatch.setattr(admin_ops, "QUEUES", ("system", "web", "docs", q))
    monkeypatch.setattr(admin_ops, "WATCHED", ("system", "web", "docs", q))
    r = canaries._redis()
    try:
        await r.rpush(q, *["x"] * 150)
        body = (await client.get("/admin/ops", headers=super_admin_headers())).json()
        assert body["queues"][q] == 150 and set(body["queues"]) >= {"system", "web", "docs"}
        by = {i["key"]: i for i in body["incidents"]}
        assert (
            by[f"backlog_{q}"]["count"] == 150 and by[f"backlog_{q}"]["runbook"] == "queue-backlog"
        )
    finally:
        await r.delete(q)
        await r.aclose()


async def test_health_is_reported(client):
    body = (await client.get("/admin/ops", headers=super_admin_headers())).json()
    assert body["health"] == {"postgres": "ok", "redis": "ok"} and body["status"] in (
        "ok",
        "degraded",
        "down",
    )


# -- runbooks ---------------------------------------------------------------------------------------
ALL_SLUGS = [
    "stuck-scans",
    "failed-scans",
    "report-failures",
    "email-failures",
    "webhook-failures",
    "fix-failures",
    "orphaned-reservations",
    "queue-backlog",
    "canary-web-scan",
    "canary-docs-pdf",
    "canary-email",
    "database-or-redis-down",
]


@pytest.mark.parametrize("slug", ALL_SLUGS)
async def test_every_runbook_exists_and_follows_the_format(client, slug):
    r = await client.get(f"/admin/ops/runbooks/{slug}", headers=super_admin_headers())
    assert r.status_code == 200 and r.json()["slug"] == slug
    md = r.json()["markdown"]
    for heading in ("## What it means", "## Check", "## Fix", "## Escalate"):
        assert heading in md, f"{slug} lacks {heading}"


async def test_every_incident_this_page_can_raise_points_at_a_real_runbook(client):
    src = (Path(__file__).resolve().parents[1] / "a11y_api/routers/admin_ops.py").read_text()
    import re

    slugs = set(re.findall(r'"([a-z]+(?:-[a-z]+)+)"\)', src)) | set(
        re.findall(r', "([a-z]+(?:-[a-z]+)+)"\),?\n', src)
    )
    for slug in ALL_SLUGS:
        assert (runbooks_dir() / f"{slug}.md").is_file()
    unknown = {
        s
        for s in slugs
        if s not in ALL_SLUGS
        and (runbooks_dir() / f"{s}.md").exists() is False
        and s.startswith(
            (
                "canary",
                "stuck",
                "failed",
                "report",
                "email",
                "webhook",
                "fix",
                "orphaned",
                "queue",
                "database",
            )
        )
    }
    assert not unknown


@pytest.mark.parametrize(
    "slug",
    [
        "../../etc/passwd",
        "..%2F..%2Fetc%2Fpasswd",
        "UPPER",
        "no-such-runbook",
        "a" * 80,
        "stuck_scans",
    ],
)
async def test_runbook_names_cannot_escape_the_folder(client, slug):
    r = await client.get(f"/admin/ops/runbooks/{slug}", headers=super_admin_headers())
    assert r.status_code in (404, 422)
    assert "root:" not in r.text


async def test_every_module_that_defines_tasks_is_loaded_by_the_workers():
    """A worker runs only the tasks of the modules in the include list. A module missing from it silently never runs its
    tasks or its schedule (found once by a live check: the mail canary), so every core module that defines a task must be
    listed. Checked on the SOURCE, because importing the module in a test would hide the mistake."""
    from pathlib import Path

    import a11y_core
    from a11y_core.celery_app import celery_app

    core = Path(a11y_core.__file__).parent
    defining = {
        f"a11y_core.{p.stem}"
        for p in core.glob("*.py")
        if "celery_app.task" in p.read_text() and p.stem != "celery_app"
    }
    assert {
        "a11y_core.canaries",
        "a11y_core.notify",
        "a11y_core.webhooks",
        "a11y_core.scan_jobs",
        "a11y_core.billing_jobs",
    } <= defining
    missing = defining - set(celery_app.conf.include)
    assert not missing, f"not loaded by any worker: {sorted(missing)}"


async def test_every_scheduled_task_exists():
    from a11y_core.celery_app import celery_app

    celery_app.loader.import_default_modules()
    owned_elsewhere = {"web.canary", "docs.canary"}  # these live in the web and docs worker images
    for name, entry in celery_app.conf.beat_schedule.items():
        assert entry["task"] in celery_app.tasks or entry["task"] in owned_elsewhere, (
            f"{name} schedules {entry['task']}"
        )
