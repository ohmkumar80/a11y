"""CSV export of EVERY finding: UTF-8 with a byte-order mark (Excel opens it correctly, including Tamil and
Hindi), one header row, one finding per row, no merged cells (PROJECT_PLAN 2.5)."""

from __future__ import annotations

import csv
import io
import uuid

from a11y_core.rules import get_registry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

COLUMNS = [
    "severity",
    "type",
    "problem",
    "rule",
    "criteria",
    "clauses",
    "confidence",
    "engines_agreeing",
    "engines_able_to_detect",
    "page",
    "element_css",
    "element_xpath",
    "message",
    "html",
    "standard",
]
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v: object) -> str:
    """Page content is untrusted: a cell starting with = + - @ would run as a formula in Excel (CSV injection)."""
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(_FORMULA_START) else s


async def build_csv(db: AsyncSession, scan_id: uuid.UUID, standard_id: str) -> bytes:
    reg = get_registry()
    scs = [c.id for c in reg.criteria_for(standard_id)]
    rows = (
        await db.execute(
            text(
                "SELECT f.*, pg.url AS page_url FROM scan_findings f JOIN scan_pages pg ON pg.id = f.page_id "
                "WHERE f.scan_id=:i AND (f.sc && CAST(:scs AS varchar[]) OR f.kind = 'best_practice') "
                "ORDER BY CASE f.severity WHEN 'critical' THEN 0 WHEN 'serious' THEN 1 WHEN 'moderate' THEN 2 ELSE 3 END, f.canonical_rule_id, pg.url, f.xpath"
            ),
            {"i": scan_id, "scs": scs},
        )
    ).all()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow(
            [
                safe_cell(x)
                for x in (
                    r.severity,
                    {
                        "violation": "failure",
                        "needs_review": "needs review",
                        "best_practice": "best practice",
                    }[r.kind],
                    r.title,
                    r.canonical_rule_id,
                    "; ".join(c for c in r.sc),
                    "; ".join(reg.clause(standard_id, c) for c in r.sc),
                    r.confidence,
                    len(r.engines),
                    len(r.covering),
                    r.page_url,
                    r.css,
                    r.xpath,
                    r.message,
                    r.html,
                    standard_id,
                )
            ]
        )
    return "﻿".encode() + buf.getvalue().encode("utf-8")


def check_csv(data: bytes) -> list[str]:
    """Schema check run before delivery: BOM, exact header, constant column count."""
    problems: list[str] = []
    if not data.startswith("﻿".encode()):
        problems.append("missing UTF-8 byte-order mark")
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    if not rows or rows[0] != COLUMNS:
        problems.append("header row does not match the schema")
    if any(len(r) != len(COLUMNS) for r in rows):
        problems.append("a row has the wrong number of columns")
    return problems
