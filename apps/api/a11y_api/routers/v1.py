"""The public API, version 1 (PROJECT_PLAN 3.17).

Server-to-server, authenticated with an API key (``Authorization: Bearer a11y_...``). It delegates to the same code the
web app uses, so a scan started here is billed, rate-limited, isolated per organisation and validated exactly like one
started in the browser. Each endpoint names the scope it needs; ``POST`` endpoints accept an ``Idempotency-Key`` so a
retried request never starts a second scan."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from a11y_core import api_keys, billing
from a11y_core.config import get_config
from a11y_core.db import tenant_session
from a11y_core.models import AuditLog
from a11y_core.rules import get_registry
from a11y_core.scan_jobs import USAGE_FEATURE
from a11y_core.settings import get_settings
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy import select, text

from ..api_auth import ApiCaller, any_valid_key, require_scope
from ..security import Principal
from . import documents as documents_router
from . import reports as reports_router
from . import scans as scans_router

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1")
VERSION = "1.0.0"


# -- shapes ----------------------------------------------------------------------------------------
class Problem(BaseModel):
    """Every error has this shape."""

    detail: str = Field(description="What went wrong, in words you can show to a person")
    code: str | None = Field(
        None, description="A stable machine-readable code, for example `quota_exceeded`"
    )
    field: str | None = Field(
        None, description="The request field the problem is about, when there is one"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "You have used 10 of 10 this month. Upgrade your plan for more.",
                "code": "quota_exceeded",
            }
        }
    )


ERRORS: dict[int | str, dict[str, Any]] = {
    401: {
        "model": Problem,
        "description": "The API key is missing, wrong, revoked or expired (`invalid_api_key`).",
    },
    403: {
        "model": Problem,
        "description": "The key lacks the required scope (`scope_missing`), or the plan has no API access (`api_not_in_plan`).",
    },
    429: {
        "model": Problem,
        "description": "Too many requests (`rate_limited`). Wait for `Retry-After` seconds.",
    },
}


class ScanIn(scans_router.ScanIn):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://www.example.com/",
                "standards": ["WCAG_2_2_AA"],
                "mode": "single",
            }
        }
    )


class ScanOut(BaseModel):
    id: uuid.UUID
    url: str
    mode: str = Field(description="`single` or `crawl`")
    max_pages: int
    standards: list[str]
    status: str = Field(description="`QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED` or `CANCELLED`")
    error_code: str | None = None
    error_detail: str | None = None
    pages_scanned: int
    findings_count: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ScanList(BaseModel):
    total: int
    scans: list[ScanOut]


class ScanCreated(BaseModel):
    id: uuid.UUID
    status: str = "QUEUED"
    max_pages: int


class ScanDetail(ScanOut):
    engine_versions: dict[str, str] = Field(default_factory=dict)
    rules_version: str | None = None
    pages: list[dict[str, Any]] = Field(description="Each page scanned, with its result")
    by_kind: dict[str, dict[str, int]] = Field(
        description="Counts by kind (violation, needs_review, best_practice) and severity"
    )
    summary: dict[str, Any] = Field(
        description="Automated coverage of the chosen standard. Never a statement of conformance."
    )


class Finding(BaseModel):
    id: uuid.UUID
    rule: str = Field(description="Our canonical rule id, stable across engines")
    title: str
    kind: str = Field(description="`violation`, `needs_review` or `best_practice`")
    severity: str = Field(description="`critical`, `serious`, `moderate` or `minor`")
    confidence: str = Field(description="`high`, `medium`, `low` or `review`")
    criteria: list[dict[str, Any]]
    engines: list[str]
    message: str
    element: dict[str, Any] = Field(
        description="xpath, css, tag, html (the opening tag) and rect in page pixels"
    )
    page: dict[str, Any]
    help_url: str | None = None
    cluster_key: str


class FindingList(BaseModel):
    total: int
    findings: list[Finding] | None = None
    clusters: list[dict[str, Any]] | None = Field(None, description="Present when `group=cluster`")


class ReportIn(reports_router.ReportIn):
    model_config = ConfigDict(
        json_schema_extra={"example": {"kind": "audit_pdf", "standard": "WCAG_2_2_AA"}}
    )


class ReportCreated(BaseModel):
    id: uuid.UUID
    status: str = "QUEUED"
    reused: bool = Field(description="True when an identical, current report already existed")


class ReportOut(BaseModel):
    id: uuid.UUID
    scan_id: uuid.UUID
    kind: str
    standard: str
    status: str = Field(description="`QUEUED`, `RUNNING`, `READY` or `FAILED`")
    error_detail: str | None = None
    size_bytes: int | None = None
    validation: dict[str, Any] = Field(
        description="The accessibility check the file passed before it was offered"
    )
    created_at: datetime
    finished_at: datetime | None = None


class Me(BaseModel):
    organization: dict[str, str]
    key: dict[str, Any]
    plan: str
    rate_limit_per_minute: int
    scans_used_this_month: int
    scans_allowed_this_month: int | None = Field(description="Null = unlimited")


class AuditEvent(BaseModel):
    id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None
    detail: dict[str, Any]
    created_at: datetime


class AuditList(BaseModel):
    events: list[AuditEvent]
    next_before: datetime | None = Field(
        description="Pass as `before` to get the next page; null at the end"
    )


class AuditOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    standard: str = Field(description="`PDF_UA_1`")
    status: str = Field(description="`QUEUED`, `RUNNING`, `SUCCEEDED` or `FAILED`")
    pages: int = Field(
        description="Document pages this check uses from the plan's monthly allowance"
    )
    summary: dict[str, Any] = Field(
        description="Counts by severity, whether anything was found, facts about the file and a `caveat`; empty until the check has finished"
    )
    error_code: str | None = None
    error_detail: str | None = Field(
        None, description="Why a failed check failed, in words you can show to a person"
    )
    created_at: datetime
    finished_at: datetime | None = None


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    kind: str = Field(description="`pdf`, `docx`, `pptx` or `epub`")
    size_bytes: int
    status: str = Field(
        description="`UPLOADED` and `SCANNING` (being virus-scanned and inspected), `CLEAN` (ready), `REJECTED` (the file failed a check, see `reject_detail`) or `FAILED` (a problem on our side)"
    )
    reject_code: str | None = None
    reject_detail: str | None = None
    page_count: int | None = None
    created_at: datetime
    scanned_at: datetime | None = None
    expires_at: datetime = Field(description="When the file will be deleted (retention)")
    ready: bool = Field(description="True once the file has passed every safety check")
    latest_audit: AuditOut | None = None


class DocFindingOut(BaseModel):
    id: uuid.UUID
    rule_id: str
    source: str = Field(description="`verapdf` (the PDF/UA-1 checker) or `direct` (our own check)")
    severity: str = Field(description="`critical`, `serious`, `moderate` or `minor`")
    title: str
    explanation: str
    how_to_fix: str
    wcag: list[str] = Field(description="WCAG success criteria this relates to")
    needs_human: bool = Field(description="True when a person has to judge or write the fix")
    count: int = Field(description="How many places in the file")
    pages: list[int] = Field(description="The first pages affected, when the checker knows them")
    pages_total: int
    examples: list[dict[str, Any]]
    explained: bool = Field(description="False for a check we do not yet explain in plain language")


class DocumentAuditDetail(AuditOut):
    document: dict[str, Any]
    findings: list[DocFindingOut]


def op(scope: str | None, summary: str, description: str = "") -> dict[str, Any]:
    note = f"\n\n**Required scope:** `{scope}`." if scope else "\n\nAny valid API key."
    return {
        "summary": summary,
        "description": description + note,
        "responses": ERRORS,
        "openapi_extra": {"x-required-scope": scope} if scope else {},
    }


# -- idempotency -----------------------------------------------------------------------------------
class Idem:
    """``Idempotency-Key``: the first request with a key does the work and its answer is kept for 24 hours; a repeat gets
    that answer back (with ``Idempotent-Replay: true``) instead of doing the work again."""

    def __init__(self, org: uuid.UUID, route: str, key: str | None) -> None:
        self.rk = f"idem:{org}:{route}:{key}" if key else None
        self.replay: Any = None

    async def start(self) -> None:
        if not self.rk:
            return
        r = Redis.from_url(get_settings().redis_url)
        try:
            if await r.set(self.rk, "PENDING", nx=True, ex=120):
                return
            cur = await r.get(self.rk)
        except Exception:  # noqa: BLE001 - without Redis we simply cannot de-duplicate
            self.rk = None
            return
        finally:
            await r.aclose()
        if cur in (None, b"PENDING"):
            raise HTTPException(
                409,
                detail={
                    "detail": "A request with this Idempotency-Key is still being processed. Try again in a moment.",
                    "code": "idempotency_in_progress",
                },
            )
        self.replay = json.loads(cur)

    async def finish(self, body: Any, *, ok: bool) -> None:
        if not self.rk:
            return
        r = Redis.from_url(get_settings().redis_url)
        try:
            if ok:
                await r.set(self.rk, json.dumps(body, default=str), ex=86400)
            else:
                await r.delete(self.rk)  # a failed attempt can be retried with the same key
        except Exception:  # noqa: BLE001
            log.warning("idempotency store unavailable")
        finally:
            await r.aclose()


def idem_key(value: str | None) -> str | None:
    if value is None:
        return None
    if not (1 <= len(value) <= 80) or not value.isprintable():
        raise HTTPException(
            422,
            detail={
                "detail": "Idempotency-Key must be 1 to 80 printable characters.",
                "code": "invalid_idempotency_key",
            },
        )
    return value


IDEM_HEADER = Header(
    None,
    alias="Idempotency-Key",
    description="Any unique string (for example a UUID), up to 80 characters. Repeat it when you retry.",
)


# -- endpoints -------------------------------------------------------------------------------------
@router.get(
    "/me",
    response_model=Me,
    tags=["Account"],
    **op(
        None,
        "Who this key is",
        "Returns the organisation, the key's scopes, the rate limit and this month's scan usage.",
    ),
)
async def me(caller: ApiCaller = Depends(any_valid_key)):
    p = caller.principal
    async with tenant_session(p.org_id) as db:
        sub = await billing.load_subscription(db)
        ent = await billing.entitlement(db, sub.plan_id, USAGE_FEATURE)
        used = await billing.usage_used(db, USAGE_FEATURE)
        k = (
            await db.execute(
                text("SELECT id, name, scopes, expires_at, created_at FROM api_keys WHERE id=:i"),
                {"i": caller.key_id},
            )
        ).first()
        org = (await db.execute(text("SELECT name FROM organizations"))).scalar_one()
    lim = (await get_config().effective("api.limits", org_id=p.org_id, plan_id=sub.plan_id)).value
    return {
        "organization": {"id": str(p.org_id), "name": org},
        "key": {
            "id": str(k.id),
            "name": k.name,
            "scopes": list(k.scopes),
            "expires_at": k.expires_at,
            "created_at": k.created_at,
        },
        "plan": sub.plan_id,
        "rate_limit_per_minute": lim.requests_per_minute,
        "scans_used_this_month": used,
        "scans_allowed_this_month": ent.limit if ent.enabled else 0,
    }


@router.get(
    "/standards",
    tags=["Scans"],
    **op(
        "scans:read",
        "List the standards a scan can be evaluated against",
        "Each has a legal status and, until an accessibility expert signs the mapping off, `review.status` is `draft`.",
    ),
)
async def standards(_: Principal = Depends(require_scope("scans:read"))):
    reg = get_registry()
    return {
        "review": reg.review | {"version": reg.standards_version},
        "standards": [
            {"id": s.id, "label": s.label, "legal_status": s.legal_status, "citation": s.citation}
            for s in reg.standards.values()
        ],
    }


@router.get(
    "/scans",
    response_model=ScanList,
    tags=["Scans"],
    **op("scans:read", "List scans", "Newest first."),
)
async def list_scans(
    limit: int = Query(25, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0),
    p: Principal = Depends(require_scope("scans:read")),
):
    return await scans_router.list_scans(limit=limit, offset=offset, p=p)


@router.post(
    "/scans",
    status_code=202,
    response_model=ScanCreated,
    tags=["Scans"],
    **op(
        "scans:write",
        "Start a scan",
        "Starts a scan of one page or a bounded crawl. It uses one scan credit and is checked like a scan started in the app: the address must be public, crawls above the unverified limit need a verified site, and your plan's quota and rate limits apply. Poll `GET /v1/scans/{id}` until `status` is `SUCCEEDED` or `FAILED`.",
    ),
)
async def create_scan(
    body: ScanIn,
    response: Response,
    p: Principal = Depends(require_scope("scans:write")),
    idempotency_key: str | None = IDEM_HEADER,
):
    idem = Idem(p.org_id, "scans", idem_key(idempotency_key))
    await idem.start()
    if idem.replay is not None:
        response.headers["Idempotent-Replay"] = "true"
        return idem.replay
    try:
        out = await scans_router.create_scan(scans_router.ScanIn(**body.model_dump()), p)
    except BaseException:
        await idem.finish(None, ok=False)
        raise
    await idem.finish(out, ok=True)
    return out


@router.get(
    "/scans/{scan_id}",
    response_model=ScanDetail,
    tags=["Scans"],
    **op(
        "scans:read",
        "Get a scan",
        "Status, pages scanned, counts by kind and severity, and the automated coverage summary.",
    ),
)
async def get_scan(
    scan_id: uuid.UUID,
    standard: str | None = Query(
        None, description="Re-evaluate the summary against another standard, with no rescan"
    ),
    p: Principal = Depends(require_scope("scans:read")),
):
    return await scans_router.get_scan(scan_id, standard, p)


@router.get(
    "/scans/{scan_id}/findings",
    response_model=FindingList,
    response_model_exclude_none=True,
    tags=["Scans"],
    **op(
        "scans:read",
        "List a scan's findings",
        "Filter by kind, severity, rule, confidence or page. `group=cluster` groups identical problems found on many pages into one root cause.",
    ),
)
async def list_findings(
    scan_id: uuid.UUID,
    standard: str | None = Query(None),
    kind: str = Query("violation", pattern="^(violation|needs_review|best_practice)$"),
    severity: str | None = Query(None, pattern="^(critical|serious|moderate|minor)$"),
    rule: str | None = Query(None, max_length=120),
    page_id: uuid.UUID | None = None,
    confidence: str | None = Query(None, pattern="^(high|medium|low|review)$"),
    group: str = Query("none", pattern="^(none|cluster)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    p: Principal = Depends(require_scope("scans:read")),
):
    return await scans_router.findings(
        scan_id, standard, kind, severity, rule, page_id, confidence, group, limit, offset, p
    )


@router.get(
    "/scans/{scan_id}/summary",
    tags=["Scans"],
    **op(
        "scans:read",
        "Automated coverage summary",
        "Which criteria failed, need review, found no issue, or cannot be tested automatically. It is never a pass/fail or a score.",
    ),
)
async def scan_summary(
    scan_id: uuid.UUID,
    standard: str = Query(scans_router.DEFAULT_STANDARD),
    p: Principal = Depends(require_scope("scans:read")),
):
    return await scans_router.summary(scan_id, standard, p)


@router.post(
    "/scans/{scan_id}/reports",
    status_code=202,
    response_model=ReportCreated,
    tags=["Reports"],
    **op(
        "reports:write",
        "Create a report",
        "Renders an accessible PDF (checked against PDF/UA), a Word file (structure-checked) or a CSV. A file that fails its accessibility check is never offered. Poll `GET /v1/reports/{id}` until `READY`.",
    ),
)
async def create_report(
    scan_id: uuid.UUID,
    body: ReportIn,
    response: Response,
    p: Principal = Depends(require_scope("reports:write")),
    idempotency_key: str | None = IDEM_HEADER,
):
    idem = Idem(p.org_id, f"reports:{scan_id}", idem_key(idempotency_key))
    await idem.start()
    if idem.replay is not None:
        response.headers["Idempotent-Replay"] = "true"
        return idem.replay
    try:
        out = await reports_router.create_report(
            scan_id, reports_router.ReportIn(**body.model_dump()), p
        )
    except BaseException:
        await idem.finish(None, ok=False)
        raise
    await idem.finish(out, ok=True)
    return out


@router.get(
    "/scans/{scan_id}/reports",
    response_model=list[ReportOut],
    tags=["Reports"],
    **op("reports:read", "List a scan's reports"),
)
async def list_reports(scan_id: uuid.UUID, p: Principal = Depends(require_scope("reports:read"))):
    return await reports_router.list_reports(scan_id, p)


@router.get(
    "/reports/{report_id}",
    response_model=ReportOut,
    tags=["Reports"],
    **op("reports:read", "Get a report's status"),
)
async def get_report(report_id: uuid.UUID, p: Principal = Depends(require_scope("reports:read"))):
    return await reports_router.get_report(report_id, p)


@router.get(
    "/reports/{report_id}/download",
    tags=["Reports"],
    response_class=Response,
    responses={
        200: {
            "description": "The file",
            "content": {
                "application/pdf": {},
                "text/csv": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
            },
        },
        **ERRORS,
    },
    summary="Download a finished report",
    description="Only a report with status `READY` can be downloaded.\n\n**Required scope:** `reports:read`.",
    openapi_extra={"x-required-scope": "reports:read"},
)
async def download_report(
    report_id: uuid.UUID, p: Principal = Depends(require_scope("reports:read"))
):
    return await reports_router.download(report_id, p)


# -- documents -------------------------------------------------------------------------------------
@router.post(
    "/documents",
    status_code=202,
    response_model=DocumentOut,
    tags=["Documents"],
    responses=ERRORS
    | {
        413: {"model": Problem, "description": "The file is larger than your limit (`too_large`)."},
        415: {
            "model": Problem,
            "description": "A file type that is not accepted (`unsupported_type`).",
        },
        422: {
            "model": Problem,
            "description": "The file was refused: not what its name says, empty, or unsafe (`type_mismatch`, `empty`, `zip_bomb`...).",
        },
    },
    summary="Upload a document",
    description="Send the file itself as the request body (`Content-Type: application/octet-stream`) and its name in `filename`. "
    "The file is encrypted at rest and held until it has been virus-scanned and inspected: poll `GET /v1/documents/{id}` until `status` is `CLEAN` "
    "(or `REJECTED`, with the reason in `reject_detail`). Nothing can read it before then.\n\n**Required scope:** `documents:write`.",
    openapi_extra={
        "x-required-scope": "documents:write",
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        },
    },
)
async def upload_document(
    request: Request,
    response: Response,
    filename: str = Query(
        ..., min_length=1, max_length=255, description="The file's name, with its extension"
    ),
    p: Principal = Depends(require_scope("documents:write")),
    idempotency_key: str | None = IDEM_HEADER,
):
    idem = Idem(p.org_id, "documents:upload", idem_key(idempotency_key))
    await idem.start()
    if idem.replay is not None:
        response.headers["Idempotent-Replay"] = "true"
        return idem.replay
    try:
        out = await documents_router.upload(request, filename, p)
    except BaseException:
        await idem.finish(None, ok=False)
        raise
    await idem.finish(out, ok=True)
    return out


@router.get(
    "/documents",
    response_model=list[DocumentOut],
    tags=["Documents"],
    **op("documents:read", "List documents", "Newest first, without erased files."),
)
async def list_documents(
    limit: int = Query(50, ge=1, le=200), p: Principal = Depends(require_scope("documents:read"))
):
    return await documents_router.list_documents(limit, p)


@router.get(
    "/documents/{document_id}",
    response_model=DocumentOut,
    tags=["Documents"],
    **op(
        "documents:read",
        "Get a document",
        "Includes the latest accessibility check, if there is one.",
    ),
)
async def get_document(
    document_id: uuid.UUID, p: Principal = Depends(require_scope("documents:read"))
):
    return await documents_router.get_one(document_id, p)


@router.get(
    "/documents/{document_id}/download",
    tags=["Documents"],
    response_class=Response,
    responses={
        200: {"description": "The original file", "content": {"application/octet-stream": {}}},
        **ERRORS,
    },
    summary="Download the original file",
    description="Only a document that has passed its safety checks (`status` `CLEAN`) can be downloaded.\n\n**Required scope:** `documents:read`.",
    openapi_extra={"x-required-scope": "documents:read"},
)
async def download_document(
    document_id: uuid.UUID, p: Principal = Depends(require_scope("documents:read"))
):
    return await documents_router.download(document_id, p)


@router.delete(
    "/documents/{document_id}",
    status_code=204,
    tags=["Documents"],
    response_class=Response,
    **op(
        "documents:write",
        "Delete a document",
        "Erases the file and its encryption key at once, together with the results of its checks. This cannot be undone.",
    ),
)
async def delete_document(
    document_id: uuid.UUID, p: Principal = Depends(require_scope("documents:write"))
):
    return await documents_router.delete(document_id, p)


@router.post(
    "/documents/{document_id}/audits",
    status_code=202,
    response_model=AuditOut,
    tags=["Documents"],
    **op(
        "documents:write",
        "Check a PDF for accessibility",
        "Checks a `CLEAN` PDF against PDF/UA-1. The document's pages are reserved from the plan's monthly allowance when you ask (a plan limit is reported as `quota_exceeded`), "
        "and given back if the check fails because of a problem on our side. Poll the audit until `SUCCEEDED`, then read its findings. "
        "A clean result means the automated checks found nothing; it is never a statement of conformance.",
    ),
)
async def start_document_audit(
    document_id: uuid.UUID,
    response: Response,
    p: Principal = Depends(require_scope("documents:write")),
    idempotency_key: str | None = IDEM_HEADER,
):
    idem = Idem(p.org_id, f"documents:audit:{document_id}", idem_key(idempotency_key))
    await idem.start()
    if idem.replay is not None:
        response.headers["Idempotent-Replay"] = "true"
        return idem.replay
    try:
        out = await documents_router.start_audit(document_id, p)
    except BaseException:
        await idem.finish(None, ok=False)
        raise
    await idem.finish(out, ok=True)
    return out


@router.get(
    "/documents/{document_id}/audits",
    response_model=list[AuditOut],
    tags=["Documents"],
    **op("documents:read", "List a document's accessibility checks", "Newest first."),
)
async def list_document_audits(
    document_id: uuid.UUID, p: Principal = Depends(require_scope("documents:read"))
):
    return await documents_router.list_audits(document_id, p)


@router.get(
    "/documents/{document_id}/audits/{audit_id}",
    response_model=DocumentAuditDetail,
    tags=["Documents"],
    **op(
        "documents:read",
        "Get an accessibility check with its findings",
        "Findings are worst first, each with a plain-language explanation and how to fix it. `summary.caveat` says what automated checks cannot judge.",
    ),
)
async def get_document_audit(
    document_id: uuid.UUID,
    audit_id: uuid.UUID,
    p: Principal = Depends(require_scope("documents:read")),
):
    return await documents_router.get_audit(document_id, audit_id, p)


@router.get(
    "/audit-log",
    response_model=AuditList,
    tags=["Account"],
    **op(
        "audit:read",
        "Read the organisation's audit log",
        "Security-relevant events, newest first: key and member changes, sign-offs, settings. Page backwards with `before`.",
    ),
)
async def audit_log(
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = Query(None, description="Only events older than this timestamp"),
    action: str | None = Query(
        None, max_length=100, description="Only this kind of event, for example `api_key.create`"
    ),
    p: Principal = Depends(require_scope("audit:read")),
):
    async with tenant_session(p.org_id) as db:
        q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit + 1)
        if before:
            q = q.where(AuditLog.created_at < before)
        if action:
            q = q.where(AuditLog.action == action)
        rows = (await db.execute(q)).scalars().all()
    page, more = rows[:limit], len(rows) > limit
    return {
        "events": [
            {
                "id": r.id,
                "action": r.action,
                "actor_user_id": r.actor_user_id,
                "detail": r.detail,
                "created_at": r.created_at,
            }
            for r in page
        ],
        "next_before": page[-1].created_at if more and page else None,
    }


# -- the published description of /v1 only ---------------------------------------------------------
DESCRIPTION = """
The a11y API lets you start accessibility scans, read their findings and download accessible reports from your own systems.

**Authentication.** Create a key in the app under *Organisation → API keys*, then send it as
`Authorization: Bearer a11y_...`. A key has *scopes* (shown on each endpoint) and works only for your organisation.
The key is shown once. Keep it secret; revoke it in the app if it leaks.

**Errors.** Every error has the shape `{"detail": "...", "code": "...", "field": "..."}`. `detail` is written for people;
`code` is stable for programs.

**Limits.** Each key has a rate limit (see `X-RateLimit-*` headers and `GET /v1/me`). Starting a scan uses one scan credit.

**Retries.** Send an `Idempotency-Key` header on `POST` requests; repeating it returns the original answer instead of
starting a second scan.

**What a scan result means.** Automated tests cover only part of WCAG. Results are never a statement of conformance.
"""


def v1_openapi(app) -> dict:
    routes = [r for r in router.routes if getattr(r, "include_in_schema", True)]
    schema = get_openapi(
        title="a11y API",
        version=VERSION,
        description=DESCRIPTION.strip(),
        routes=routes,
        tags=[{"name": "Account"}, {"name": "Scans"}, {"name": "Reports"}],
    )
    schema["components"] = schema.get("components", {})
    schema["components"]["securitySchemes"] = {
        "apiKey": {"type": "http", "scheme": "bearer", "bearerFormat": "a11y API key"}
    }
    schema["security"] = [{"apiKey": []}]
    schema["servers"] = [
        {"url": get_settings().public_api_url or "/", "description": "This environment"}
    ]
    for path in schema["paths"].values():
        for operation in path.values():
            operation.setdefault("security", [{"apiKey": []}])
    return schema


@router.get("/openapi.json", include_in_schema=False)
async def openapi_json(request: Request):
    return v1_openapi(request.app)


# Re-exported so tests and the key-management router share one definition.
__all__ = ["router", "v1_openapi", "api_keys"]
