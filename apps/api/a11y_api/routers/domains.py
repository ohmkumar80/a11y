"""Domain verification: prove the organisation controls a site before large crawls (PROJECT_PLAN 3.6).

Two ways, either is enough:
  file  - serve the token at https://<host>/.well-known/a11y-verification.txt
  meta  - add <meta name="a11y-verification" content="<token>"> to the home page
The check refuses internal addresses (SSRF), never follows redirects to another host, and reads at
most 64 KB."""

import re
import secrets
import uuid
from datetime import UTC, datetime

import httpx
from a11y_core.db import tenant_session
from a11y_core.ssrf import BlockedTarget, check_url, parse_url
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..deps import require_company_admin
from ..security import Principal

router = APIRouter(prefix="/domains", tags=["domains"])
MAX_BYTES = 64 * 1024
META = re.compile(
    r"""<meta\s+[^>]*name=["']a11y-verification["'][^>]*content=["']([^"']+)["']""", re.I
)
META_REV = re.compile(
    r"""<meta\s+[^>]*content=["']([^"']+)["'][^>]*name=["']a11y-verification["']""", re.I
)


class DomainIn(BaseModel):
    host: str = Field(min_length=3, max_length=2048, description="A host name or a full address")


def _problem(http_status: int, detail: str, field: str | None = None, **extra) -> HTTPException:
    return HTTPException(http_status, detail={"detail": detail, "field": field, **extra})


def _json(r) -> dict:
    t = r.token
    return {
        "id": str(r.id),
        "host": r.host,
        "verified": r.verified_at is not None,
        "verified_at": r.verified_at,
        "method": r.method,
        "instructions": {
            "file": {"url": f"https://{r.host}/.well-known/a11y-verification.txt", "content": t},
            "meta": {"tag": f'<meta name="a11y-verification" content="{t}">'},
        },
    }


@router.get("")
async def list_domains(p: Principal = Depends(require_company_admin)):
    async with tenant_session(p.org_id) as db:
        rows = (
            await db.execute(text("SELECT * FROM verified_domains ORDER BY created_at DESC"))
        ).all()
    return [_json(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_domain(body: DomainIn, p: Principal = Depends(require_company_admin)):
    raw = body.host.strip()
    try:
        _, host, _ = parse_url(raw if "://" in raw else f"https://{raw}")
    except BlockedTarget as e:
        raise _problem(422, e.message, "host", code=e.code) from None
    async with tenant_session(p.org_id) as db:
        row = (
            await db.execute(
                text(
                    "INSERT INTO verified_domains (id, organization_id, host, token) VALUES (:i, :o, :h, :t) ON CONFLICT (organization_id, host) DO UPDATE SET host = EXCLUDED.host RETURNING *"
                ),
                {
                    "i": uuid.uuid4(),
                    "o": p.org_id,
                    "h": host,
                    "t": "a11y-" + secrets.token_urlsafe(24),
                },
            )
        ).first()
    return _json(row)


async def _fetch(url: str) -> str | None:
    """Fetch with the SSRF checks; same host only, no redirects, size-capped."""
    try:
        await check_url(url)
        async with (
            httpx.AsyncClient(
                timeout=8, follow_redirects=False, headers={"user-agent": "a11y-verifier/0.1"}
            ) as c,
            c.stream("GET", url) as r,
        ):
            if r.status_code != 200:
                return None
            buf = b""
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_BYTES:
                    break
            return buf[:MAX_BYTES].decode("utf-8", "replace")
    except (BlockedTarget, httpx.HTTPError):
        return None


@router.post("/{domain_id}/verify")
async def verify(domain_id: uuid.UUID, p: Principal = Depends(require_company_admin)):
    async with tenant_session(p.org_id) as db:
        row = (
            await db.execute(text("SELECT * FROM verified_domains WHERE id=:i"), {"i": domain_id})
        ).first()
    if row is None:
        raise _problem(404, "We could not find that domain.")
    method = None
    for scheme in ("https", "http"):
        body = await _fetch(f"{scheme}://{row.host}/.well-known/a11y-verification.txt")
        if body is not None and body.strip() == row.token:
            method = "file"
            break
        page = await _fetch(f"{scheme}://{row.host}/")
        if page and any(
            m.group(1) == row.token for m in (*META.finditer(page), *META_REV.finditer(page))
        ):
            method = "meta"
            break
    if method is None:
        raise _problem(
            422,
            f"We could not find the verification code on {row.host}. Add the file or the tag, then try again.",
            "host",
            code="verification_failed",
        )
    async with tenant_session(p.org_id) as db:
        row = (
            await db.execute(
                text(
                    "UPDATE verified_domains SET verified_at=:n, method=:m WHERE id=:i RETURNING *"
                ),
                {"n": datetime.now(UTC), "m": method, "i": domain_id},
            )
        ).first()
    return _json(row)


@router.delete("/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove(domain_id: uuid.UUID, p: Principal = Depends(require_company_admin)):
    async with tenant_session(p.org_id) as db:
        await db.execute(text("DELETE FROM verified_domains WHERE id=:i"), {"i": domain_id})
