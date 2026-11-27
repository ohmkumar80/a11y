"""Report data: a deterministic snapshot of a finished scan, shaped for templates.

Everything a report says comes from here. There is no model call anywhere in this module: narrative text
is built from the numbers, so a report is reproducible and costs no tokens (PROJECT_PLAN 3.14)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

from a11y_core.rules import get_registry
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SEVERITIES = ("critical", "serious", "moderate", "minor")
MAX_CLUSTERS = 150  # keep reports readable; the CSV has every finding
MAX_EXAMPLES = 3


class CriterionRef(BaseModel):
    id: str
    name: str
    level: str
    clause: str


class Example(BaseModel):
    page: str
    css: str
    html: str
    message: str


class ClusterRow(BaseModel):
    rule: str
    title: str
    criteria: list[CriterionRef]
    severity: str
    kind: str
    occurrences: int
    pages: int
    confidence: str
    agreement: str
    examples: list[Example]


class PageRow(BaseModel):
    url: str
    result: str


class StandardInfo(BaseModel):
    id: str
    label: str
    legal_status: str
    legal_label: str
    citation: str | None = None
    notes: str | None = None
    mapping_review: str


class CriteriaBuckets(BaseModel):
    failed: list[CriterionRef]
    needs_review: list[CriterionRef]
    no_issues_found: list[CriterionRef]
    not_tested: list[CriterionRef]
    tested: int
    total: int


class AuditReportData(BaseModel):
    organization: str
    site: str
    site_host: str
    generated_on: str
    scanned_on: str
    standard: StandardInfo
    engine_versions: dict[str, str]
    rules_version: str
    mode: str
    pages_scanned: int
    severity_counts: dict[str, int]
    failures: int
    needs_review: int
    best_practices: int
    criteria: CriteriaBuckets
    clusters: list[ClusterRow]
    clusters_total: int
    pages: list[PageRow]
    narrative: list[str]
    template_version: str = ""


LEGAL_LABEL = {
    "regulation": "A legal requirement",
    "benchmark": "A benchmark commonly used in legal settlements; not itself a legal requirement",
    "recommended_target": "A recommended target; not a legal requirement",
    "reference": "A reference standard",
    "informational": "Informational only",
}
CONF_LABEL = {"high": "High", "medium": "Medium", "low": "Low", "review": "Needs review"}


def _crit(reg, standard_id: str, sc: str) -> CriterionRef:
    c = reg.criteria[sc]
    return CriterionRef(id=sc, name=c.name, level=c.level, clause=reg.clause(standard_id, sc))


def build_narrative(d: AuditReportData) -> list[str]:
    """Plain sentences from the numbers only. Every figure here is also in the tables (a test checks it)."""
    n = d.pages_scanned
    out = [
        f"On {d.scanned_on} we scanned {n} {'page' if n == 1 else 'pages'} of {d.site_host} with three automated accessibility engines "
        f"and checked the results against {d.standard.label}."
    ]
    if d.failures:
        sev = ", ".join(
            f"{d.severity_counts.get(s, 0)} {s}" for s in SEVERITIES if d.severity_counts.get(s)
        )
        out.append(
            f"The tests reported {d.failures} {'failure' if d.failures == 1 else 'failures'} ({sev}) caused by {d.clusters_total} distinct "
            f"{'problem' if d.clusters_total == 1 else 'problems'}."
        )
        top = max(d.clusters, key=lambda c: c.occurrences) if d.clusters else None
        if top and top.kind == "violation":
            out.append(
                f'The most widespread problem is "{top.title}", with {top.occurrences} '
                f"{'occurrence' if top.occurrences == 1 else 'occurrences'} on {top.pages} {'page' if top.pages == 1 else 'pages'}."
            )
    else:
        out.append(
            "The automated tests reported no failures. That does not mean the site conforms: automated tests cannot check every criterion."
        )
    if d.needs_review:
        out.append(
            f"A further {d.needs_review} {'item needs' if d.needs_review == 1 else 'items need'} a person to judge whether it is a problem."
        )
    f, t = len(d.criteria.failed), d.criteria.tested
    out.append(
        f"{f} of the {d.criteria.total} criteria in this standard had at least one automated failure. "
        f"Automated checks exist for {t} of the {d.criteria.total} criteria, so {d.criteria.total - t} need to be evaluated by a person."
    )
    return out


async def load_audit_data(
    db: AsyncSession, scan_id: uuid.UUID, standard_id: str, *, organization: str
) -> AuditReportData:
    reg = get_registry()
    if standard_id not in reg.standards:
        raise ValueError(f"unknown standard {standard_id}")
    st = reg.standards[standard_id]
    scan = (await db.execute(text("SELECT * FROM scan_jobs WHERE id=:i"), {"i": scan_id})).first()
    if scan is None or scan.status != "SUCCEEDED":
        raise ValueError("the scan is not finished")
    pages = (
        await db.execute(
            text(
                "SELECT url, status, error_detail FROM scan_pages WHERE scan_id=:i ORDER BY scanned_at"
            ),
            {"i": scan_id},
        )
    ).all()
    in_scope = [c.id for c in reg.criteria_for(standard_id)]
    sc_rows = (
        await db.execute(
            text("SELECT DISTINCT unnest(sc) AS sc, kind FROM scan_findings WHERE scan_id=:i"),
            {"i": scan_id},
        )
    ).all()
    summary = reg.summarise(standard_id, [{"sc": [r.sc], "kind": r.kind} for r in sc_rows])
    counts = (
        await db.execute(
            text(
                "SELECT kind, severity, count(*) n FROM scan_findings WHERE scan_id=:i AND (sc && CAST(:scs AS varchar[]) OR kind = 'best_practice') GROUP BY kind, severity"
            ),
            {"i": scan_id, "scs": in_scope},
        )
    ).all()
    sev = {s: 0 for s in SEVERITIES}
    needs = best = 0
    for r in counts:
        if r.kind == "violation":
            sev[r.severity] += r.n
        elif r.kind == "needs_review":
            needs += r.n
        else:
            best += r.n
    failures = sum(sev.values())
    rows = (
        await db.execute(
            text(
                "SELECT f.cluster_key, min(f.canonical_rule_id) AS rule, min(f.title) AS title, min(array_to_string(f.sc, ',')) AS sc, min(f.kind) AS kind, "
                "min(CASE f.severity WHEN 'critical' THEN 0 WHEN 'serious' THEN 1 WHEN 'moderate' THEN 2 ELSE 3 END) AS sev, count(*) AS occ, "
                "count(DISTINCT f.page_id) AS pages, min(f.confidence) AS conf, max(cardinality(f.engines)) AS agree, max(cardinality(f.covering)) AS cover "
                "FROM scan_findings f WHERE f.scan_id=:i AND f.kind='violation' AND f.sc && CAST(:scs AS varchar[]) "
                "GROUP BY f.cluster_key ORDER BY sev, occ DESC, rule LIMIT :lim"
            ),
            {"i": scan_id, "scs": in_scope, "lim": MAX_CLUSTERS},
        )
    ).all()
    total_clusters = (
        await db.execute(
            text(
                "SELECT count(DISTINCT cluster_key) FROM scan_findings WHERE scan_id=:i AND kind='violation' AND sc && CAST(:scs AS varchar[])"
            ),
            {"i": scan_id, "scs": in_scope},
        )
    ).scalar_one()
    clusters: list[ClusterRow] = []
    for r in rows:
        ex = (
            await db.execute(
                text(
                    "SELECT pg.url, f.css, f.html, f.message FROM scan_findings f JOIN scan_pages pg ON pg.id=f.page_id "
                    "WHERE f.scan_id=:i AND f.cluster_key=:k ORDER BY pg.scanned_at, f.xpath LIMIT :n"
                ),
                {"i": scan_id, "k": r.cluster_key, "n": MAX_EXAMPLES},
            )
        ).all()
        clusters.append(
            ClusterRow(
                rule=r.rule,
                title=r.title,
                criteria=[
                    _crit(reg, standard_id, c) for c in (r.sc or "").split(",") if c in reg.criteria
                ],
                severity=SEVERITIES[r.sev],
                kind=r.kind,
                occurrences=r.occ,
                pages=r.pages,
                confidence=CONF_LABEL.get(r.conf, r.conf),
                agreement=f"{r.agree} of {max(r.cover, r.agree)} engines",
                examples=[
                    Example(page=e.url, css=e.css, html=e.html, message=e.message) for e in ex
                ],
            )
        )
    site = scan.start_url
    d = AuditReportData(
        organization=organization,
        site=site,
        site_host=urlsplit(site).hostname or site,
        generated_on=datetime.now(UTC).strftime("%d %B %Y"),
        scanned_on=(scan.finished_at or scan.created_at).strftime("%d %B %Y"),
        standard=StandardInfo(
            id=st.id,
            label=st.label,
            legal_status=st.legal_status,
            legal_label=LEGAL_LABEL.get(st.legal_status, st.legal_status),
            citation=st.citation,
            notes=st.notes,
            mapping_review=reg.review["status"],
        ),
        engine_versions=scan.engine_versions,
        rules_version=scan.rules_version or reg.standards_version,
        mode=scan.mode,
        pages_scanned=scan.pages_scanned,
        severity_counts=sev,
        failures=failures,
        needs_review=needs,
        best_practices=best,
        criteria=CriteriaBuckets(
            failed=[_crit(reg, standard_id, c) for c in summary.failed],
            needs_review=[_crit(reg, standard_id, c) for c in summary.needs_review],
            no_issues_found=[_crit(reg, standard_id, c) for c in summary.no_issues_found],
            not_tested=[_crit(reg, standard_id, c) for c in summary.not_tested],
            tested=summary.automated_coverage[0],
            total=summary.automated_coverage[1],
        ),
        clusters=clusters,
        clusters_total=total_clusters,
        pages=[
            PageRow(
                url=p.url, result="Scanned" if p.status == "OK" else (p.error_detail or p.status)
            )
            for p in pages
        ],
        narrative=[],
    )
    d.narrative = build_narrative(d)
    return d
