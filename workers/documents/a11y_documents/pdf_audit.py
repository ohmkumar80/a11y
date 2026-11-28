"""Audit one customer PDF (ADR 0021): veraPDF's PDF/UA-1 checks plus a few direct checks, turned into findings a person
can act on. Pure functions over bytes, so they are testable without a database.

What this does NOT do: it cannot tell whether alt text is good, whether the reading order makes sense, or whether
colour contrast is enough. A file with no findings has passed the machine-checkable rules only; the summary says so."""

from __future__ import annotations

import contextlib
import io
import re
from dataclasses import dataclass, field

import pikepdf
from a11y_core import doc_rules

from .verapdf import VeraPdfUnavailable, validate_pdf_ua

SEVERITY_ORDER = {s: i for i, s in enumerate(doc_rules.SEVERITIES)}
_PAGE = re.compile(r"pages\[(\d+)\]")
_OBJ_ID = re.compile(r"\(\d+ \d+ obj [^)]*\)")
_TEXT_OPS = {"Tj", "TJ", "'", '"'}
MAX_PAGES_SCANNED = 200
MAX_EXAMPLES = 3
MAX_PAGES_LISTED = 25
LONG_DOC_PAGES = 20


class AuditError(Exception):
    """The file could not be audited. `customer_fault` decides whether the pages are charged."""

    def __init__(self, code: str, message: str, *, customer_fault: bool) -> None:
        super().__init__(message)
        self.code, self.message, self.customer_fault = code, message, customer_fault


@dataclass
class AuditResult:
    findings: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    tool_version: str = ""


def _pages_from(contexts: list[str]) -> list[int]:
    return sorted({int(m.group(1)) + 1 for c in contexts if (m := _PAGE.search(c))})


def _tidy(context: str) -> str:
    """A shortened location for experts: object numbers removed, bounded length."""
    return _OBJ_ID.sub("", context)[:220]


def _page_has_text(page) -> bool:
    try:
        for operands, op in pikepdf.parse_content_stream(page):  # noqa: B007
            if str(op) in _TEXT_OPS:
                return True
    except Exception:  # noqa: BLE001
        return True  # cannot tell: do not claim the page is a scan
    return False


def _resources_xobjects(page) -> tuple[bool, bool]:
    """(has an image, has a form XObject that might hold text)."""
    has_image = has_form = False
    with contextlib.suppress(Exception):
        xo = page.Resources.get("/XObject")
        if xo is not None:
            for _, obj in xo.items():
                sub = str(obj.get("/Subtype", ""))
                has_image |= sub == "/Image"
                has_form |= sub == "/Form"
    return has_image, has_form


def _facts_and_direct(data: bytes) -> tuple[dict, list[dict]]:
    try:
        pdf = pikepdf.open(io.BytesIO(data))
    except pikepdf.PasswordError:
        raise AuditError(
            "encrypted", "That PDF is password-protected.", customer_fault=True
        ) from None
    except (pikepdf.PdfError, ValueError, RuntimeError):
        raise AuditError(
            "corrupt", "That PDF is damaged and could not be opened.", customer_fault=True
        ) from None
    with pdf:
        root = pdf.Root
        pages = len(pdf.pages)
        mark = root.get("/MarkInfo")
        info_title = str(pdf.docinfo.get("/Title", "")).strip() if pdf.docinfo is not None else ""
        if not info_title:  # many tools keep the title only in the XMP metadata
            with (
                contextlib.suppress(Exception),
                pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as meta,
            ):
                info_title = str(meta.get("dc:title", "") or "").strip()
        facts = {
            "pages": pages,
            "tagged": bool(mark is not None and mark.get("/Marked", False)),
            "has_structure": "/StructTreeRoot" in root,
            "language": str(root.get("/Lang", "")) or None,
            "has_title": bool(info_title),
            "has_bookmarks": "/Outlines" in root and "/First" in root.Outlines,
            "pdf_version": str(pdf.pdf_version),
        }
        direct: list[dict] = []
        scanned: list[int] = []
        for i, page in enumerate(pdf.pages):
            if i >= MAX_PAGES_SCANNED:
                break
            has_image, has_form = _resources_xobjects(page)
            if has_image and not has_form and not _page_has_text(page):
                scanned.append(i + 1)
        facts["image_only_pages"] = len(scanned)
        if scanned:
            direct.append(
                _finding(
                    "direct:image-only-pages",
                    "direct",
                    "critical",
                    "Some pages are pictures of text (scanned pages)",
                    "A page that is only a picture has no real text, so a screen reader finds nothing to read, and people cannot resize, "
                    "search or reflow it. This is the most common reason a PDF is unusable for blind readers.",
                    "Run text recognition (OCR) on the file, then tag the result and check the reading order. If you still have the "
                    "original document, re-export it as a tagged PDF instead.",
                    ["1.1.1", "1.4.5"],
                    False,
                    len(scanned),
                    scanned,
                    [],
                )
            )
        if pages >= LONG_DOC_PAGES and not facts["has_bookmarks"]:
            direct.append(
                _finding(
                    "direct:no-bookmarks",
                    "direct",
                    "moderate",
                    f"A {pages}-page document has no bookmarks",
                    "Bookmarks are the table of contents of a PDF. Without them, readers have to move through the whole file page by page to find a section.",
                    "Create bookmarks from the headings: most export tools have a 'Create bookmarks' option.",
                    ["2.4.5"],
                    False,
                    1,
                    [],
                    [],
                )
            )
        return facts, direct


def _finding(
    rule_id, source, severity, title, why, fix, wcag, needs_human, count, pages, examples
) -> dict:
    return {
        "rule_id": rule_id,
        "source": source,
        "severity": severity,
        "title": title,
        "explanation": why,
        "how_to_fix": fix,
        "wcag": list(wcag),
        "needs_human": needs_human,
        "count": count,
        "pages": pages[:MAX_PAGES_LISTED],
        "pages_total": len(pages),
        "examples": examples,
    }


def audit_pdf(data: bytes, *, page_count: int | None = None) -> AuditResult:
    facts, direct = _facts_and_direct(data)
    timeout = min(900, 90 + 2 * (page_count or facts["pages"]))
    try:
        vera = validate_pdf_ua(data, timeout=timeout)
    except VeraPdfUnavailable as e:
        raise AuditError("checker_unavailable", str(e), customer_fault=False) from None
    findings: list[dict] = []
    for r in vera.failed:
        t = doc_rules.lookup(r.clause, r.test, r.description)
        contexts = [c for c, _ in r.checks]
        pages = _pages_from(contexts)
        examples = [{"where": _tidy(c), "message": m[:300]} for c, m in r.checks[:MAX_EXAMPLES]]
        findings.append(
            _finding(
                t.rule_id,
                "verapdf",
                t.severity,
                t.title,
                t.why,
                t.fix,
                t.wcag,
                t.needs_human,
                r.failed_checks,
                pages,
                examples,
            )
            | {"explained": t.explained, "description": r.description[:400]}
        )
    findings += direct
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), -f["count"], f["rule_id"]))
    by_sev = {s: sum(1 for f in findings if f["severity"] == s) for s in doc_rules.SEVERITIES}
    summary = {
        "standard": "PDF/UA-1",
        "verdict": "problems_found" if findings else "no_automated_problems",
        "findings": len(findings),
        "by_severity": by_sev,
        "needs_a_person": sum(1 for f in findings if f["needs_human"]),
        "rules_passed": vera.passed_rules,
        "rules_failed": len(vera.failed),
        "facts": facts,
        "caveat": "Automated checks find only part of what makes a PDF accessible. They cannot judge whether alternative text is "
        "meaningful, the reading order is logical or the colours have enough contrast, so a person still needs to review the file.",
    }
    return AuditResult(findings, summary, vera.tool_version)
