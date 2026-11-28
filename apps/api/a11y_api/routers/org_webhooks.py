"""Organisation administrators manage outbound webhooks here. See ``a11y_core.webhooks`` for how events are delivered.

The signing secret is shown once (at creation or rotation) and stored encrypted. The address cannot be edited: to move an
endpoint, create a new one, so a secret is never silently handed to a different server."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from a11y_core import api_keys, billing, flags, webhooks
from a11y_core.celery_app import celery_app
from a11y_core.config import get_config
from a11y_core.db import tenant_session
from a11y_core.models import AuditLog, WebhookEndpoint
from a11y_core.ssrf import BlockedTarget
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update

from ..deps import ensure_flag, require_company_admin
from ..security import Principal

router = APIRouter(prefix="/org/webhooks", tags=["org"])


def _problem(
    http_status: int, detail: str, code: str | None = None, field: str | None = None, **extra
) -> HTTPException:
    return HTTPException(
        http_status, detail={"detail": detail, "code": code, "field": field, **extra}
    )


class EndpointIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    events: list[str] = Field(min_length=1, max_length=len(webhooks.EVENTS))
    description: str = Field("", max_length=120)


class EndpointPatch(BaseModel):
    events: list[str] | None = Field(None, min_length=1, max_length=len(webhooks.EVENTS))
    description: str | None = Field(None, max_length=120)
    enabled: bool | None = None


def _json(e: WebhookEndpoint, last=None) -> dict:
    return {
        "id": str(e.id),
        "url": e.url,
        "description": e.description,
        "events": e.events,
        "enabled": e.enabled,
        "disabled_reason": e.disabled_reason,
        "secret_hint": e.secret_hint,
        "consecutive_failures": e.consecutive_failures,
        "last_success_at": e.last_success_at,
        "created_at": e.created_at,
        "last_delivery": last,
    }


async def _context(db, org_id):
    sub = await billing.load_subscription(db)
    ent = await billing.entitlement(db, sub.plan_id, api_keys.ENTITLEMENT)
    lim = (
        await get_config().effective("webhooks.limits", org_id=org_id, plan_id=sub.plan_id)
    ).value
    on = await flags.enabled("webhooks", org_id=org_id, plan_id=sub.plan_id)
    return sub, ent, lim, on


def _check_events(events: list[str]) -> list[str]:
    bad = sorted(set(events) - set(webhooks.EVENTS))
    if bad:
        raise _problem(422, f"Unknown event: {', '.join(bad)}.", "unknown_event", "events")
    return sorted(set(events))


async def _own(db, endpoint_id: uuid.UUID) -> WebhookEndpoint:
    e = (
        await db.execute(select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id))
    ).scalar_one_or_none()
    if e is None:
        raise _problem(404, "We could not find that webhook.")
    return e


def _audit(db, p: Principal, action: str, **detail) -> None:
    db.add(
        AuditLog(organization_id=p.org_id, actor_user_id=p.user_id, action=action, detail=detail)
    )


@router.get("")
async def list_endpoints(p: Principal = Depends(require_company_admin)):
    async with tenant_session(p.org_id) as db:
        _, ent, lim, on = await _context(db, p.org_id)
        eps = (
            (await db.execute(select(WebhookEndpoint).order_by(WebhookEndpoint.created_at.desc())))
            .scalars()
            .all()
        )
        last = {
            r.endpoint_id: {
                "status": r.status,
                "at": r.created_at,
                "response_status": r.response_status,
                "error": r.error,
            }
            for r in (
                await db.execute(
                    text(
                        "SELECT DISTINCT ON (endpoint_id) endpoint_id, status, created_at, response_status, error FROM webhook_deliveries ORDER BY endpoint_id, created_at DESC"
                    )
                )
            ).all()
        }
    return {
        "entitled": ent.enabled and on,
        "switched_off": ent.enabled and not on,
        "upgrade_url": "/org#plan",
        "max_endpoints": lim.max_endpoints_per_org,
        "events": webhooks.EVENTS,
        "endpoints": [_json(e, last.get(e.id)) for e in eps],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_endpoint(body: EndpointIn, p: Principal = Depends(require_company_admin)):
    await ensure_flag("webhooks", p)
    events = _check_events(body.events)
    secret, ct = webhooks.new_secret()
    async with tenant_session(p.org_id) as db:
        await billing.require_writable(
            db, lock=True
        )  # serialise so the endpoint limit cannot be raced past
        _, ent, lim, _on = await _context(db, p.org_id)
        if not ent.enabled:
            raise _problem(
                402,
                "Your plan does not include API access and webhooks.",
                "api_not_in_plan",
                upgrade_url="/org#plan",
            )
        n = (await db.execute(text("SELECT count(*) FROM webhook_endpoints"))).scalar_one()
        if n >= lim.max_endpoints_per_org:
            raise _problem(
                409,
                f"You already have {n} webhooks, the most your organisation can have. Delete one first.",
                "too_many_webhooks",
            )
    try:
        await webhooks.check_url(body.url.strip(), require_https=lim.require_https)
    except BlockedTarget as e:
        raise _problem(422, e.message, e.code, "url") from None
    async with tenant_session(p.org_id) as db:
        ep = WebhookEndpoint(
            id=uuid.uuid4(),
            organization_id=p.org_id,
            url=body.url.strip(),
            description=body.description.strip(),
            events=events,
            secret_ct=ct,
            secret_hint=secret[-4:],
            created_by=p.user_id,
        )
        db.add(ep)
        _audit(db, p, "webhook.create", endpoint_id=str(ep.id), url=ep.url, events=events)
        await db.flush()
        await db.refresh(ep)
        out = _json(ep)
    return {
        **out,
        "secret": secret,
        "notice": "Copy the signing secret now. It is shown only once.",
    }


@router.patch("/{endpoint_id}")
async def update_endpoint(
    endpoint_id: uuid.UUID, body: EndpointPatch, p: Principal = Depends(require_company_admin)
):
    async with tenant_session(p.org_id) as db:
        e = await _own(db, endpoint_id)
        values: dict = {}
        if body.events is not None:
            values["events"] = _check_events(body.events)
        if body.description is not None:
            values["description"] = body.description.strip()
        if body.enabled is not None:
            values["enabled"] = body.enabled
            if body.enabled:  # switching back on clears the failure history
                values |= {"disabled_reason": None, "consecutive_failures": 0}
            else:
                values["disabled_reason"] = "Switched off by an administrator."
        if values:
            await db.execute(
                update(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id).values(**values)
            )
            _audit(
                db,
                p,
                "webhook.update",
                endpoint_id=str(endpoint_id),
                **{k: v for k, v in values.items() if k in ("enabled", "events")},
            )
        await db.refresh(e)
        return _json(e)


@router.post("/{endpoint_id}/rotate-secret")
async def rotate_secret(endpoint_id: uuid.UUID, p: Principal = Depends(require_company_admin)):
    secret, ct = webhooks.new_secret()
    async with tenant_session(p.org_id) as db:
        await _own(db, endpoint_id)
        await db.execute(
            update(WebhookEndpoint)
            .where(WebhookEndpoint.id == endpoint_id)
            .values(secret_ct=ct, secret_hint=secret[-4:])
        )
        _audit(db, p, "webhook.rotate_secret", endpoint_id=str(endpoint_id))
    return {
        "secret": secret,
        "secret_hint": secret[-4:],
        "notice": "Copy the new signing secret now. The old one no longer works.",
    }


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(endpoint_id: uuid.UUID, p: Principal = Depends(require_company_admin)):
    async with tenant_session(p.org_id) as db:
        e = await _own(db, endpoint_id)
        _audit(db, p, "webhook.delete", endpoint_id=str(endpoint_id), url=e.url)
        await db.delete(e)


@router.post("/{endpoint_id}/test", status_code=status.HTTP_202_ACCEPTED)
async def send_test(endpoint_id: uuid.UUID, p: Principal = Depends(require_company_admin)):
    """Queue a `ping` event for this endpoint only, so an administrator can see their receiver work."""
    event_id = uuid.uuid4()
    envelope = {
        "id": str(event_id),
        "type": webhooks.PING,
        "created_at": datetime.now(UTC).isoformat(),
        "data": {"message": "This is a test event from a11y."},
    }
    async with tenant_session(p.org_id) as db:
        await _own(db, endpoint_id)
        did = (
            await db.execute(
                text(
                    "INSERT INTO webhook_deliveries (id, organization_id, endpoint_id, event_id, event_type, payload) "
                    "VALUES (gen_random_uuid(), :o, :ep, :ev, 'ping', CAST(:p AS jsonb)) RETURNING id"
                ),
                {"o": p.org_id, "ep": endpoint_id, "ev": event_id, "p": json.dumps(envelope)},
            )
        ).scalar_one()
    celery_app.send_task("webhooks.deliver", args=[str(p.org_id), str(did)], queue="system")
    return {"delivery_id": str(did)}


@router.get("/{endpoint_id}/deliveries")
async def deliveries(
    endpoint_id: uuid.UUID,
    limit: int = Query(25, ge=1, le=100),
    p: Principal = Depends(require_company_admin),
):
    async with tenant_session(p.org_id) as db:
        await _own(db, endpoint_id)
        rows = (
            await db.execute(
                text(
                    "SELECT id, event_id, event_type, status, attempts, response_status, error, created_at, delivered_at, next_attempt_at "
                    "FROM webhook_deliveries WHERE endpoint_id=:e ORDER BY created_at DESC LIMIT :l"
                ),
                {"e": endpoint_id, "l": limit},
            )
        ).all()
    return [
        {
            "id": str(r.id),
            "event_id": str(r.event_id),
            "event_type": r.event_type,
            "status": r.status,
            "attempts": r.attempts,
            "response_status": r.response_status,
            "error": r.error,
            "created_at": r.created_at,
            "delivered_at": r.delivered_at,
            "next_attempt_at": r.next_attempt_at if r.status == "PENDING" else None,
        }
        for r in rows
    ]


@router.post("/deliveries/{delivery_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_delivery(delivery_id: uuid.UUID, p: Principal = Depends(require_company_admin)):
    async with tenant_session(p.org_id) as db:
        row = (
            await db.execute(
                text(
                    "UPDATE webhook_deliveries SET status='PENDING', attempts=0, next_attempt_at=now(), error=NULL WHERE id=:i AND status='ABANDONED' RETURNING endpoint_id"
                ),
                {"i": delivery_id},
            )
        ).first()
        if row is None:
            raise _problem(
                409, "Only a delivery that was given up on can be retried.", "not_retryable"
            )
        ok = (
            await db.execute(
                text("SELECT enabled FROM webhook_endpoints WHERE id=:i"), {"i": row.endpoint_id}
            )
        ).scalar_one()
        if not ok:
            raise _problem(409, "Switch the webhook back on first.", "endpoint_disabled")
        _audit(db, p, "webhook.retry", delivery_id=str(delivery_id))
    celery_app.send_task("webhooks.deliver", args=[str(p.org_id), str(delivery_id)], queue="system")
    return {"delivery_id": str(delivery_id)}
