"""Accessible PDF pipeline: WeasyPrint PDF/UA-1 + veraPDF gate (ADR 0008)."""

import io
import struct
import time
import zlib
from pathlib import Path

import pikepdf
import pytest
from a11y_documents.pdf import ReportTemplateError, check_template_html, render_pdf_ua
from a11y_documents.verapdf import runner_available, validate_pdf_ua
from weasyprint import HTML

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = (ROOT / "fixtures/reports/sample-report.html").read_text()
needs_verapdf = pytest.mark.skipif(
    not runner_available(),
    reason="veraPDF (binary or docker image ghcr.io/verapdf/cli) not available",
)


def png_bytes() -> bytes:
    raw = b"".join(b"\x00" + bytes((200, 30, 30)) * 40 for _ in range(20))

    def ch(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + ch(b"IHDR", struct.pack(">IIBBBBB", 40, 20, 8, 2, 0, 0, 0))
        + ch(b"IDAT", zlib.compress(raw))
        + ch(b"IEND", b"")
    )


def big_report(rows: int = 400, decorative: str = "") -> str:
    body = "".join(
        f'<tr><th scope="row">https://example.com/page-{i}</th><td>image-alt</td><td>1.1.1</td><td>{["Critical", "Serious", "Moderate"][i % 3]}</td></tr>'
        for i in range(rows)
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Large report</title>
<style>@page {{ size:A4; margin:20mm; @bottom-center {{ content: "Page " counter(page) " of " counter(pages) }} }}
thead {{ display: table-header-group }} tr {{ break-inside: avoid }} body {{ font: 10pt Arial, sans-serif }}</style></head><body>
<h1>Large report</h1>
<h2>Languages</h2>
<p lang="ta">அணுகல்தன்மை அறிக்கை: இந்தப் பக்கத்தில் உள்ள படங்களுக்கு மாற்று உரை தேவை.</p>
<p lang="hi">पहुंच-योग्यता रिपोर्ट: इस पृष्ठ की छवियों के लिए वैकल्पिक पाठ आवश्यक है।</p>
<h2>Image</h2>
<p><img src="shot.png" alt="Screenshot of the page header with a red banner" width="200"></p>
{decorative}
<h2>Findings</h2>
<table><caption>Findings</caption><thead><tr><th scope="col">Page</th><th scope="col">Rule</th><th scope="col">Criterion</th><th scope="col">Severity</th></tr></thead><tbody>{body}</tbody></table>
</body></html>"""


@pytest.fixture(scope="module")
def assets(tmp_path_factory):
    d = tmp_path_factory.mktemp("assets")
    (d / "shot.png").write_bytes(png_bytes())
    return d


# --- the gate ----------------------------------------------------------------------------------------


@needs_verapdf
def test_sample_report_passes_pdf_ua_1():
    r = validate_pdf_ua(render_pdf_ua(SAMPLE))
    assert r.compliant, r.summary()
    assert r.passed_rules > 100 and r.tool_version


@needs_verapdf
def test_long_multilingual_report_passes_and_renders_quickly(assets):
    t = time.time()
    pdf = render_pdf_ua(big_report(), base_url=str(assets) + "/")
    assert time.time() - t < 15
    assert len(pikepdf.open(io.BytesIO(pdf)).pages) > 5  # really multi-page: header row repeats
    r = validate_pdf_ua(pdf)
    assert r.compliant, r.summary()


@needs_verapdf
def test_validator_is_not_vacuous_a_plain_pdf_fails():
    plain = HTML(string=SAMPLE).write_pdf()  # same document, but NOT produced as PDF/UA
    r = validate_pdf_ua(plain)
    assert not r.compliant and r.failed


@needs_verapdf
def test_garbage_is_reported_as_an_error_not_a_pass():
    from a11y_documents.verapdf import VeraPdfUnavailable

    try:
        r = validate_pdf_ua(b"this is not a pdf")
    except VeraPdfUnavailable:
        return
    assert not r.compliant


@needs_verapdf
def test_spike_finding_decorative_img_fails_but_css_background_passes(assets):
    bad = big_report(rows=3, decorative='<p><img src="shot.png" alt="" width="60"> decorative</p>')
    r = validate_pdf_ua(
        render_pdf_ua(bad, base_url=str(assets) + "/", check=False)
    )  # bypass our own check on purpose
    assert not r.compliant and any(f.clause == "7.3" for f in r.failed)  # Figure without alt text
    good = big_report(
        rows=3,
        decorative='<p><span style="display:inline-block;width:60px;height:30px;background:url(shot.png)"></span> decorative</p>',
    )
    assert validate_pdf_ua(render_pdf_ua(good, base_url=str(assets) + "/")).compliant


# --- what the PDF contains ------------------------------------------------------------------------------


def structure_types(pdf: pikepdf.Pdf) -> list[str]:
    out: list[str] = []

    def walk(n):
        if isinstance(n, pikepdf.Dictionary) and "/S" in n:
            out.append(str(n["/S"]))
        k = n.get("/K") if isinstance(n, pikepdf.Dictionary) else None
        if k is not None:
            for c in k if isinstance(k, pikepdf.Array) else [k]:
                if isinstance(c, pikepdf.Dictionary):
                    walk(c)

    walk(pdf.Root.StructTreeRoot)
    return out


def test_pdf_keeps_the_semantics_of_the_html():
    pdf = pikepdf.open(io.BytesIO(render_pdf_ua(SAMPLE)))
    assert (
        str(pdf.Root.Lang) == "en"
        and bool(pdf.Root.MarkInfo.Marked)
        and bool(pdf.Root.ViewerPreferences.DisplayDocTitle)
    )
    assert (
        str(pdf.docinfo.Title) == "Accessibility audit report: example.com"
        and "/Metadata" in pdf.Root
    )
    types = structure_types(pdf)
    for needed in (
        "/Document",
        "/H1",
        "/H2",
        "/H3",
        "/L",
        "/LI",
        "/Table",
        "/THead",
        "/TH",
        "/TD",
        "/Caption",
        "/Link",
        "/Figure",
    ):
        assert needed in types, needed
    # the chart's <title> became the figure's alternative text
    alts = []

    def find(n):
        if isinstance(n, pikepdf.Dictionary):
            if str(n.get("/S")) == "/Figure" and "/Alt" in n:
                alts.append(str(n["/Alt"]))
            k = n.get("/K")
            if k is not None:
                for c in k if isinstance(k, pikepdf.Array) else [k]:
                    find(c)

    find(pdf.Root.StructTreeRoot)
    assert alts == ["Failures by severity"]


def test_indian_scripts_are_embedded_not_boxes(assets):
    pdf = pikepdf.open(io.BytesIO(render_pdf_ua(big_report(rows=3), base_url=str(assets) + "/")))
    fonts = {
        str(f.get("/BaseFont")) for pg in pdf.pages for f in pg.Resources.get("/Font", {}).values()
    }
    if not any("Tamil" in f for f in fonts):
        pytest.skip("no Tamil font on this machine (the docs-worker image installs Noto fonts)")
    assert any("Devanagari" in f for f in fonts)


# --- template check (runs when a template is saved) --------------------------------------------------------


def test_the_sample_template_is_clean():
    assert check_template_html(SAMPLE) == []


@pytest.mark.parametrize(
    "html,expect",
    [
        ("<html><head><title>t</title></head><body><h1>x</h1></body></html>", "lang"),
        ('<html lang="en"><head></head><body><h1>x</h1></body></html>', "title"),
        (
            '<html lang="en"><head><title>t</title></head><body><p>x</p></body></html>',
            "no headings",
        ),
        (
            '<html lang="en"><head><title>t</title></head><body><h1>x</h1><img src="a.png"></body></html>',
            "no alt attribute",
        ),
        (
            '<html lang="en"><head><title>t</title></head><body><h1>x</h1><img src="a.png" alt=""></body></html>',
            "decorative",
        ),
        (
            '<html lang="en"><head><title>t</title></head><body><h1>x</h1><svg width="1" height="1"></svg></body></html>',
            "svg",
        ),
        (
            '<html lang="en"><head><title>t</title></head><body><h1>x</h1><table><tr><td>a</td></tr></table></body></html>',
            "header cells",
        ),
        (
            '<html lang="en"><head><title>t</title></head><body><h1>x</h1><h3>y</h3></body></html>',
            "jumps from h1 to h3",
        ),
    ],
)
def test_template_check_catches_accessibility_mistakes(html, expect):
    problems = check_template_html(html)
    assert any(expect in p for p in problems), problems
    with pytest.raises(ReportTemplateError):
        render_pdf_ua(html)


def test_hidden_svg_and_labelled_svg_are_accepted():
    ok = '<html lang="en"><head><title>t</title></head><body><h1>x</h1><svg aria-hidden="true"></svg><svg role="img" aria-label="Chart"><title>Chart</title></svg></body></html>'
    assert check_template_html(ok) == []
