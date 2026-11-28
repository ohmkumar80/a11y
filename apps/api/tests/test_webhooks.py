# ruff: noqa: F811
"""Outbound webhooks against a REAL local receiver: signing, retries, SSRF, redirects, concurrency and isolation."""

import asyncio
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from a11y_core import webhooks
from a11y_core.config import Scope, get_config
from a11y_core.config.crypto import get_box
from a11y_core.scan_jobs import fail_scan
from a11y_documents.tasks import render_report
from a11y_web_audit.tasks import run_scan

from .conftest import make_org, sql
from .test_billing import auth
from .test_reports_api import finished_scan
from .test_scans_api import FAST, _cfg_reset, create, dev, high_ports, site  # noqa: F401  (fixtures)


class Receiver:
    """A tiny web server. ``answers`` is a queue of (status, delay_seconds, location); empty = 200."""

    def __init__(self):
        self.requests: list[dict] = []
        self.answers: list[tuple] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("content-length", 0)))
                outer.requests.append(
                    {"path": self.path, "headers": dict(self.headers), "body": body}
                )
                status, delay, location = outer.answers.pop(0) if outer.answers else (200, 0, None)
                time.sleep(delay)
                self.send_response(status)
                if location:
                    self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/hooks/a11y"

    def stop(self):
        self.server.shutdown()


@pytest.fixture
def rx():
    r = Receiver()
    yield r
    r.stop()


@pytest.fixture(autouse=True)
async def _clean(monkeypatch):
    monkeypatch.setattr(
        webhooks, "PORTS", tuple(range(1, 65536))
    )  # the local receiver listens on a random port

    async def wipe():
        await sql("DELETE FROM setting_versions WHERE comment LIKE 'test-%'")
        r = get_config()._r()
        for k in await r.keys("cfg:*"):
            await r.delete(k)

    await wipe()
    yield
    await wipe()


async def make_endpoint(
    client,
    org,
    user,
    url,
    events=("scan.completed", "scan.failed", "report.ready", "report.failed"),
):
    r = await client.post(
        "/org/webhooks",
        headers=auth(org, user),
        json={"url": url, "events": list(events), "description": "ci"},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def deliveries(org):
    return await sql(
        "SELECT id, status, attempts, response_status, error, event_type, next_attempt_at FROM webhook_deliveries WHERE organization_id=$1 ORDER BY created_at",
        org,
    )


async def due_now(delivery_id):
    await sql(
        "UPDATE webhook_deliveries SET next_attempt_at = now() - interval '1 second' WHERE id=$1",
        delivery_id,
    )


async def limits(org, **v):
    await get_config().save(
        "webhooks.limits", Scope.ORG, str(org), v, comment="test-wl", actor=None
    )


# -- endpoints ------------------------------------------------------------------------------------
async def test_creating_an_endpoint_shows_the_secret_once_and_stores_it_encrypted(client, rx, dev):
    org, user, _ = await make_org(plan="GROWTH")
    ep = await make_endpoint(client, org, user, rx.url)
    assert ep["secret"].startswith("whsec_") and "only once" in ep["notice"]
    listed = (await client.get("/org/webhooks", headers=auth(org, user))).json()
    assert (
        "secret" not in listed["endpoints"][0]
        and listed["endpoints"][0]["secret_hint"] == ep["secret"][-4:]
    )
    ct = (await sql("SELECT secret_ct FROM webhook_endpoints WHERE organization_id=$1", org))[0][
        "secret_ct"
    ]
    assert ep["secret"] not in ct and get_box().decrypt(ct) == ep["secret"]
    assert await sql(
        "SELECT action FROM audit_log WHERE organization_id=$1 AND action='webhook.create'", org
    )


@pytest.mark.parametrize(
    "url,code",
    [
        ("http://hooks.example.com/a11y", "https_required"),
        ("https://10.0.0.5/hook", "private_address"),
        ("https://169.254.169.254/latest/meta-data", "private_address"),
        ("https://[::1]/hook", "private_address"),
        ("https://user:pass@hooks.example.com/hook", "credentials_in_url"),
        ("ftp://hooks.example.com/x", "invalid_scheme"),
        ("https://nonexistent-host-for-a11y-tests.invalid/hook", "dns_failed"),
    ],
)
async def test_unsafe_addresses_are_refused_with_a_reason(client, dev, url, code):
    org, user, _ = await make_org(plan="GROWTH")
    r = await client.post(
        "/org/webhooks", headers=auth(org, user), json={"url": url, "events": ["scan.completed"]}
    )
    assert r.status_code == 422 and r.json()["code"] == code and r.json()["field"] == "url", r.text


async def test_limits_entitlement_flag_and_validation(client, rx, dev):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    assert (
        await client.post("/org/webhooks", headers=h, json={"url": rx.url, "events": ["nope"]})
    ).status_code == 422
    assert (
        await client.post("/org/webhooks", headers=h, json={"url": rx.url, "events": []})
    ).status_code == 422
    await limits(org, max_endpoints_per_org=1)
    await make_endpoint(client, org, user, rx.url)
    over = await client.post(
        "/org/webhooks", headers=h, json={"url": rx.url, "events": ["scan.completed"]}
    )
    assert over.status_code == 409 and over.json()["code"] == "too_many_webhooks"
    starter, suser, _ = await make_org(plan="STARTER")
    no = await client.post(
        "/org/webhooks",
        headers=auth(starter, suser),
        json={"url": rx.url, "events": ["scan.completed"]},
    )
    assert no.status_code == 402 and no.json()["code"] == "api_not_in_plan"
    await get_config().save(
        "flags", Scope.ORG, str(org), {"webhooks": False}, comment="test-fl", actor=None
    )
    off = await client.post(
        "/org/webhooks", headers=h, json={"url": rx.url, "events": ["scan.completed"]}
    )
    assert off.status_code == 403 and off.json()["feature"] == "webhooks"
    assert (await client.get("/org/webhooks", headers=h)).json()["switched_off"] is True


async def test_only_administrators_manage_webhooks_and_organisations_are_isolated(client, rx, dev):
    from .test_reports_api import add_member

    org, user, _ = await make_org(plan="GROWTH")
    ep = await make_endpoint(client, org, user, rx.url)
    member = await add_member(org)
    assert (
        await client.get("/org/webhooks", headers=auth(org, member, "STANDARD_USER"))
    ).status_code == 403
    other, ouser, _ = await make_org(plan="GROWTH")
    oh = auth(other, ouser)
    assert (await client.get("/org/webhooks", headers=oh)).json()["endpoints"] == []
    for method, path in (
        ("patch", ""),
        ("delete", ""),
        ("post", "/test"),
        ("post", "/rotate-secret"),
        ("get", "/deliveries"),
    ):
        r = await getattr(client, method)(
            f"/org/webhooks/{ep['id']}{path}",
            headers=oh,
            **({"json": {"enabled": False}} if method == "patch" else {}),
        )
        assert r.status_code == 404, (method, path)
    with pytest.raises(
        Exception, match="permission denied"
    ):  # the address of an endpoint cannot be edited, even by a bug
        from a11y_core.db import tenant_session
        from sqlalchemy import text

        async with tenant_session(org) as db:
            await db.execute(text("UPDATE webhook_endpoints SET url='https://evil.example/'"))


# -- delivery -------------------------------------------------------------------------------------
async def test_an_event_is_delivered_signed_exactly_once(client, rx, dev):
    org, user, _ = await make_org(plan="GROWTH")
    ep = await make_endpoint(client, org, user, rx.url)
    dev.clear()
    assert (
        await webhooks.emit_event(
            org, "scan.completed", {"scan_id": "s1", "url": "https://x.example/"}
        )
        == 1
    )
    assert [d[0] for d in dev] == ["webhooks.deliver"] and dev[0][2] == "system"
    did = (await deliveries(org))[0]["id"]
    assert await webhooks.deliver(org, did) == "SENT"
    assert await webhooks.deliver(org, did) == "SKIPPED"  # a redelivered task changes nothing
    assert len(rx.requests) == 1
    req = rx.requests[0]
    h = {k.lower(): v for k, v in req["headers"].items()}
    assert (
        req["path"] == "/hooks/a11y"
        and h["content-type"] == "application/json"
        and h["user-agent"] == "a11y-webhooks/1"
    )
    assert webhooks.verify(ep["secret"], h["a11y-signature"], req["body"])  # what a receiver does
    assert not webhooks.verify("whsec_wrong", h["a11y-signature"], req["body"])
    assert not webhooks.verify(
        ep["secret"], h["a11y-signature"], req["body"] + b" "
    )  # a changed body fails
    env = json.loads(req["body"])
    assert (
        env["type"] == "scan.completed"
        and env["id"] == h["a11y-event-id"]
        and env["data"]["scan_id"] == "s1"
        and env["created_at"]
    )
    assert h["a11y-event-type"] == "scan.completed" and h["a11y-delivery-attempt"] == "1"
    assert h["host"] == req["headers"]["Host"] and h["host"].startswith("127.0.0.1:")
    row = (await deliveries(org))[0]
    assert (row["status"], row["response_status"], row["error"]) == ("SENT", 200, None)


async def test_only_subscribed_enabled_endpoints_get_an_event(client, rx, dev):
    org, user, _ = await make_org(plan="GROWTH")
    a = await make_endpoint(client, org, user, rx.url, events=["report.ready"])
    b = await make_endpoint(client, org, user, rx.url, events=["scan.completed"])
    c = await make_endpoint(client, org, user, rx.url, events=["scan.completed"])
    assert (
        await client.patch(
            f"/org/webhooks/{c['id']}", headers=auth(org, user), json={"enabled": False}
        )
    ).json()["enabled"] is False
    assert await webhooks.emit_event(org, "scan.completed", {"scan_id": "s"}) == 1
    got = await sql("SELECT endpoint_id FROM webhook_deliveries WHERE organization_id=$1", org)
    assert [str(r["endpoint_id"]) for r in got] == [b["id"]] and a["id"] != b["id"]
    await get_config().save(
        "flags", Scope.ORG, str(org), {"webhooks": False}, comment="test-fl", actor=None
    )
    assert (
        await webhooks.emit_event(org, "scan.completed", {"scan_id": "s"}) == 0
    )  # switched off: nothing is queued


async def test_failures_retry_with_backoff_then_are_abandoned_and_can_be_retried_by_hand(
    client, rx, dev
):
    org, user, _ = await make_org(plan="GROWTH")
    await limits(org, max_attempts=3)
    await make_endpoint(client, org, user, rx.url)
    await webhooks.emit_event(org, "scan.failed", {"scan_id": "s"})
    did = (await deliveries(org))[0]["id"]
    rx.answers = [(500, 0, None)] * 3
    assert await webhooks.deliver(org, did) == "PENDING"
    row = (await deliveries(org))[0]
    assert row["attempts"] == 1 and row["error"] == "HTTP 500" and row["response_status"] == 500
    delta = row["next_attempt_at"].timestamp() - time.time()
    assert 40 < delta < 70  # about a minute
    assert await webhooks.deliver(org, did) == "SKIPPED"  # not due yet: nothing is sent early
    assert len(rx.requests) == 1
    await due_now(did)
    assert await webhooks.deliver(org, did) == "PENDING"
    await due_now(did)
    assert await webhooks.deliver(org, did) == "ABANDONED"
    assert (await deliveries(org))[0]["attempts"] == 3
    assert (
        await sql(
            "SELECT consecutive_failures FROM webhook_endpoints WHERE organization_id=$1", org
        )
    )[0]["consecutive_failures"] == 1
    # an administrator retries it once the receiver is fixed: full attempts again
    r = await client.post(f"/org/webhooks/deliveries/{did}/retry", headers=auth(org, user))
    assert r.status_code == 202
    assert await webhooks.deliver(org, did) == "SENT"
    assert (
        await sql(
            "SELECT consecutive_failures FROM webhook_endpoints WHERE organization_id=$1", org
        )
    )[0]["consecutive_failures"] == 0
    assert (
        await client.post(f"/org/webhooks/deliveries/{did}/retry", headers=auth(org, user))
    ).status_code == 409  # already delivered


async def test_the_sweeper_requeues_what_is_due_and_frees_lost_claims(client, rx, dev):
    org, user, _ = await make_org(plan="GROWTH")
    await make_endpoint(client, org, user, rx.url)
    await webhooks.emit_event(org, "scan.completed", {"scan_id": "1"})
    await webhooks.emit_event(org, "scan.completed", {"scan_id": "2"})
    a, b = [r["id"] for r in await deliveries(org)]
    await sql(
        "UPDATE webhook_deliveries SET next_attempt_at = now() + interval '1 hour' WHERE id=$1", b
    )  # not due
    await sql(
        "UPDATE webhook_deliveries SET status='SENDING', claimed_at = now() - interval '10 minutes' WHERE id=$1",
        a,
    )  # worker died
    dev.clear()
    n = await webhooks.retry_due()
    assert (
        n >= 1 and any(d[1][1] == str(a) for d in dev) and not any(d[1][1] == str(b) for d in dev)
    )
    assert (await deliveries(org))[0]["status"] == "PENDING"


async def test_410_gone_switches_the_endpoint_off_and_tells_the_administrators(client, rx, dev):
    org, user, email = await make_org(plan="GROWTH")
    ep = await make_endpoint(client, org, user, rx.url)
    await webhooks.emit_event(org, "scan.completed", {"scan_id": "s"})
    did = (await deliveries(org))[0]["id"]
    rx.answers = [(410, 0, None)]
    assert await webhooks.deliver(org, did) == "ABANDONED"  # no point retrying
    e = (
        await sql(
            "SELECT enabled, disabled_reason FROM webhook_endpoints WHERE id=$1",
            uuid.UUID(ep["id"]),
        )
    )[0]
    assert e["enabled"] is False and "410" in e["disabled_reason"]
    mail = await sql(
        "SELECT to_email, event FROM notification_log WHERE organization_id=$1 AND event='webhook.disabled'",
        org,
    )
    assert [m["to_email"] for m in mail] == [email.lower()]
    assert (
        await webhooks.emit_event(org, "scan.completed", {"scan_id": "t"}) == 0
    )  # off: no more events


async def test_an_endpoint_that_keeps_failing_is_switched_off(client, rx, dev):
    org, user, _ = await make_org(plan="GROWTH")
    await limits(org, max_attempts=1, disable_after_failures=2)
    ep = await make_endpoint(client, org, user, rx.url)
    rx.answers = [(503, 0, None)] * 5
    for i in range(2):
        await webhooks.emit_event(org, "scan.completed", {"scan_id": str(i)})
    for r in await deliveries(org):
        assert await webhooks.deliver(org, r["id"]) == "ABANDONED"
    e = (
        await sql(
            "SELECT enabled, consecutive_failures, disabled_reason FROM webhook_endpoints WHERE id=$1",
            uuid.UUID(ep["id"]),
        )
    )[0]
    assert (
        e["enabled"] is False
        and e["consecutive_failures"] == 2
        and "2 deliveries in a row" in e["disabled_reason"]
    )
    # switching it back on clears the history
    r = (
        await client.patch(
            f"/org/webhooks/{ep['id']}", headers=auth(org, user), json={"enabled": True}
        )
    ).json()
    assert r["enabled"] is True and r["consecutive_failures"] == 0 and r["disabled_reason"] is None


async def test_a_slow_receiver_times_out_and_is_retried(client, rx, dev):
    org, user, _ = await make_org(plan="GROWTH")
    await limits(org, timeout_seconds=1)
    await make_endpoint(client, org, user, rx.url)
    await webhooks.emit_event(org, "scan.completed", {"scan_id": "s"})
    did = (await deliveries(org))[0]["id"]
    rx.answers = [(200, 2.5, None)]
    assert await webhooks.deliver(org, did) == "PENDING"
    assert (await deliveries(org))[0]["error"] == "timed out"


async def test_redirects_are_never_followed(client, rx, dev):
    org, user, _ = await make_org(plan="GROWTH")
    await make_endpoint(client, org, user, rx.url)
    await webhooks.emit_event(org, "scan.completed", {"scan_id": "s"})
    did = (await deliveries(org))[0]["id"]
    rx.answers = [(302, 0, "http://169.254.169.254/latest/meta-data")]
    assert await webhooks.deliver(org, did) == "PENDING"
    assert (await deliveries(org))[0]["error"] == "HTTP 302" and len(
        rx.requests
    ) == 1  # a redirect is a failure, not a hop


async def test_an_address_that_later_resolves_to_a_private_network_is_blocked_at_delivery(
    client, rx, dev
):
    org, user, _ = await make_org(plan="GROWTH")
    ep = await make_endpoint(client, org, user, rx.url)
    await webhooks.emit_event(org, "scan.completed", {"scan_id": "s"})
    did = (await deliveries(org))[0]["id"]
    # DNS rebinding, simulated: the endpoint's host now points inside our network
    await sql(
        "UPDATE webhook_endpoints SET url='https://10.1.2.3/hook' WHERE id=$1", uuid.UUID(ep["id"])
    )
    assert await webhooks.deliver(org, did) == "PENDING"
    row = (await deliveries(org))[0]
    assert (
        row["error"] == "blocked: private_address" and rx.requests == []
    )  # nothing was sent anywhere


async def test_two_workers_cannot_send_the_same_delivery(client, rx, dev):
    org, user, _ = await make_org(plan="GROWTH")
    await make_endpoint(client, org, user, rx.url)
    await webhooks.emit_event(org, "scan.completed", {"scan_id": "s"})
    did = (await deliveries(org))[0]["id"]
    out = await asyncio.gather(*[webhooks.deliver(org, did) for _ in range(4)])
    assert sorted(out) == ["SENT", "SKIPPED", "SKIPPED", "SKIPPED"] and len(rx.requests) == 1


async def test_a_test_event_reaches_one_endpoint_and_the_history_shows_what_happened(
    client, rx, dev
):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    ep = await make_endpoint(
        client, org, user, rx.url, events=["report.ready"]
    )  # not subscribed to ping: still allowed
    r = await client.post(f"/org/webhooks/{ep['id']}/test", headers=h)
    assert r.status_code == 202
    assert await webhooks.deliver(org, uuid.UUID(r.json()["delivery_id"])) == "SENT"
    env = json.loads(rx.requests[0]["body"])
    assert env["type"] == "ping" and "test event" in env["data"]["message"]
    hist = (await client.get(f"/org/webhooks/{ep['id']}/deliveries", headers=h)).json()
    assert [(d["event_type"], d["status"], d["response_status"]) for d in hist] == [
        ("ping", "SENT", 200)
    ]
    assert (await client.get("/org/webhooks", headers=h)).json()["endpoints"][0]["last_delivery"][
        "status"
    ] == "SENT"


async def test_rotating_the_secret_replaces_it_at_once(client, rx, dev):
    org, user, _ = await make_org(plan="GROWTH")
    ep = await make_endpoint(client, org, user, rx.url)
    new = (
        await client.post(f"/org/webhooks/{ep['id']}/rotate-secret", headers=auth(org, user))
    ).json()
    assert new["secret"] != ep["secret"] and "old one no longer works" in new["notice"]
    await webhooks.emit_event(org, "scan.completed", {"scan_id": "s"})
    await webhooks.deliver(org, (await deliveries(org))[0]["id"])
    sig = {k.lower(): v for k, v in rx.requests[0]["headers"].items()}["a11y-signature"]
    assert webhooks.verify(new["secret"], sig, rx.requests[0]["body"]) and not webhooks.verify(
        ep["secret"], sig, rx.requests[0]["body"]
    )


async def test_deleting_an_endpoint_removes_its_history(client, rx, dev):
    org, user, _ = await make_org(plan="GROWTH")
    ep = await make_endpoint(client, org, user, rx.url)
    await webhooks.emit_event(org, "scan.completed", {"scan_id": "s"})
    assert (
        await client.delete(f"/org/webhooks/{ep['id']}", headers=auth(org, user))
    ).status_code == 204
    assert (
        await deliveries(org) == []
        and (await client.get("/org/webhooks", headers=auth(org, user))).json()["endpoints"] == []
    )


# -- the product raises the events ----------------------------------------------------------------
async def test_scans_and_reports_raise_webhook_events(client, site, rx, dev):
    org, user, _ = await make_org(plan="GROWTH")
    await make_endpoint(client, org, user, rx.url)
    sid, h = await finished_scan(client, site, org, user)
    rep = (
        await client.post(f"/scans/{sid}/reports", headers=h, json={"kind": "audit_csv"})
    ).json()["id"]
    await render_report(org, uuid.UUID(rep))
    bad = uuid.UUID((await create(client, h, f"{site}/good.html")).json()["id"])
    await fail_scan(
        org, bad, "worker_lost", "The scan worker stopped responding.", system_fault=True
    )
    rows = await deliveries(org)
    assert sorted(r["event_type"] for r in rows) == [
        "report.ready",
        "scan.completed",
        "scan.failed",
    ]
    for r in rows:
        await webhooks.deliver(org, r["id"])
    by = {json.loads(q["body"])["type"]: json.loads(q["body"])["data"] for q in rx.requests}
    assert (
        by["scan.completed"]["scan_id"] == str(sid)
        and by["scan.completed"]["findings"] > 0
        and by["scan.completed"]["api_path"] == f"/v1/scans/{sid}"
    )
    assert by["report.ready"] == {
        "report_id": rep,
        "scan_id": str(sid),
        "kind": "audit_csv",
        "standard": "WCAG_2_2_AA",
        "status": "READY",
        "download_path": f"/v1/reports/{rep}/download",
    }
    assert (
        by["scan.failed"]["credit_returned"] is True
        and "stopped responding" in by["scan.failed"]["reason"]
    )


async def test_a_redelivered_scan_task_does_not_emit_a_second_event(client, site, rx, dev):
    org, user, _ = await make_org(plan="GROWTH")
    await make_endpoint(client, org, user, rx.url, events=["scan.completed"])
    h = auth(org, user)
    sid = uuid.UUID((await create(client, h, f"{site}/good.html")).json()["id"])
    await run_scan(org, sid, opts_override=FAST)
    await run_scan(org, sid, opts_override=FAST)  # finished scans are not re-run
    assert len(await deliveries(org)) == 1


async def test_signature_verification_rejects_old_and_malformed_headers():
    s, _ = webhooks.new_secret()
    body = b"{}"
    ok = webhooks.sign(s, 1_000_000, body)
    assert webhooks.verify(s, ok, body, now=1_000_100)
    assert not webhooks.verify(s, ok, body, now=1_000_000 + 301)  # replay window
    for bad in ("", "garbage", "t=abc,v1=00", "v1=00", f"t=1000000,v1={'0' * 64}"):
        assert not webhooks.verify(s, bad, body, now=1_000_000)
