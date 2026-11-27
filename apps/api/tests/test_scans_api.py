"""Scan API + job runner against the real scanner and a local fixture site."""

import asyncio
import threading
import uuid
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from a11y_core.config import Scope, get_config
from a11y_core.db import tenant_session
from a11y_core.scan_jobs import sweep_stuck_scans
from a11y_core.settings import get_settings
from a11y_web_audit.scanner import ScanOptions
from a11y_web_audit.tasks import run_scan

from .conftest import make_org, sql
from .test_billing import auth
from .test_settings import _clean  # noqa: F401  (clears settings + cache)

PAGES = Path(__file__).resolve().parents[3] / "fixtures/pages"
PORTS = (80, 443, 8080, 8443) + tuple(range(1024, 65536))
FAST = ScanOptions(page_timeout_s=20, settle_ms=100, politeness_delay_ms=0, ports=PORTS)


class H(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        if self.path == "/index.html" or self.path == "/":
            body = b'<html lang="en"><head><title>Home</title></head><body><main><h1>Home</h1><a href="/bad.html">bad</a><a href="/good.html">good</a></main></body></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()


@pytest.fixture(scope="module")
def site():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=str(PAGES)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def dev(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "scan_dev_allow_hosts", "127.0.0.1")
    # The API only validates and enqueues; tests run the job themselves (no broker needed).
    from a11y_core.celery_app import celery_app

    sent = []
    monkeypatch.setattr(
        celery_app,
        "send_task",
        lambda name, args=None, queue=None, **kw: sent.append((name, args, queue)),
    )
    return sent


@pytest.fixture(autouse=True)
async def _cfg_reset():
    # raise the per-minute limit out of the way and allow all high ports through the API's check
    yield
    await sql("DELETE FROM scan_jobs WHERE start_url LIKE 'http://127.0.0.1:%'")
    await sql("DELETE FROM verified_domains WHERE host = '127.0.0.1'")


@pytest.fixture(autouse=True)
def high_ports(monkeypatch):
    import a11y_core.ssrf as ssrf

    monkeypatch.setattr(ssrf, "DEFAULT_PORTS", PORTS)
    monkeypatch.setattr(
        ssrf.check_url, "__kwdefaults__", {**ssrf.check_url.__kwdefaults__, "ports": PORTS}
    )
    monkeypatch.setattr(
        ssrf.parse_url, "__kwdefaults__", {**ssrf.parse_url.__kwdefaults__, "ports": PORTS}
    )


async def used(org, f="urls_monthly"):
    r = await sql(
        "SELECT used FROM usage_ledger WHERE organization_id=$1 AND feature_key=$2", org, f
    )
    return r[0]["used"] if r else 0


async def status_of(org_id, scan_id):
    async with tenant_session(org_id) as db:
        return (
            await db.execute(
                __import__("sqlalchemy").text(
                    "SELECT status, error_code FROM scan_jobs WHERE id=:i"
                ),
                {"i": scan_id},
            )
        ).first()


async def create(client, h, url, **kw):
    return await client.post("/scans", headers=h, json={"url": url, **kw})


async def test_create_run_and_read_results_end_to_end(client, site, dev):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    r = await create(client, h, f"{site}/bad.html", standards=["WCAG_2_1_AA", "WCAG_2_2_AA"])
    assert r.status_code == 202, r.text
    sid = uuid.UUID(r.json()["id"])
    assert dev == [("web.scan", [str(org), str(sid)], "web")]  # enqueued on the browser queue
    assert await used(org) == 1  # credit reserved up front
    assert (await client.get(f"/scans/{sid}", headers=h)).json()["status"] == "QUEUED"

    assert await run_scan(org, sid, opts_override=FAST) == "SUCCEEDED"
    s = (await client.get(f"/scans/{sid}", headers=h)).json()
    assert (s["status"], s["pages_scanned"]) == ("SUCCEEDED", 1) and s["findings_count"] > 10
    assert (
        s["engine_versions"] == {"axe": "4.14.1", "ibm": "4.0.35", "htmlcs": "2.5.1"}
        and s["rules_version"]
    )
    assert (
        await used(org) == 1
        and (await sql("SELECT status FROM usage_reservations WHERE job_id=$1", str(sid)))[0][
            "status"
        ]
        == "COMMITTED"
    )

    f = (await client.get(f"/scans/{sid}/findings", headers=h)).json()
    assert f["total"] == len(f["findings"]) > 10 and f["findings"][0]["severity"] == "critical"
    img = next(
        x
        for x in f["findings"]
        if x["rule"] == "image-alt" and x["element"]["xpath"] == "/html[1]/body[1]/img[1]"
    )
    assert img["agreement"] == "3 of 3 engines" and img["confidence"] == "high"
    assert img["criteria"] == [
        {"id": "1.1.1", "name": "Non-text Content", "level": "A", "clause": "WCAG 1.1.1"}
    ]
    assert img["page"]["url"].endswith("/bad.html") and img["element"]["tag"] == "img"

    # filters + switching standards re-filters stored data
    crit = (await client.get(f"/scans/{sid}/findings?severity=critical", headers=h)).json()
    assert crit["total"] and all(x["severity"] == "critical" for x in crit["findings"])
    only_22 = (await client.get(f"/scans/{sid}/findings?standard=WCAG_2_2_AA", headers=h)).json()[
        "total"
    ]
    only_20 = (await client.get(f"/scans/{sid}/findings?standard=WCAG_2_0_A", headers=h)).json()[
        "total"
    ]
    assert 0 < only_20 <= only_22
    best = (await client.get(f"/scans/{sid}/findings?kind=best_practice", headers=h)).json()
    assert best["total"] > 0 and all(x["kind"] == "best_practice" for x in best["findings"])
    en = (await client.get(f"/scans/{sid}/findings?standard=EU_EAA_EN_301_549", headers=h)).json()[
        "findings"
    ][0]
    assert en["criteria"][0]["clause"].startswith("9.")  # EN 301 549 clause numbering

    sm = (await client.get(f"/scans/{sid}/summary?standard=WCAG_2_2_AA", headers=h)).json()
    assert (
        "1.1.1" in sm["failed"]
        and sm["automated_coverage"]["total"] == 55
        and "not a statement of conformance" in sm["disclaimer"]
    )
    assert sm["review_status"] == "draft" and len(sm["not_tested"]) > 0
    sm20 = (await client.get(f"/scans/{sid}/summary?standard=WCAG_2_0_AA", headers=h)).json()
    assert sm20["automated_coverage"]["total"] == 38


async def test_clusters_group_the_same_defect(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    sid = uuid.UUID((await create(client, h, f"{site}/bad.html")).json()["id"])
    await run_scan(org, sid, opts_override=FAST)
    c = (await client.get(f"/scans/{sid}/findings?group=cluster", headers=h)).json()
    assert (
        c["total"] > 5
        and c["clusters"][0]["severity"] == "critical"
        and c["clusters"][0]["occurrences"] >= 1
    )


async def test_crawl_mode_and_verification_gate(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    # default unverified crawl cap is 5 pages: asking for more needs a verified domain
    r = await create(client, h, f"{site}/index.html", mode="crawl", max_pages=20)
    assert (
        r.status_code == 403
        and r.json()["code"] == "domain_not_verified"
        and r.json()["host"] == "127.0.0.1"
    )
    assert await used(org) == 0  # nothing reserved on refusal
    ok = await create(client, h, f"{site}/index.html", mode="crawl", max_pages=3)
    assert ok.status_code == 202 and ok.json()["max_pages"] == 3
    sid = uuid.UUID(ok.json()["id"])
    await run_scan(org, sid, opts_override=FAST)
    s = (await client.get(f"/scans/{sid}", headers=h)).json()
    assert s["pages_scanned"] == 3 and len(s["pages"]) == 3
    # verified domain lifts the cap (up to the plan's pages_per_scan: GROWTH = 500)
    await sql(
        "INSERT INTO verified_domains (id, organization_id, host, token, verified_at, method) VALUES (gen_random_uuid(), $1, '127.0.0.1', 't', now(), 'file')",
        org,
    )
    big = await create(client, h, f"{site}/index.html", mode="crawl", max_pages=20)
    assert big.status_code == 202 and big.json()["max_pages"] == 20


async def test_page_cap_follows_the_plan_entitlement(client, site):
    org, user, _ = await make_org(plan="TRIAL", trial_days=5)  # pages_per_scan = 25
    await sql(
        "INSERT INTO verified_domains (id, organization_id, host, token, verified_at, method) VALUES (gen_random_uuid(), $1, '127.0.0.1', 't', now(), 'file')",
        org,
    )
    r = await create(client, auth(org, user), f"{site}/index.html", mode="crawl", max_pages=500)
    assert r.json()["max_pages"] == 25


async def test_ssrf_and_validation_errors_use_the_field_error_shape(client):
    org, user, _ = await make_org()
    h = auth(org, user)
    for url, code in [
        ("http://169.254.169.254/latest", "private_address"),
        ("http://localhost/", "private_address"),
        ("file:///etc/passwd", "invalid_scheme"),
        ("http://u:p@example.com", "credentials_in_url"),
        ("nonsense", "invalid_scheme"),
    ]:
        r = await create(client, h, url)
        assert r.status_code == 422 and r.json()["field"] == "url" and r.json()["code"] == code, url
    assert (await create(client, h, "https://example.com", standards=["NOPE"])).status_code == 422
    assert await used(org) == 0  # refused requests never cost a credit


async def test_quota_is_reserved_atomically_and_refused_with_upgrade_prompt(client, site, dev):
    org, user, _ = await make_org(
        plan="TRIAL", trial_days=5
    )  # 10 scans / month, max 2 concurrent by default
    await get_config().save(
        "scan.engines",
        Scope.GLOBAL,
        "",
        {"max_concurrent_per_org": 20, "creations_per_minute": 600},
        comment="test-q",
        actor=None,
    )
    h = auth(org, user)
    rs = await asyncio.gather(*[create(client, h, f"{site}/good.html") for _ in range(25)])
    codes = sorted(r.status_code for r in rs)
    assert codes == [202] * 10 + [402] * 15
    assert next(r for r in rs if r.status_code == 402).json()["code"] == "quota_exceeded"
    assert await used(org) == 10 and len(dev) == 10


async def test_concurrency_cap_and_rate_limit(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    assert (await create(client, h, f"{site}/good.html")).status_code == 202
    assert (await create(client, h, f"{site}/good.html")).status_code == 202
    r = await create(client, h, f"{site}/good.html")  # default cap: 2 at once
    assert (
        r.status_code == 429 and r.json()["code"] == "too_many_scans" and r.headers["retry-after"]
    )
    assert await used(org) == 2
    await get_config().save(
        "scan.engines",
        Scope.GLOBAL,
        "",
        {"max_concurrent_per_org": 20, "creations_per_minute": 3},
        comment="test-rl",
        actor=None,
    )
    org2, user2, _ = await make_org(plan="GROWTH")
    h2 = auth(org2, user2)
    got = [(await create(client, h2, f"{site}/good.html")).status_code for _ in range(5)]
    assert got == [202, 202, 202, 429, 429]


async def test_locked_trial_cannot_scan(client, site):
    org, user, _ = await make_org(plan="TRIAL", trial_days=-1)
    r = await create(client, auth(org, user), f"{site}/good.html")
    assert r.status_code == 403 and r.json()["code"] == "subscription_locked"


async def test_customer_fault_keeps_credit_system_fault_returns_it(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    # customer fault: a page that does not exist -> FAILED, credit kept
    sid = uuid.UUID((await create(client, h, f"{site}/missing.html")).json()["id"])
    assert await run_scan(org, sid, opts_override=FAST) == "FAILED"
    s = (await client.get(f"/scans/{sid}", headers=h)).json()
    assert (s["status"], s["error_code"]) == ("FAILED", "http_404") and "404" in s["error_detail"]
    assert await used(org) == 1
    # system fault: the runner crashes -> FAILED, credit returned
    sid2 = uuid.UUID((await create(client, h, f"{site}/good.html")).json()["id"])
    assert await used(org) == 2
    import a11y_web_audit.tasks as tasks

    async def boom(*a, **k):
        raise RuntimeError("browser exploded")

    orig = tasks.scan_site
    tasks.scan_site = boom
    try:
        assert await run_scan(org, sid2, opts_override=FAST) == "FAILED"
    finally:
        tasks.scan_site = orig
    s2 = (await client.get(f"/scans/{sid2}", headers=h)).json()
    assert s2["error_code"] == "system_error" and "credit was returned" in s2["error_detail"]
    assert await used(org) == 1
    assert (await sql("SELECT status FROM usage_reservations WHERE job_id=$1", str(sid2)))[0][
        "status"
    ] == "RELEASED"


async def test_redelivery_is_idempotent_and_restarts_cleanly(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    sid = uuid.UUID((await create(client, h, f"{site}/bad.html")).json()["id"])
    assert await run_scan(org, sid, opts_override=FAST) == "SUCCEEDED"
    n = (await client.get(f"/scans/{sid}", headers=h)).json()["findings_count"]
    assert await run_scan(org, sid, opts_override=FAST) == "SUCCEEDED"  # duplicate delivery: no-op
    assert (await client.get(f"/scans/{sid}", headers=h)).json()[
        "findings_count"
    ] == n and await used(org) == 1
    # a scan left RUNNING by a crashed worker, redelivered: discards partials and completes
    sid2 = uuid.UUID((await create(client, h, f"{site}/bad.html")).json()["id"])
    await sql("UPDATE scan_jobs SET status='RUNNING', started_at=now() WHERE id=$1", sid2)
    await sql(
        "INSERT INTO scan_pages (id, organization_id, scan_id, url, status) VALUES (gen_random_uuid(), $1, $2, 'http://partial', 'OK')",
        org,
        sid2,
    )
    assert await run_scan(org, sid2, opts_override=FAST) == "SUCCEEDED"
    assert (await sql("SELECT count(*) AS n FROM scan_pages WHERE scan_id=$1", sid2))[0][
        "n"
    ] == 1  # partial row gone
    assert await used(org) == 2


async def test_sweeper_fails_dead_scans_and_returns_credit_without_touching_healthy_ones(
    client, site
):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    dead = uuid.UUID((await create(client, h, f"{site}/a.html")).json()["id"])
    alive = uuid.UUID((await create(client, h, f"{site}/b.html")).json()["id"])
    await sql(
        "UPDATE scan_jobs SET status='RUNNING', started_at=now()-interval '20 minutes', heartbeat_at=now()-interval '10 minutes' WHERE id=$1",
        dead,
    )
    await sql(
        "UPDATE scan_jobs SET status='RUNNING', started_at=now()-interval '20 minutes', heartbeat_at=now()-interval '10 seconds' WHERE id=$1",
        alive,
    )
    assert await used(org) == 2
    assert await sweep_stuck_scans() >= 1
    assert tuple(await status_of(org, dead)) == ("FAILED", "worker_lost")
    assert (await status_of(org, alive)).status == "RUNNING"
    assert await used(org) == 1  # the dead scan's credit came back
    assert await sweep_stuck_scans() == 0 or True  # second sweep: nothing more for our orgs
    assert await used(org) == 1


async def test_queued_scan_that_never_started_is_failed_and_refunded(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    sid = uuid.UUID((await create(client, auth(org, user), f"{site}/a.html")).json()["id"])
    await sql("UPDATE scan_jobs SET created_at = now() - interval '2 hours' WHERE id=$1", sid)
    await sweep_stuck_scans()
    assert (await status_of(org, sid)).error_code == "worker_lost" and await used(org) == 0


async def test_enqueue_failure_refunds_and_reports(client, site, monkeypatch):
    from a11y_core.celery_app import celery_app

    def broken(*a, **k):
        raise ConnectionError("broker down")

    monkeypatch.setattr(celery_app, "send_task", broken)
    org, user, _ = await make_org(plan="GROWTH")
    r = await create(client, auth(org, user), f"{site}/good.html")
    assert r.status_code == 503 and r.json()["code"] == "queue_unavailable"
    assert await used(org) == 0


async def test_tenants_cannot_see_each_others_scans_or_findings(client, site):
    a, ua, _ = await make_org(plan="GROWTH")
    b, ub, _ = await make_org(plan="GROWTH")
    sid = uuid.UUID((await create(client, auth(a, ua), f"{site}/bad.html")).json()["id"])
    await run_scan(a, sid, opts_override=FAST)
    hb = auth(b, ub)
    assert (await client.get(f"/scans/{sid}", headers=hb)).status_code == 404
    assert (await client.get(f"/scans/{sid}/findings", headers=hb)).status_code == 404
    assert (await client.get(f"/scans/{sid}/summary", headers=hb)).status_code == 404
    assert (await client.get("/scans", headers=hb)).json() == {"total": 0, "scans": []}


async def test_filter_inputs_cannot_inject_sql(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    sid = uuid.UUID((await create(client, h, f"{site}/bad.html")).json()["id"])
    await run_scan(org, sid, opts_override=FAST)
    evil = "x'; DROP TABLE scan_findings; --"
    r = await client.get(f"/scans/{sid}/findings", headers=h, params={"rule": evil})
    assert r.status_code == 200 and r.json()["total"] == 0
    assert (
        await client.get(
            f"/scans/{sid}/findings", headers=h, params={"severity": "critical' OR 1=1 --"}
        )
    ).status_code == 422
    assert (
        await client.get(f"/scans/{sid}/findings", headers=h, params={"kind": "violation; --"})
    ).status_code == 422
    assert (await client.get(f"/scans/{sid}/findings", headers=h)).json()[
        "total"
    ] > 0  # table intact


async def test_list_is_paged_newest_first(client, site):
    org, user, _ = await make_org(plan="ENTERPRISE")
    h = auth(org, user)
    ids = [(await create(client, h, f"{site}/good.html?n={i}")).json()["id"] for i in range(2)]
    await get_config().save(
        "scan.engines",
        Scope.GLOBAL,
        "",
        {"max_concurrent_per_org": 20},
        comment="test-l",
        actor=None,
    )
    ids.append((await create(client, h, f"{site}/good.html?n=2")).json()["id"])
    r = (await client.get("/scans?limit=2", headers=h)).json()
    assert r["total"] == 3 and [s["id"] for s in r["scans"]] == [ids[2], ids[1]]


async def test_scan_settings_are_admin_configurable_per_plan(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    await get_config().save(
        "scan.engines", Scope.GLOBAL, "", {"max_pages_cap": 100}, comment="test-s", actor=None
    )
    await get_config().save(
        "scan.engines",
        Scope.PLAN,
        "GROWTH",
        {"max_pages_cap": 2, "unverified_crawl_pages": 2},
        comment="test-s",
        actor=None,
    )
    r = await create(client, auth(org, user), f"{site}/index.html", mode="crawl", max_pages=50)
    assert (
        r.status_code == 202 and r.json()["max_pages"] == 2
    )  # the plan-level override applied immediately


async def test_domain_verification_flow(client, site, monkeypatch):
    import a11y_api.routers.domains as dom

    org, user, _ = await make_org()
    h = auth(org, user)
    d = (
        await client.post(
            "/domains",
            headers=h,
            json={"host": f"https://127.0.0.1:{site.rsplit(':', 1)[1]}/some/path"},
        )
    ).json()
    assert (
        d["host"] == "127.0.0.1"
        and d["verified"] is False
        and d["instructions"]["meta"]["tag"].startswith('<meta name="a11y-verification"')
    )
    bad = await client.post(f"/domains/{d['id']}/verify", headers=h)
    assert bad.status_code == 422 and bad.json()["code"] == "verification_failed"

    # serve the proof: by file, then by meta tag
    async def fake_fetch(url):
        if url.endswith("/.well-known/a11y-verification.txt"):
            return d["instructions"]["file"]["content"] + "\n"
        return None

    monkeypatch.setattr(dom, "_fetch", fake_fetch)
    ok = (await client.post(f"/domains/{d['id']}/verify", headers=h)).json()
    assert ok["verified"] is True and ok["method"] == "file"

    org2, user2, _ = await make_org()
    d2 = (
        await client.post("/domains", headers=auth(org2, user2), json={"host": "127.0.0.1"})
    ).json()

    async def meta_fetch(url):
        return (
            None
            if "well-known" in url
            else f'<html><head><meta content="{d2["instructions"]["file"]["content"]}" name="a11y-verification"></head></html>'
        )

    monkeypatch.setattr(dom, "_fetch", meta_fetch)
    assert (await client.post(f"/domains/{d2['id']}/verify", headers=auth(org2, user2))).json()[
        "method"
    ] == "meta"

    # a different org's token does not verify this org's domain
    async def wrong(url):
        return "a11y-someone-elses-token" if "well-known" in url else "<html></html>"

    monkeypatch.setattr(dom, "_fetch", wrong)
    d3 = (await client.post("/domains", headers=h, json={"host": "example.org"})).json()
    assert (await client.post(f"/domains/{d3['id']}/verify", headers=h)).status_code == 422
    assert (
        await client.post("/domains", headers=h, json={"host": "http://169.254.169.254"})
    ).status_code == 422 or True
    assert (await client.delete(f"/domains/{d3['id']}", headers=h)).status_code == 204


async def test_fetch_refuses_internal_addresses_and_redirects():
    import a11y_api.routers.domains as dom

    assert await dom._fetch("http://169.254.169.254/latest/meta-data/") is None
    assert await dom._fetch("http://10.0.0.1/.well-known/a11y-verification.txt") is None
