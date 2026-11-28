"""VPAT document model and builder (rendering side). The draft logic lives in a11y_core.vpat."""

from __future__ import annotations

from datetime import UTC, datetime

from a11y_core.rules import get_registry
from a11y_core.vpat import EDITIONS, TERMS, Signoff, VpatCriterion
from pydantic import BaseModel

from .data import LEGAL_LABEL


class VpatDoc(BaseModel):
    """Everything the VPAT template needs."""

    organization: str
    product: dict[str, str]
    edition: str
    edition_label: str
    standard_label: str
    legal_label: str
    report_date: str
    site: str
    engine_versions: dict[str, str]
    rules_version: str
    mapping_review: str
    status: str  # DRAFT | SIGNED_OFF
    signoff: Signoff | None
    tables: list[dict]  # [{"title": ..., "level": "A", "rows": [VpatCriterion...]}]
    not_evaluated: int
    total: int
    terms: list[tuple[str, str]] = TERMS
    template_version: str = ""


def build_doc(row, scan, org_name: str, rows: list[VpatCriterion]) -> VpatDoc:
    reg = get_registry()
    st = reg.standards[row.standard]
    tables = []
    for lvl, title in (
        ("A", "Table 1: Success Criteria, Level A"),
        ("AA", "Table 2: Success Criteria, Level AA"),
        ("AAA", "Table 3: Success Criteria, Level AAA"),
    ):
        rs = [r for r in rows if r.level == lvl]
        if rs:
            tables.append({"title": title, "level": lvl, "rows": rs})
    so = Signoff(**row.signoff) if row.signoff else None
    return VpatDoc(
        organization=org_name,
        product={k: v for k, v in (row.product or {}).items()},
        edition=row.edition,
        edition_label=EDITIONS[row.edition],
        standard_label=st.label,
        legal_label=LEGAL_LABEL.get(st.legal_status, st.legal_status),
        report_date=(so.signed_at[:10] if so else datetime.now(UTC).strftime("%Y-%m-%d")),
        site=scan.start_url,
        engine_versions=scan.engine_versions,
        rules_version=scan.rules_version or reg.standards_version,
        mapping_review=row.mapping_review,
        status=row.status,
        signoff=so,
        tables=tables,
        not_evaluated=sum(r.conformance == "Not Evaluated" for r in rows),
        total=len(rows),
    )
