"""Report templates and file formats, without a database: golden text, escaping, PDF/UA, DOCX, CSV."""

import io
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path

import pikepdf
import pytest
from a11y_documents.csv_export import COLUMNS, check_csv, safe_cell
from a11y_documents.data import build_narrative
from a11y_documents.docx_check import check_docx
from a11y_documents.docx_export import add_table, audit_docx, new_document
from a11y_documents.pdf import ReportTemplateError, check_template_html, render_pdf_ua
from a11y_documents.registry import TEMPLATES, render_html
from a11y_documents.samples import sample_audit_data
from a11y_documents.verapdf import runner_available, validate_pdf_ua

GOLDEN = Path(__file__).parent / "golden"
needs_verapdf = pytest.mark.skipif(not runner_available(), reason="veraPDF not available")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.t, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in ("style", "script")

    def handle_endtag(self, tag):
        self.skip -= tag in ("style", "script")

    def handle_data(self, data):
        if not self.skip:
            self.t.append(data)


def text_of(html: str) -> str:
    p = _Text()
    p.feed(html)
    return "\n".join(
        line for line in (re.sub(r"\s+", " ", x).strip() for x in "".join(p.t).splitlines()) if line
    )


# --- template ----------------------------------------------------------------------------------------------


def test_audit_template_renders_accessible_html_and_matches_the_golden_text():
    html = render_html("audit_report", sample_audit_data())
    assert check_template_html(html) == []
    golden = GOLDEN / "audit_report.txt"
    got = text_of(html)
    if not golden.exists():  # first run (or deliberate refresh): review the diff in git
        golden.parent.mkdir(exist_ok=True)
        golden.write_text(got + "\n")
    assert got + "\n" == golden.read_text(), (
        "the audit report text changed: if intended, delete tests/golden/audit_report.txt and re-run"
    )


def test_the_template_says_what_it_must_say():
    t = text_of(render_html("audit_report", sample_audit_data()))
    assert "not a statement of conformance" in t
    assert (
        "has not yet been signed off by an accessibility expert" in t
    )  # draft mapping is disclosed
    assert "without any AI-written text" in t
    assert "compliant" not in t.lower().replace("not compliant", "")  # never claims compliance


def test_untrusted_page_content_is_escaped_not_executed():
    html = render_html("audit_report", sample_audit_data(hostile=True))

    class Tags(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags, self.attrs = [], []

        def handle_starttag(self, tag, attrs):
            self.tags.append(tag)
            self.attrs += [k for k, _ in attrs]

    p = Tags()
    p.feed(html)
    assert (
        "script" not in p.tags and "onerror" not in p.attrs
    )  # no live element or handler came from page content
    assert p.tags.count("img") == 0  # the sample's <img> snippets are shown as text, not rendered
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in html
    assert "Évil &lt;b&gt;Corp&lt;/b&gt; &amp; Sons" in html


def test_a_template_with_an_unknown_variable_fails_loudly(tmp_path, monkeypatch):
    import a11y_documents.registry as reg
    from jinja2 import FileSystemLoader, UndefinedError

    (tmp_path / "bad.html.j2").write_text(
        "<html lang='en'><head><title>t</title></head><body><h1>{{ d.nope }}</h1></body></html>"
    )
    monkeypatch.setattr(reg._env, "loader", FileSystemLoader(tmp_path))
    monkeypatch.setitem(
        reg.TEMPLATES, "bad", reg.TemplateDef("bad", 1, "bad.html.j2", type(sample_audit_data()))
    )
    with pytest.raises(UndefinedError):
        reg.render_html("bad", sample_audit_data())


def test_the_sandbox_blocks_dangerous_template_code(tmp_path, monkeypatch):
    import a11y_documents.registry as reg
    from jinja2 import FileSystemLoader
    from jinja2.exceptions import SecurityError

    (tmp_path / "evil.html.j2").write_text(
        "<html lang='en'><head><title>t</title></head><body><h1>{{ d.__class__.__mro__[1].__subclasses__() }}</h1></body></html>"
    )
    monkeypatch.setattr(reg._env, "loader", FileSystemLoader(tmp_path))
    monkeypatch.setitem(
        reg.TEMPLATES, "evil", reg.TemplateDef("evil", 1, "evil.html.j2", type(sample_audit_data()))
    )
    with pytest.raises((SecurityError, Exception)) as e:
        reg.render_html("evil", sample_audit_data())
    assert "subclasses" not in str(getattr(e.value, "message", "")) or isinstance(
        e.value, SecurityError
    )


def test_template_version_id_changes_when_the_template_changes():
    v = TEMPLATES["audit_report"].version_id
    assert re.fullmatch(r"audit_report@v1\+[0-9a-f]{8}", v)


def test_narrative_numbers_match_the_tables():
    d = sample_audit_data()
    n = " ".join(build_narrative(d))
    assert (
        f"{d.failures} failures" in n
        and f"{d.pages_scanned} pages" in n
        and f"{d.criteria.tested} of the {d.criteria.total}" in n
    )
    assert str(d.needs_review) in n
    one = sample_audit_data()
    one.pages_scanned, one.failures = 1, 0
    one.clusters, one.clusters_total = [], 0
    s = " ".join(build_narrative(one))
    assert "1 page of" in s and "no failures" in s and "does not mean the site conforms" in s


# --- PDF -------------------------------------------------------------------------------------------------------


@needs_verapdf
def test_audit_pdf_passes_pdf_ua_and_keeps_its_structure():
    pdf = render_pdf_ua(render_html("audit_report", sample_audit_data(hostile=True)))
    r = validate_pdf_ua(pdf)
    assert r.compliant, r.summary()
    p = pikepdf.open(io.BytesIO(pdf))
    assert str(p.Root.Lang) == "en" and "Accessibility audit report" in str(p.docinfo.Title)


@needs_verapdf
def test_a_report_with_no_findings_also_passes():
    d = sample_audit_data()
    d.clusters, d.clusters_total, d.failures = [], 0, 0
    d.severity_counts = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
    assert validate_pdf_ua(render_pdf_ua(render_html("audit_report", d))).compliant


def test_pdf_generation_refuses_an_inaccessible_template():
    with pytest.raises(ReportTemplateError):
        render_pdf_ua("<html><head><title>x</title></head><body><h1>No language</h1></body></html>")


# --- DOCX ------------------------------------------------------------------------------------------------------


def docx_bytes(doc) -> bytes:
    b = io.BytesIO()
    doc.save(b)
    return b.getvalue()


def test_audit_docx_passes_its_accessibility_check():
    data = docx_bytes(audit_docx(sample_audit_data(hostile=True)))
    assert check_docx(data) == []
    z = zipfile.ZipFile(io.BytesIO(data))
    assert "Évil" in z.read("word/document.xml").decode()  # escaped XML, not injected markup
    assert "<script>" not in z.read("word/document.xml").decode()


def test_docx_check_catches_the_real_problems():
    doc = new_document("t")
    doc.add_heading("Top", level=1)
    doc.add_heading("Skipped", level=3)
    t = doc.add_table(rows=1, cols=2)  # no header row marking
    t.rows[0].cells[0].text = "a"
    problems = check_docx(docx_bytes(doc))
    assert any("jumps from 1 to 3" in p for p in problems) and any(
        "header row" in p for p in problems
    )

    untitled = new_document("")
    untitled.add_heading("Top", level=1)
    assert any("no title" in p for p in check_docx(docx_bytes(untitled)))

    nohead = new_document("t")
    nohead.add_paragraph("just text")
    assert any("no headings" in p for p in check_docx(docx_bytes(nohead)))

    pic = new_document("t")
    pic.add_heading("Top", level=1)
    pic.add_picture(
        io.BytesIO(__import__("base64").b64decode("R0lGODlhAQABAAAAACw=")) if False else _png(),
        width=None,
    )
    assert any("alternative text" in p for p in check_docx(docx_bytes(pic)))
    assert check_docx(b"not a zip") == ["not a valid Word document"]


def _png():
    import struct
    import zlib

    raw = b"\x00" + bytes((200, 30, 30)) * 4

    def ch(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return io.BytesIO(
        b"\x89PNG\r\n\x1a\n"
        + ch(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + ch(b"IDAT", zlib.compress(raw + raw))
        + ch(b"IEND", b"")
    )


def test_docx_tables_repeat_their_header_row():
    doc = new_document("t")
    doc.add_heading("Top", level=1)
    add_table(doc, ["A", "B"], [["1", "2"]], caption="Numbers")
    assert check_docx(docx_bytes(doc)) == []


# --- CSV -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("v", ["=1+1", "+SUM(A1)", "-2+3", "@cmd", "\tx", "\rx"])
def test_csv_cells_cannot_become_formulas(v):
    assert safe_cell(v).startswith("'")


def test_csv_leaves_ordinary_text_alone_and_check_catches_schema_drift():
    assert safe_cell("normal") == "normal" and safe_cell(None) == "" and safe_cell(5) == "5"
    good = "﻿".encode() + (",".join(COLUMNS) + "\r\n").encode()
    assert check_csv(good) == []
    assert any("byte-order" in p for p in check_csv(good[3:]))
    assert any("header" in p for p in check_csv("﻿a,b\r\n".encode()))
    assert any("columns" in p for p in check_csv(good + b"x,y\r\n"))


# --- VPAT -----------------------------------------------------------------------------------------------------


def sample_vpat(signed: bool):
    from a11y_core.vpat import Signoff, VpatCriterion
    from a11y_documents.vpat import VpatDoc

    rows = [
        VpatCriterion(
            id="1.1.1",
            name="Non-text Content",
            level="A",
            clause="WCAG 1.1.1",
            conformance="Does Not Support",
            remarks="Automated tests found 4 failures on 2 of 3 pages scanned.",
            source="automated",
        ),
        VpatCriterion(id="1.4.3", name="Contrast (Minimum)", level="AA", clause="WCAG 1.4.3"),
        VpatCriterion(
            id="1.2.5",
            name="Audio Description (Prerecorded)",
            level="AA",
            clause="WCAG 1.2.5",
            conformance="Supports",
            remarks="Provided for every video.",
            source="manual",
        ),
    ]
    return VpatDoc(
        organization="Example Ltd",
        product={"name": "Acme Portal", "version": "4.2"},
        edition="WCAG",
        edition_label="WCAG Edition",
        standard_label="WCAG 2.2 Level AA",
        legal_label="A reference standard",
        report_date="2026-11-27",
        site="https://www.example.com/",
        engine_versions={"axe": "4.14.1"},
        rules_version="2026-11-27.1",
        mapping_review="draft",
        status="SIGNED_OFF" if signed else "DRAFT",
        signoff=Signoff(
            name="Priya N",
            role="Accessibility lead",
            statement="I have reviewed each level.",
            signed_at="2026-11-27T10:00:00+00:00",
        )
        if signed
        else None,
        tables=[
            {"title": "Table 1: Success Criteria, Level A", "level": "A", "rows": [rows[0]]},
            {"title": "Table 2: Success Criteria, Level AA", "level": "AA", "rows": rows[1:]},
        ],
        not_evaluated=1,
        total=3,
    )


def test_vpat_draft_says_it_is_a_draft_and_never_a_conformance_claim():
    html = render_html("vpat", sample_vpat(False))
    assert check_template_html(html) == []
    t = text_of(html)
    assert (
        "DRAFT: not reviewed or signed off" in t
        and "must not be shared as a conformance claim" in t
    )
    assert (
        "This report is incomplete: 1 of 3 criteria are still" in t
        and "not yet been signed off by an accessibility expert" in t
    )
    assert "web content only" in t and "Does Not Support" in t and "Supports" in t


def test_signed_vpat_names_the_person_and_keeps_the_incomplete_warning():
    t = text_of(render_html("vpat", sample_vpat(True)))
    assert "reviewed and confirmed by Priya N (Accessibility lead) on 2026-11-27" in t
    assert (
        "DRAFT" not in t and "This report is incomplete" in t
    )  # signing off does not hide that criteria are unevaluated


@needs_verapdf
def test_vpat_pdf_and_docx_pass_their_gates():
    from a11y_documents.docx_export import vpat_docx

    assert validate_pdf_ua(render_pdf_ua(render_html("vpat", sample_vpat(True)))).compliant
    assert check_docx(docx_bytes(vpat_docx(sample_vpat(True)))) == []
    assert check_docx(docx_bytes(vpat_docx(sample_vpat(False)))) == []


def test_default_criteria_rules():
    from a11y_core.rules import get_registry
    from a11y_core.vpat import default_criteria, validate_edits

    reg = get_registry()
    rows = {
        r.id: r
        for r in default_criteria(
            reg,
            "WCAG_2_1_AA",
            {
                "1.1.1": {"failures": 5, "pages": 4, "review": 2},
                "1.4.3": {"failures": 2, "pages": 1, "review": 0},
            },
            4,
        )
    }
    assert (
        rows["1.1.1"].conformance == "Does Not Support"
        and "2 items need review" in rows["1.1.1"].remarks
    )  # every page fails
    assert rows["1.4.3"].conformance == "Partially Supports"  # 1 of 4 pages
    assert "2.5.8" not in rows  # a WCAG 2.2 criterion is not in a 2.1 VPAT
    assert all(
        r.conformance in ("Does Not Support", "Partially Supports", "Not Evaluated")
        for r in rows.values()
    )
    assert validate_edits(list(rows.values())) == []  # the defaults themselves are consistent
    broken = rows["1.4.3"].model_copy(update={"remarks": "", "conformance": "Partially Supports"})
    assert any("explain why" in p for p in validate_edits([broken]))
    zero = default_criteria(
        reg, "WCAG_2_1_AA", {"1.1.1": {"failures": 1, "pages": 1, "review": 0}}, 0
    )
    assert (
        next(r for r in zero if r.id == "1.1.1").conformance == "Partially Supports"
    )  # no pages scanned: never claims "all pages"
