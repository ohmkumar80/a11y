"""Web scans: create (quota-reserved, rate-limited, SSRF-checked), list, results, per-standard summary."""

import time
import uuid
from urllib.parse import urldefrag

from a11y_core import billing
from a11y_core.celery_app import celery_app
from a11y_core.config import definitions as _definitions  # noqa: F401
from a11y_core.config import get_config
from a11y_core.db import tenant_session
from a11y_core.rules import get_registry
from a11y_core.scan_jobs import USAGE_FEATURE, fail_scan
from a11y_core.settings import get_settings
from a11y_core.ssrf import BlockedTarget, check_url
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import text

from ..deps import current_principal
from ..security import Principal

router = APIRouter(prefix="/scans", tags=["scans"])
DEFAULT_STANDARD = "WCAG_2_2_AA"
SEV_ORDER = (
    "CASE severity WHEN 'critical' THEN 0 WHEN 'serious' THEN 1 WHEN 'moderate' THEN 2 ELSE 3 END"
)


class ScanIn(BaseModel):
    url: str = Field(max_length=2048)
    standards: list[str] = Field(
        default_factory=lambda: [DEFAULT_STANDARD], min_length=1, max_length=8
    )
    mode: str = Field("single", pattern="^(single|crawl)$")
    max_pages: int | None = Field(None, ge=1, le=2000)


def _problem(http_status: int, detail: str, field: str | None = None, **extra) -> HTTPException:
    return HTTPException(http_status, detail={"detail": detail, "field": field, **extra})


async def _rate_limit(
    org_id: uuid.UUID, per_minute: int, *, bucket: str = "scan", what: str = "scans"
) -> None:
    r = Redis.from_url(get_settings().redis_url)
    try:
        key = f"rl:{bucket}:{org_id}:{int(time.time() // 60)}"
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 90)
    except Exception:  # noqa: BLE001 - if Redis is down we do not block scanning; the concurrency cap still applies
        return
    finally:
        await r.aclose()
    if n > per_minute:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "detail": f"You are starting {what} too quickly. Wait a minute and try again.",
                "code": "rate_limited",
            },
            headers={"Retry-After": "60"},
        )


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_scan(body: ScanIn, p: Principal = Depends(current_principal)):
    reg = get_registry()
    for s in body.standards:
        if s not in reg.standards:
            raise _problem(422, f"Unknown standard {s}.", "standards")
    url = urldefrag(body.url.strip())[0]
    try:
        target = await check_url(url)
    except BlockedTarget as e:
        raise _problem(422, e.message, "url", code=e.code) from None

    cfg = get_config()
    async with tenant_session(p.org_id) as db:
        sub = await billing.load_subscription(db)
        plan_id = sub.plan_id
        ent = await billing.entitlement(db, plan_id, "pages_per_scan")
    s = (await cfg.effective("scan.engines", org_id=p.org_id, plan_id=plan_id)).value

    pages = 1
    if body.mode == "crawl":
        want = body.max_pages or s.unverified_crawl_pages
        limits = [want, s.max_pages_cap] + (
            [ent.limit] if ent.enabled and ent.limit is not None else []
        )
        pages = max(1, min(limits))
        if pages > s.unverified_crawl_pages:
            async with tenant_session(p.org_id) as db:
                ok = (
                    await db.execute(
                        text(
                            "SELECT 1 FROM verified_domains WHERE host=:h AND verified_at IS NOT NULL"
                        ),
                        {"h": target.host},
                    )
                ).first()
            if not ok:
                raise _problem(
                    403,
                    f"To crawl more than {s.unverified_crawl_pages} pages, confirm that you own {target.host} first.",
                    "url",
                    code="domain_not_verified",
                    host=target.host,
                    verify_url="/workspace#domains",
                )
    await _rate_limit(p.org_id, s.creations_per_minute)

    scan_id = uuid.uuid4()
    async with tenant_session(p.org_id) as db:
        # Serialise per organisation so the concurrency cap cannot be raced past.
        await billing.require_writable(db, lock=True)
        running = (
            await db.execute(
                text("SELECT count(*) FROM scan_jobs WHERE status IN ('QUEUED','RUNNING')")
            )
        ).scalar_one()
        if running >= s.max_concurrent_per_org:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "detail": f"{running} scans are already running. Wait for one to finish.",
                    "code": "too_many_scans",
                },
                headers={"Retry-After": "30"},
            )
        await billing.reserve(
            db, p.org_id, USAGE_FEATURE, str(scan_id)
        )  # QuotaExceeded -> 402, nothing is created
        await db.execute(
            text(
                "INSERT INTO scan_jobs (id, organization_id, created_by, start_url, mode, max_pages, standards) "
                "VALUES (:i, :o, :u, :url, :m, :p, :s)"
            ),
            {
                "i": scan_id,
                "o": p.org_id,
                "u": p.user_id,
                "url": url,
                "m": body.mode,
                "p": pages,
                "s": body.standards,
            },
        )
    try:
        celery_app.send_task("web.scan", args=[str(p.org_id), str(scan_id)], queue="web")
    except Exception:  # noqa: BLE001
        await fail_scan(
            p.org_id,
            scan_id,
            "queue_unavailable",
            "We could not start the scan. Your credit was returned. Try again shortly.",
            system_fault=True,
        )
        raise _problem(
            503,
            "We could not start the scan right now. Please try again shortly.",
            code="queue_unavailable",
        ) from None
    return {"id": str(scan_id), "status": "QUEUED", "max_pages": pages}


def _scan_json(r) -> dict:
    return {
        "id": str(r.id),
        "url": r.start_url,
        "mode": r.mode,
        "max_pages": r.max_pages,
        "standards": r.standards,
        "status": r.status,
        "error_code": r.error_code,
        "error_detail": r.error_detail,
        "pages_scanned": r.pages_scanned,
        "findings_count": r.findings_count,
        "created_at": r.created_at,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
    }


@router.get("")
async def list_scans(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    p: Principal = Depends(current_principal),
):
    async with tenant_session(p.org_id) as db:
        rows = (
            await db.execute(
                text("SELECT * FROM scan_jobs ORDER BY created_at DESC LIMIT :l OFFSET :o"),
                {"l": limit, "o": offset},
            )
        ).all()
        total = (await db.execute(text("SELECT count(*) FROM scan_jobs"))).scalar_one()
    return {"total": total, "scans": [_scan_json(r) for r in rows]}


async def _load(db, scan_id: uuid.UUID):
    r = (await db.execute(text("SELECT * FROM scan_jobs WHERE id=:i"), {"i": scan_id})).first()
    if r is None:
        raise _problem(404, "We could not find that scan.")
    return r


def _summary(reg, standard: str, rows) -> dict:
    s = reg.summarise(standard, [{"sc": [r.sc], "kind": r.kind} for r in rows])
    tested, total = s.automated_coverage
    st = reg.standards[standard]
    return {
        "standard": standard,
        "label": st.label,
        "legal_status": st.legal_status,
        "citation": st.citation,
        "notes": st.notes,
        "criteria_total": total,
        "automated_coverage": {"tested": tested, "total": total},
        "failed": s.failed,
        "needs_review": s.needs_review,
        "no_issues_found": s.no_issues_found,
        "not_tested": s.not_tested,
        "review_status": reg.review["status"],
        # Said plainly so no UI can present this as a pass: automation cannot test every criterion.
        "disclaimer": "Automated tests cover only part of WCAG. This is not a statement of conformance.",
    }


@router.get("/{scan_id}")
async def get_scan(
    scan_id: uuid.UUID, standard: str | None = None, p: Principal = Depends(current_principal)
):
    reg = get_registry()
    async with tenant_session(p.org_id) as db:
        job = await _load(db, scan_id)
        pages = (
            await db.execute(
                text(
                    "SELECT id, url, final_url, status, error_code, error_detail, title, http_status, engines FROM scan_pages WHERE scan_id=:i ORDER BY scanned_at"
                ),
                {"i": scan_id},
            )
        ).all()
        rows = (
            await db.execute(
                text(
                    "SELECT DISTINCT unnest(CASE WHEN cardinality(sc)=0 THEN ARRAY[NULL]::text[] ELSE sc END) AS sc, kind FROM scan_findings WHERE scan_id=:i"
                ),
                {"i": scan_id},
            )
        ).all()
        counts = (
            await db.execute(
                text(
                    f"SELECT kind, severity, count(*) n FROM scan_findings WHERE scan_id=:i GROUP BY kind, severity ORDER BY {SEV_ORDER}"
                ),
                {"i": scan_id},
            )
        ).all()
    rows = [r for r in rows if r.sc]
    std = standard or (job.standards[0] if job.standards else DEFAULT_STANDARD)
    if std not in reg.standards:
        raise _problem(422, f"Unknown standard {std}.", "standard")
    return {
        **_scan_json(job),
        "engine_versions": job.engine_versions,
        "rules_version": job.rules_version,
        "attempts": job.attempts,
        "pages": [
            {
                "id": str(x.id),
                "url": x.url,
                "final_url": x.final_url,
                "status": x.status,
                "error_code": x.error_code,
                "error_detail": x.error_detail,
                "title": x.title,
                "http_status": x.http_status,
                "engines": x.engines,
            }
            for x in pages
        ],
        "by_kind": _group_counts(counts),
        "summary": _summary(reg, std, rows),
    }


def _group_counts(counts) -> dict:
    out: dict = {}
    for r in counts:
        out.setdefault(r.kind, {})[r.severity] = r.n
    return out


@router.get("/{scan_id}/findings")
async def findings(
    scan_id: uuid.UUID,
    standard: str | None = None,
    kind: str = Query("violation", pattern="^(violation|needs_review|best_practice)$"),
    severity: str | None = Query(None, pattern="^(critical|serious|moderate|minor)$"),
    rule: str | None = Query(None, max_length=120),
    page_id: uuid.UUID | None = None,
    confidence: str | None = Query(None, pattern="^(high|medium|low|review)$"),
    group: str = Query("none", pattern="^(none|cluster)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    p: Principal = Depends(current_principal),
):
    """Filter by standard re-filters EXISTING data (no rescan): a finding counts toward a standard if
    any of its criteria are in that standard's scope."""
    reg = get_registry()
    where, params = (
        ["f.scan_id = :scan", "f.kind = :kind"],
        {"scan": scan_id, "kind": kind, "l": limit, "o": offset},
    )
    if standard:
        if standard not in reg.standards:
            raise _problem(422, f"Unknown standard {standard}.", "standard")
        params["scs"] = [c.id for c in reg.criteria_for(standard)]
        where.append(
            "(f.sc && CAST(:scs AS varchar[]) OR (cardinality(f.sc) = 0 AND f.kind = 'best_practice'))"
        )
    for col, val in (
        ("severity", severity),
        ("canonical_rule_id", rule),
        ("page_id", page_id),
        ("confidence", confidence),
    ):
        if val is not None:
            where.append(f"f.{col} = :{col}")
            params[col] = val
    w = " AND ".join(where)
    async with tenant_session(p.org_id) as db:
        await _load(db, scan_id)
        if group == "cluster":
            rows = (
                await db.execute(
                    text(
                        f"SELECT f.cluster_key, min(f.canonical_rule_id) AS rule, min(f.title) AS title, min(array_to_string(f.sc, ',')) AS sc, count(*) AS occurrences, "
                        f"count(DISTINCT f.page_id) AS pages, min(CASE f.severity WHEN 'critical' THEN 0 WHEN 'serious' THEN 1 WHEN 'moderate' THEN 2 ELSE 3 END) AS sev, "
                        f"(array_agg(f.html))[1] AS sample_html, (array_agg(f.css))[1] AS sample_css, (array_agg(f.id))[1] AS sample_id "
                        f"FROM scan_findings f WHERE {w} GROUP BY f.cluster_key ORDER BY sev, occurrences DESC LIMIT :l OFFSET :o"
                    ),
                    params,
                )
            ).all()
            total = (
                await db.execute(
                    text(f"SELECT count(DISTINCT f.cluster_key) FROM scan_findings f WHERE {w}"),
                    params,
                )
            ).scalar_one()
            sev_name = ["critical", "serious", "moderate", "minor"]
            return {
                "total": total,
                "clusters": [
                    {
                        "cluster_key": r.cluster_key,
                        "rule": r.rule,
                        "title": r.title,
                        "sc": r.sc,
                        "occurrences": r.occurrences,
                        "pages": r.pages,
                        "severity": sev_name[r.sev],
                        "sample": {
                            "id": str(r.sample_id),
                            "html": r.sample_html,
                            "css": r.sample_css,
                        },
                    }
                    for r in rows
                ],
            }
        rows = (
            await db.execute(
                text(
                    f"SELECT f.*, pg.url AS page_url FROM scan_findings f JOIN scan_pages pg ON pg.id = f.page_id WHERE {w} "
                    f"ORDER BY CASE f.severity WHEN 'critical' THEN 0 WHEN 'serious' THEN 1 WHEN 'moderate' THEN 2 ELSE 3 END, f.canonical_rule_id, f.xpath LIMIT :l OFFSET :o"
                ),
                params,
            )
        ).all()
        total = (
            await db.execute(text(f"SELECT count(*) FROM scan_findings f WHERE {w}"), params)
        ).scalar_one()
    std = standard or DEFAULT_STANDARD
    return {
        "total": total,
        "findings": [
            {
                "id": str(r.id),
                "rule": r.canonical_rule_id,
                "title": r.title,
                "kind": r.kind,
                "severity": r.severity,
                "confidence": r.confidence,
                "criteria": [
                    {
                        "id": c,
                        "name": reg.criteria[c].name,
                        "level": reg.criteria[c].level,
                        "clause": reg.clause(std, c),
                    }
                    for c in r.sc
                    if c in reg.criteria
                ],
                "engines": r.engines,
                "engines_covering": r.covering,
                "agreement": f"{len(r.engines)} of {max(len(r.covering), len(r.engines))} engines",
                "message": r.message,
                "element": {"xpath": r.xpath, "css": r.css, "tag": r.tag, "html": r.html},
                "page": {"id": str(r.page_id), "url": r.page_url},
                "help_url": r.help_url,
                "cluster_key": r.cluster_key,
            }
            for r in rows
        ],
    }


@router.get("/{scan_id}/summary")
async def summary(
    scan_id: uuid.UUID,
    standard: str = Query(DEFAULT_STANDARD),
    p: Principal = Depends(current_principal),
):
    """Recomputed from stored findings, so switching standard needs no rescan."""
    reg = get_registry()
    if standard not in reg.standards:
        raise _problem(422, f"Unknown standard {standard}.", "standard")
    async with tenant_session(p.org_id) as db:
        await _load(db, scan_id)
        rows = (
            await db.execute(
                text("SELECT DISTINCT unnest(sc) AS sc, kind FROM scan_findings WHERE scan_id=:i"),
                {"i": scan_id},
            )
        ).all()
    return _summary(reg, standard, rows)
