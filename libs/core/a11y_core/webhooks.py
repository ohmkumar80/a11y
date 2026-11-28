"""Outbound webhooks (PROJECT_PLAN 3.17): tell a customer's system when something happens, instead of making it poll.

Delivery is durable and safe:
* Every event for every subscribed endpoint is a row (``webhook_deliveries``); ``(endpoint, event)`` is unique, so
  emitting twice never sends twice. A scheduled sweeper re-enqueues anything due, so a lost task or a restart loses nothing.
* The URL is customer-supplied, so every request re-checks it with the same SSRF rules as the scanner and connects to the
  address that passed the check (TLS is still verified against the real host name). Redirects are never followed.
* The body is signed: ``A11y-Signature: t=<unix time>,v1=<hex HMAC-SHA256 of "<t>.<body>" with the endpoint secret>``.
  Receivers should check the signature and reject old timestamps. The secret is shown once and stored encrypted.
* No database connection is held while waiting for the customer's server.
* Retries back off (1 minute, 5 minutes, 30 minutes, 2 hours, 6 hours); after the last, the delivery is abandoned and an
  endpoint that keeps failing is switched off and its administrators emailed."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import text

from .config import get_config
from .config.crypto import get_box
from .config.registry import Scope, SettingDef, register
from .db import admin_session, tenant_session
from .ssrf import BlockedTarget, dev_allow_hosts, parse_url, resolve_public

log = logging.getLogger(__name__)

EVENTS = {
    "scan.completed": "A scan finished successfully",
    "scan.failed": "A scan did not finish",
    "report.ready": "A report is ready to download",
    "report.failed": "A report could not be produced",
    "review.completed": "A person finished checking a document you asked them to check",
}
PING = "ping"  # sent only when an administrator asks for a test
BACKOFF = (60, 300, 1800, 7200, 21600)  # seconds before attempt 2, 3, ...
STALE_CLAIM = timedelta(
    minutes=3
)  # a delivery claimed this long ago whose worker vanished is retried
PORTS = (80, 443, 8080, 8443)
USER_AGENT = "a11y-webhooks/1"


class WebhookLimits(BaseModel):
    max_endpoints_per_org: int = Field(
        5, ge=1, le=50, description="Webhook endpoints per organisation"
    )
    max_attempts: int = Field(
        6, ge=1, le=10, description="Tries per delivery before it is abandoned"
    )
    timeout_seconds: int = Field(10, ge=1, le=60, description="Wait for the receiver's answer")
    disable_after_failures: int = Field(
        20,
        ge=1,
        le=1000,
        description="Switch an endpoint off after this many abandoned deliveries in a row",
    )
    require_https: bool = Field(
        True,
        description="Only https addresses (plain http is accepted only for local development hosts)",
    )


register(
    SettingDef(
        key="webhooks.limits",
        model=WebhookLimits,
        default=WebhookLimits(),
        description="Outbound webhooks: endpoints per organisation, retries, timeout and when a failing endpoint is switched off.",
        scopes=frozenset({Scope.GLOBAL, Scope.PLAN, Scope.ORG}),
        tags=("api",),
    )
)


def new_secret() -> tuple[str, str]:
    """(secret shown once, ciphertext stored)."""
    s = "whsec_" + secrets.token_urlsafe(32)
    return s, get_box().encrypt(s)


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def verify(
    secret: str, header: str, body: bytes, *, tolerance: int = 300, now: float | None = None
) -> bool:
    """What a receiver should do. Kept here so our own tests (and docs) use the same code."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs((now if now is not None else time.time()) - t) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, t, body), header)


async def check_url(
    url: str, *, require_https: bool = True
) -> tuple[str, str, int, tuple[str, ...]]:
    """Validate an endpoint address: (scheme, host, port, public addresses). Raises BlockedTarget."""
    scheme, host, port = parse_url(url, ports=PORTS)
    local = host.lower() in dev_allow_hosts()
    if require_https and scheme != "https" and not local:
        raise BlockedTarget("https_required", "Webhook addresses must start with https://.")
    return scheme, host, port, await resolve_public(host, port)


def body_bytes(envelope: dict) -> bytes:
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()


async def emit_event(org_id: uuid.UUID, event_type: str, data: dict) -> int:
    """Queue ``event_type`` for every enabled endpoint of the organisation subscribed to it. Never raises: a webhook
    problem must not affect the scan or report that caused the event."""
    from . import billing, flags  # noqa: PLC0415
    from .celery_app import celery_app  # noqa: PLC0415

    try:
        async with tenant_session(org_id) as db:
            plan_id = (await billing.load_subscription(db)).plan_id
        if not await flags.enabled("webhooks", org_id=org_id, plan_id=plan_id):
            return 0
        event_id = uuid.uuid4()
        envelope = {
            "id": str(event_id),
            "type": event_type,
            "created_at": datetime.now(UTC).isoformat(),
            "data": data,
        }
        queued: list[uuid.UUID] = []
        async with tenant_session(org_id) as db:
            eps = (
                await db.execute(
                    text("SELECT id FROM webhook_endpoints WHERE enabled AND :e = ANY(events)"),
                    {"e": event_type},
                )
            ).all()
            for ep in eps:
                row = (
                    await db.execute(
                        text(
                            "INSERT INTO webhook_deliveries (id, organization_id, endpoint_id, event_id, event_type, payload) "
                            "VALUES (gen_random_uuid(), :o, :ep, :ev, :t, CAST(:p AS jsonb)) "
                            "ON CONFLICT (endpoint_id, event_id) DO NOTHING RETURNING id"
                        ),
                        {
                            "o": org_id,
                            "ep": ep.id,
                            "ev": event_id,
                            "t": event_type,
                            "p": json.dumps(envelope),
                        },
                    )
                ).first()
                if row:
                    queued.append(row[0])
        for did in queued:
            try:
                celery_app.send_task(
                    "webhooks.deliver", args=[str(org_id), str(did)], queue="system"
                )
            except Exception:  # noqa: BLE001 - the sweeper will pick the row up
                log.exception("could not queue webhook delivery %s", did)
        return len(queued)
    except Exception:  # noqa: BLE001
        log.exception("could not emit webhook event %s", event_type)
        return 0


def _short(e: Exception) -> str:
    if isinstance(e, BlockedTarget):
        return f"blocked: {e.code}"
    if isinstance(e, httpx.TimeoutException):
        return "timed out"
    if isinstance(e, httpx.ConnectError):
        return "could not connect"
    return type(e).__name__


async def deliver(
    org_id: uuid.UUID, delivery_id: uuid.UUID, *, transport: httpx.AsyncBaseTransport | None = None
) -> str:
    """One attempt. Returns SENT, PENDING (will retry), ABANDONED, or SKIPPED (not due / already handled). Idempotent."""
    from . import billing  # noqa: PLC0415

    async with tenant_session(org_id) as db:
        plan_id = (await billing.load_subscription(db)).plan_id
    limits = (await get_config().effective("webhooks.limits", org_id=org_id, plan_id=plan_id)).value
    async with tenant_session(org_id) as db:
        d = (
            await db.execute(
                text(
                    "UPDATE webhook_deliveries SET status='SENDING', claimed_at=now(), attempts=attempts+1 "
                    "WHERE id=:i AND status='PENDING' AND next_attempt_at <= now() "
                    "RETURNING endpoint_id, event_type, payload, attempts"
                ),
                {"i": delivery_id},
            )
        ).first()
        if d is None:
            return "SKIPPED"
        ep = (
            await db.execute(
                text("SELECT url, secret_ct, enabled FROM webhook_endpoints WHERE id=:i"),
                {"i": d.endpoint_id},
            )
        ).first()
        if ep is None or not ep.enabled:
            await db.execute(
                text(
                    "UPDATE webhook_deliveries SET status='ABANDONED', error='The endpoint is switched off or deleted.' WHERE id=:i"
                ),
                {"i": delivery_id},
            )
            return "ABANDONED"

    # -- no database connection is held from here until the answer arrives ------------------------
    status_code: int | None = None
    error: str | None = None
    try:
        scheme, host, port, addrs = await check_url(ep.url, require_https=limits.require_https)
        body = body_bytes(d.payload)
        ts = int(time.time())
        secret = get_box().decrypt(ep.secret_ct)
        ip = addrs[0]
        netloc = f"[{ip}]" if ":" in ip else ip
        path = urlsplit(ep.url)
        target = f"{scheme}://{netloc}:{port}{path.path or '/'}" + (
            f"?{path.query}" if path.query else ""
        )
        default_port = 443 if scheme == "https" else 80
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(limits.timeout_seconds, connect=min(10, limits.timeout_seconds)),
            follow_redirects=False,
        ) as client:
            r = await client.post(
                target,
                content=body,
                headers={
                    "Host": host if port == default_port else f"{host}:{port}",
                    "Content-Type": "application/json",
                    "User-Agent": USER_AGENT,
                    "A11y-Signature": sign(secret, ts, body),
                    "A11y-Event-Id": d.payload["id"],
                    "A11y-Event-Type": d.event_type,
                    "A11y-Delivery-Attempt": str(d.attempts),
                },
                extensions={"sni_hostname": host},
            )
            status_code = r.status_code
    except Exception as e:  # noqa: BLE001 - every failure is recorded, never leaked or raised
        error = _short(e)
    ok = status_code is not None and 200 <= status_code < 300
    if status_code is not None and not ok:
        error = f"HTTP {status_code}"
    gone = status_code == 410
    final = ok or gone or d.attempts >= limits.max_attempts
    nxt = datetime.now(UTC) + timedelta(seconds=BACKOFF[min(d.attempts - 1, len(BACKOFF) - 1)])
    state = "SENT" if ok else ("ABANDONED" if final else "PENDING")
    disabled = False
    async with tenant_session(org_id) as db:
        await db.execute(
            text(
                "UPDATE webhook_deliveries SET status=:s, claimed_at=NULL, response_status=:c, error=:e, "
                "delivered_at=CASE WHEN CAST(:ok AS boolean) THEN now() ELSE delivered_at END, next_attempt_at=:n WHERE id=:i"
            ),
            {
                "s": state,
                "ok": ok,
                "c": status_code,
                "e": None if ok else error,
                "n": nxt,
                "i": delivery_id,
            },
        )
        if ok:
            await db.execute(
                text(
                    "UPDATE webhook_endpoints SET consecutive_failures=0, last_success_at=now() WHERE id=:i"
                ),
                {"i": d.endpoint_id},
            )
        elif state == "ABANDONED":
            n = (
                await db.execute(
                    text(
                        "UPDATE webhook_endpoints SET consecutive_failures=consecutive_failures+1 WHERE id=:i RETURNING consecutive_failures"
                    ),
                    {"i": d.endpoint_id},
                )
            ).scalar_one()
            if gone or n >= limits.disable_after_failures:
                reason = (
                    "The receiver answered 410 Gone."
                    if gone
                    else f"{n} deliveries in a row failed."
                )
                await db.execute(
                    text(
                        "UPDATE webhook_endpoints SET enabled=false, disabled_reason=:r WHERE id=:i"
                    ),
                    {"r": reason, "i": d.endpoint_id},
                )
                disabled = True
    if disabled:
        from . import notify  # noqa: PLC0415

        await notify.notify_webhook_disabled(org_id, d.endpoint_id, ep.url)
    if not ok and state == "PENDING":
        log.info("webhook %s attempt %s failed: %s", delivery_id, d.attempts, error)
    return state


async def retry_due() -> int:
    """Re-enqueue deliveries whose retry time has come, and free ones whose worker disappeared mid-send."""
    from .celery_app import celery_app  # noqa: PLC0415

    async with admin_session(
        actor_user_id=None, reason="webhook retry sweep", action="system.webhook_retry"
    ) as db:
        # the cross-tenant session only reads; changes are made inside each organisation's own session
        stale = (
            await db.execute(
                text(
                    "SELECT id, organization_id FROM webhook_deliveries WHERE status='SENDING' AND claimed_at < now() - CAST(:s AS interval)"
                ),
                {"s": STALE_CLAIM},
            )
        ).all()
    for r in stale:
        async with tenant_session(r.organization_id) as tdb:
            await tdb.execute(
                text(
                    "UPDATE webhook_deliveries SET status='PENDING', claimed_at=NULL WHERE id=:i AND status='SENDING'"
                ),
                {"i": r.id},
            )
    async with admin_session(
        actor_user_id=None, reason="webhook retry sweep", action="system.webhook_retry"
    ) as db:
        due = (
            await db.execute(
                text(
                    "SELECT id, organization_id FROM webhook_deliveries WHERE status='PENDING' AND next_attempt_at <= now() ORDER BY next_attempt_at LIMIT 500"
                )
            )
        ).all()
    for r in due:
        celery_app.send_task(
            "webhooks.deliver", args=[str(r.organization_id), str(r.id)], queue="system"
        )
    return len(due)


def _register_tasks() -> None:
    import asyncio  # noqa: PLC0415

    from .celery_app import celery_app  # noqa: PLC0415
    from .db import dispose_engines  # noqa: PLC0415

    @celery_app.task(name="webhooks.deliver", acks_late=True)
    def deliver_task(org_id: str, delivery_id: str) -> str:
        async def run() -> str:
            try:
                return await deliver(uuid.UUID(org_id), uuid.UUID(delivery_id))
            finally:
                await dispose_engines()

        return asyncio.run(run())

    @celery_app.task(name="webhooks.retry_due")
    def retry_due_task() -> int:
        async def run() -> int:
            try:
                return await retry_due()
            finally:
                await dispose_engines()

        return asyncio.run(run())

    celery_app.conf.beat_schedule = {
        **(celery_app.conf.beat_schedule or {}),
        "webhook-retries": {"task": "webhooks.retry_due", "schedule": 60.0},
    }


_register_tasks()
