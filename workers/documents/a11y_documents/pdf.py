"""Accessible PDF generation: WeasyPrint with ``pdf_variant="pdf/ua-1"``.

Decision (ADR 0008): Chromium's tagged PDF fails PDF/UA-1 out of the box (link annotations, figure alt text,
XMP metadata) and would need a repair step; WeasyPrint's PDF/UA-1 output passes veraPDF, embeds the fonts it
needs (Tamil and Devanagari included, with Noto fonts installed) and keeps the semantics of the HTML: headings,
lists, table header cells, captions, links, and SVG <title> as figure alt text.

`check_template_html` finds, BEFORE rendering, the mistakes the spike showed would fail the validator or hide
content from assistive technology. Templates must pass it when they are saved (PROJECT_PLAN 3.14)."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser

from weasyprint import HTML


class ReportTemplateError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class _Scan:
    lang: str | None = None
    title: str = ""
    problems: list[str] | None = None


class _Checker(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.problems: list[str] = []
        self.lang: str | None = None
        self.title = ""
        self._in_title = False
        self._svg_depth = 0
        self._svg_has_title = False
        self._svg_labelled = False
        self._table_has_th: list[bool] = []
        self._h = 0
        self._last_heading = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "title":
            self._in_title = True
        elif tag == "img":
            alt = a.get("alt")
            if alt is None:
                self.problems.append(
                    "An <img> has no alt attribute. Describe it, or draw decorative graphics with a CSS background."
                )
            elif alt.strip() == "":
                self.problems.append(
                    'A decorative <img alt=""> fails PDF/UA when rendered. Use a CSS background image for decoration.'
                )
        elif tag == "svg":
            self._svg_depth += 1
            self._svg_has_title = False
            self._svg_labelled = (
                a.get("role") == "img" or "aria-label" in a or "aria-labelledby" in a
            )
            if a.get("aria-hidden") != "true" and not self._svg_labelled:
                self.problems.append(
                    'An <svg> needs role="img" and a <title> (it becomes the figure\'s alt text).'
                )
        elif tag == "title" and self._svg_depth:
            self._svg_has_title = True
        elif tag == "table":
            self._table_has_th.append(False)
        elif tag == "th" and self._table_has_th:
            self._table_has_th[-1] = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            if self._last_heading and level > self._last_heading + 1:
                self.problems.append(f"Heading level jumps from h{self._last_heading} to h{level}.")
            self._last_heading = level
            self._h += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "svg" and self._svg_depth:
            self._svg_depth -= 1
        elif tag == "table" and self._table_has_th:
            if not self._table_has_th.pop():
                self.problems.append("A <table> has no header cells (<th>).")

    def handle_data(self, data: str) -> None:
        if self._in_title and not self._svg_depth:
            self.title += data


def check_template_html(html: str) -> list[str]:
    """Problems that would make the rendered PDF inaccessible. Empty list = fine."""
    c = _Checker()
    c.feed(html)
    out = list(c.problems)
    if not c.lang:
        out.append('The <html> element needs a lang attribute, for example lang="en".')
    if not c.title.strip():
        out.append("The document needs a non-empty <title>.")
    if c._h == 0:
        out.append("The document has no headings.")
    return list(dict.fromkeys(out))


def render_pdf_ua(html: str, *, base_url: str | None = None, check: bool = True) -> bytes:
    """HTML -> tagged PDF/UA-1. Raises ReportTemplateError if the template would break accessibility."""
    if check and (problems := check_template_html(html)):
        raise ReportTemplateError(problems)
    return HTML(string=html, base_url=base_url).write_pdf(pdf_variant="pdf/ua-1")
