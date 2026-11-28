"""VPAT 2.5 / ACR draft logic (PROJECT_PLAN 1.7 and 3.8). Pure logic shared by the API and the docs worker;
the document rendering lives in workers/documents.


What automation may and may not say:
  * An automated FAILURE can suggest "Does Not Support" (failures on every scanned page) or "Partially Supports".
  * Automation can NEVER establish "Supports". A criterion with no automated issue stays "Not Evaluated".
  * Criteria automation cannot test at all stay "Not Evaluated".
A person edits the levels and remarks, then signs off. The document cannot be exported before sign-off and, if
criteria remain "Not Evaluated", it says so on its first page."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .rules import Registry, get_registry

LEVELS = ("Supports", "Partially Supports", "Does Not Support", "Not Applicable", "Not Evaluated")
NEEDS_REMARKS = ("Partially Supports", "Does Not Support")
EDITIONS = {
    "WCAG": "WCAG Edition",
    "508": "Revised Section 508 Edition",
    "EU": "EU Edition (EN 301 549)",
    "INT": "International Edition",
}
TERMS = [
    (
        "Supports",
        "The functionality of the product has at least one method that meets the criterion without known defects, or meets it with equivalent facilitation.",
    ),
    ("Partially Supports", "Some functionality of the product does not meet the criterion."),
    ("Does Not Support", "The majority of product functionality does not meet the criterion."),
    ("Not Applicable", "The criterion is not relevant to the product."),
    (
        "Not Evaluated",
        "The product has not been evaluated against the criterion. This can be used only in WCAG Level AAA in a completed report.",
    ),
]


class VpatCriterion(BaseModel):
    id: str
    name: str
    level: str  # WCAG level A / AA / AAA
    clause: str
    conformance: Literal[
        "Supports", "Partially Supports", "Does Not Support", "Not Applicable", "Not Evaluated"
    ] = "Not Evaluated"
    remarks: str = ""
    source: Literal["automated", "manual", "default"] = "default"
    failures: int = 0
    failing_pages: int = 0
    scanned_pages: int = 0
    review_items: int = 0
    automated_check_exists: bool = False


class Signoff(BaseModel):
    name: str
    role: str
    statement: str
    user_id: str | None = None
    signed_at: str


def default_criteria(
    reg: Registry, standard_id: str, per_sc: dict[str, dict], scanned_pages: int
) -> list[VpatCriterion]:
    """Draft conformance from the scan. `per_sc[sc] = {failures, pages, review}`."""
    out: list[VpatCriterion] = []
    for c in reg.criteria_for(standard_id):
        ev = per_sc.get(c.id, {})
        failures, fpages, review = ev.get("failures", 0), ev.get("pages", 0), ev.get("review", 0)
        checks = c.id in reg.automated_sc
        row = VpatCriterion(
            id=c.id,
            name=c.name,
            level=c.level,
            clause=reg.clause(standard_id, c.id),
            failures=failures,
            failing_pages=fpages,
            scanned_pages=scanned_pages,
            review_items=review,
            automated_check_exists=checks,
        )
        if failures:
            row.conformance = (
                "Does Not Support"
                if scanned_pages and fpages >= scanned_pages
                else "Partially Supports"
            )
            row.remarks = (
                f"Automated tests found {failures} {'failure' if failures == 1 else 'failures'} on {fpages} of {scanned_pages} "
                f"{'page' if scanned_pages == 1 else 'pages'} scanned. See the audit report for the affected elements."
            )
            row.source = "automated"
        elif checks:
            row.remarks = "Automated tests found no issue for this criterion. A person must still evaluate it before it can be reported as supported."
        else:
            row.remarks = "Automated tests cannot evaluate this criterion. It needs to be evaluated by a person."
        if review:
            row.remarks += f" {review} {'item needs' if review == 1 else 'items need'} review."
        out.append(row)
    return out


def validate_edits(rows: list[VpatCriterion]) -> list[str]:
    """Problems that must be fixed before sign-off (and, for remarks, before saving a level)."""
    problems = []
    for r in rows:
        if r.conformance in NEEDS_REMARKS and not r.remarks.strip():
            problems.append(f"{r.clause} {r.name}: explain why it is '{r.conformance}'.")
        if r.failures and r.conformance in ("Supports", "Not Applicable") and not r.remarks.strip():
            problems.append(
                f"{r.clause} {r.name}: automated tests found failures; explain why you are marking it '{r.conformance}'."
            )
        if (
            r.conformance == "Not Evaluated"
            and r.level != "AAA"
            and r.source == "manual"
            and not r.remarks.strip()
        ):
            problems.append(f"{r.clause} {r.name}: say why it was not evaluated.")
    return problems


async def load_scan_evidence(db: AsyncSession, scan_id: uuid.UUID) -> tuple[dict[str, dict], int]:
    rows = (
        await db.execute(
            text(
                "SELECT sc, kind, count(*) AS n, count(DISTINCT page_id) AS p FROM (SELECT unnest(sc) AS sc, kind, page_id FROM scan_findings WHERE scan_id=:i) x GROUP BY sc, kind"
            ),
            {"i": scan_id},
        )
    ).all()
    per: dict[str, dict] = {}
    for r in rows:
        e = per.setdefault(r.sc, {"failures": 0, "pages": 0, "review": 0})
        if r.kind == "violation":
            e["failures"], e["pages"] = r.n, r.p
        elif r.kind == "needs_review":
            e["review"] = r.n
    scanned = (
        await db.execute(
            text("SELECT count(*) FROM scan_pages WHERE scan_id=:i AND status='OK'"), {"i": scan_id}
        )
    ).scalar_one()
    return per, scanned


async def create_draft(
    db: AsyncSession,
    org_id: uuid.UUID,
    scan_id: uuid.UUID,
    standard_id: str,
    edition: str,
    user_id: uuid.UUID | None,
    *,
    product_name: str,
) -> uuid.UUID:
    """Idempotent: returns the existing draft for (scan, standard, edition)."""
    existing = (
        await db.execute(
            text("SELECT id FROM vpat_reports WHERE scan_id=:s AND standard=:st AND edition=:e"),
            {"s": scan_id, "st": standard_id, "e": edition},
        )
    ).first()
    if existing:
        return existing.id
    reg = get_registry()
    per, scanned = await load_scan_evidence(db, scan_id)
    rows = default_criteria(reg, standard_id, per, scanned)
    vid = uuid.uuid4()
    import json

    await db.execute(
        text(
            "INSERT INTO vpat_reports (id, organization_id, scan_id, standard, edition, product, criteria, mapping_review, created_by) "
            "VALUES (:i, :o, :s, :st, :e, CAST(:p AS jsonb), CAST(:c AS jsonb), :m, :u)"
        ),
        {
            "i": vid,
            "o": org_id,
            "s": scan_id,
            "st": standard_id,
            "e": edition,
            "u": user_id,
            "m": reg.review["status"],
            "p": json.dumps(
                {"name": product_name, "version": "", "description": "", "contact": "", "notes": ""}
            ),
            "c": json.dumps([r.model_dump() for r in rows]),
        },
    )
    return vid
