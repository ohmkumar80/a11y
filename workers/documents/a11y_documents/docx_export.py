"""Word (DOCX) output with real accessibility structure: Heading styles, repeating header rows, document
title and language, alternative text for any picture. `check_docx` gates every file."""

from __future__ import annotations

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from .data import AuditReportData
from .vpat import VpatDoc


def new_document(title: str, *, lang: str = "en") -> Document:
    doc = Document()
    doc.core_properties.title = title
    doc.core_properties.language = lang
    doc.core_properties.author = "a11y"
    # Document language, so screen readers use the right voice (set on the default run properties).
    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10.5)
    rpr = normal.element.get_or_add_rPr()
    el = OxmlElement("w:lang")
    el.set(qn("w:val"), "en-GB" if lang == "en" else lang)
    rpr.append(el)
    for name in ("Heading 1", "Heading 2", "Heading 3"):
        doc.styles[name].font.color.rgb = RGBColor(
            0x1A, 0x1A, 0x1A
        )  # strong contrast, no theme blue
    return doc


def add_table(
    doc: Document,
    header: list[str],
    rows: list[list[str]],
    *,
    caption: str | None = None,
    widths=None,
):
    """A data table whose first row is a header row that repeats on every page."""
    if caption:
        p = doc.add_paragraph()
        r = p.add_run(caption)
        r.bold = True
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    for i, h in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        run.bold = True
    trpr = t.rows[0]._tr.get_or_add_trPr()
    trpr.append(OxmlElement("w:tblHeader"))
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = str(v)
    return t


def audit_docx(d: AuditReportData) -> Document:
    doc = new_document(f"Accessibility audit report: {d.site_host}")
    doc.add_heading("Accessibility audit report", level=1)
    doc.add_paragraph(d.site)
    add_table(
        doc,
        ["Item", "Value"],
        [
            ["Prepared for", d.organization],
            ["Scanned on", d.scanned_on],
            ["Report created", d.generated_on],
            ["Checked against", d.standard.label],
            ["Pages scanned", str(d.pages_scanned)],
        ],
        caption="About this report",
    )

    doc.add_heading("Read this first", level=2)
    p = doc.add_paragraph()
    p.add_run(
        "This report is the result of automated tests. It is not a statement of conformance. "
    ).bold = True
    p.add_run(
        f"Automated tests can check only part of the criteria in {d.standard.label}. A page with no automated failures can still be inaccessible, "
        "and every criterion that needs a person must be evaluated by an accessibility specialist."
    )
    doc.add_paragraph(
        f"{d.standard.label}: {d.standard.legal_label}."
        + (f" {d.standard.citation}" if d.standard.citation else "")
    )
    if d.standard.mapping_review == "draft":
        doc.add_paragraph(
            "The mapping of this standard to individual criteria has not yet been signed off by an accessibility expert."
        )

    doc.add_heading("Summary", level=2)
    for line in d.narrative:
        doc.add_paragraph(line)
    add_table(
        doc,
        ["Result", "Count"],
        [
            [f"{s.capitalize()} failures", str(d.severity_counts.get(s, 0))]
            for s in ("critical", "serious", "moderate", "minor")
        ]
        + [
            ["Items that need a person to review", str(d.needs_review)],
            ["Best-practice suggestions", str(d.best_practices)],
        ],
        caption="Results at a glance",
    )

    doc.add_heading(f"Criteria in {d.standard.label}", level=2)
    doc.add_paragraph(
        f"Automated checks exist for {d.criteria.tested} of {d.criteria.total} criteria."
    )
    join = lambda cs: ", ".join(c.clause for c in cs) or "None"  # noqa: E731
    add_table(
        doc,
        ["Result", "Number", "Criteria"],
        [
            ["Automated failure found", str(len(d.criteria.failed)), join(d.criteria.failed)],
            [
                "Only items to review",
                str(len(d.criteria.needs_review)),
                join(d.criteria.needs_review),
            ],
            [
                "Automated tests found no issue (still needs a person)",
                str(len(d.criteria.no_issues_found)),
                join(d.criteria.no_issues_found),
            ],
            [
                "Cannot be tested by automation: needs a person",
                str(len(d.criteria.not_tested)),
                join(d.criteria.not_tested),
            ],
        ],
        caption="Criteria by result",
    )

    doc.add_heading("Problems found", level=2)
    if not d.clusters:
        doc.add_paragraph("The automated tests found no failures in this standard.")
    if d.clusters_total > len(d.clusters):
        doc.add_paragraph(
            f"This report shows the {len(d.clusters)} most severe of {d.clusters_total} problems; the CSV export lists everything."
        )
    for i, c in enumerate(d.clusters, 1):
        doc.add_heading(f"{i}. {c.title}", level=3)
        add_table(
            doc,
            ["Item", "Detail"],
            [
                ["Severity", c.severity.capitalize()],
                [
                    "Criteria",
                    "; ".join(f"{k.clause} {k.name} (level {k.level})" for k in c.criteria)
                    or "Not mapped to a criterion",
                ],
                [
                    "How often",
                    f"{c.occurrences} {'occurrence' if c.occurrences == 1 else 'occurrences'} on {c.pages} {'page' if c.pages == 1 else 'pages'}",
                ],
                ["Confidence", f"{c.confidence} ({c.agreement} agree)"],
            ],
            caption=f"Details of problem {i}",
        )
        doc.add_paragraph().add_run("Examples").bold = True
        for e in c.examples:
            doc.add_paragraph(f"On {e.page}" + (f": {e.message}" if e.message else ""))
            r = doc.add_paragraph().add_run(e.html)
            r.font.name = "Courier New"
            r.font.size = Pt(8.5)

    doc.add_heading("Pages scanned", level=2)
    add_table(
        doc, ["Address", "Result"], [[p.url, p.result] for p in d.pages], caption="Pages scanned"
    )
    doc.add_heading("How this report was made", level=2)
    doc.add_paragraph(
        "Each page was opened in a real browser. Three open-source engines then tested the same page: "
        + ", ".join(f"{k} {v}" for k, v in d.engine_versions.items())
        + f". Where several engines reported the same problem on the same element it is listed once. Rule mappings version {d.rules_version}. "
        "This report was generated from the stored scan results without any AI-written text."
    )
    return doc


def vpat_docx(d: VpatDoc) -> Document:
    name = d.product.get("name") or d.site
    doc = new_document(f"Accessibility Conformance Report ({d.edition_label}): {name}")
    doc.add_heading("Accessibility Conformance Report", level=1)
    doc.add_paragraph(
        f"Based on VPAT 2.5, {d.edition_label}."
        + (" DRAFT: not reviewed or signed off." if d.status == "DRAFT" else "")
    )
    doc.add_heading("About this report", level=2)
    add_table(
        doc,
        ["Item", "Detail"],
        [
            ["Name of product", name],
            ["Version", d.product.get("version") or "Not stated"],
            ["Description", d.product.get("description") or "Not stated"],
            ["Web address evaluated", d.site],
            ["Report date", d.report_date],
            ["Prepared for", d.organization],
            ["Contact", d.product.get("contact") or "Not stated"],
            ["Notes", d.product.get("notes") or "None"],
            ["Standard", f"{d.standard_label}. {d.legal_label}."],
        ],
        caption="Product and report details",
    )
    doc.add_heading("Status of this document", level=2)
    if d.signoff:
        doc.add_paragraph(
            f"The conformance levels and remarks in this document were reviewed and confirmed by {d.signoff.name} ({d.signoff.role}) on {d.signoff.signed_at[:10]}."
        )
        doc.add_paragraph(f"Statement made at sign-off: {d.signoff.statement}")
    else:
        doc.add_paragraph(
            "This is a draft. It has not been reviewed or signed off by a person and must not be shared as a conformance claim."
        )
    if d.not_evaluated:
        doc.add_paragraph(
            f'This report is incomplete: {d.not_evaluated} of {d.total} criteria are still "Not Evaluated".'
        )
    if d.mapping_review == "draft":
        doc.add_paragraph(
            "The mapping of this standard to individual criteria has not yet been signed off by an accessibility expert."
        )
    doc.add_paragraph(
        f"This document contains the WCAG success criteria for web content only. The chapters of {d.edition_label} that apply to software, hardware and documentation are not included."
    )
    doc.add_heading("Evaluation methods used", level=2)
    doc.add_paragraph(
        "Automated tests: each page was opened in a real browser and tested with "
        + ", ".join(f"{k} {v}" for k, v in d.engine_versions.items())
        + f" (rule mappings version {d.rules_version}). Automated tests cannot establish that a criterion is supported. Where a level other than "
        '"Not Evaluated" has no automated evidence behind it, it was set by the person named above.'
    )
    doc.add_heading("Terms used in the conformance level information", level=2)
    add_table(doc, ["Term", "Meaning"], [[t, m] for t, m in d.terms], caption="Conformance levels")
    for t in d.tables:
        doc.add_heading(t["title"], level=2)
        add_table(
            doc,
            ["Criteria", "Conformance level", "Remarks and explanations"],
            [
                [f"{r.clause} {r.name} (Level {r.level})", r.conformance, r.remarks]
                for r in t["rows"]
            ],
            caption=t["title"],
        )
    return doc
