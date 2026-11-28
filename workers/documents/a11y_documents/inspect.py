"""Deep inspection of an uploaded file, run only inside the documents worker (ADR 0020).

First-line checks (kind, size, zip-bomb) already ran in the API. This adds what needs a real parser: password
protection, page count, and "active content" - scripts and launch actions in PDFs, macros in Office files, XML entity
declarations. It never executes or renders anything; it only reads structure. Returns facts for the document's
`inspection` column, or raises `Refusal` with a plain-language message."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

import pikepdf
from a11y_core.upload_checks import Refusal

# Reasons that mean the bytes themselves are hostile: they are erased at once instead of being kept for support.
DANGEROUS = frozenset(
    {"malware", "zip_bomb", "zip_unsafe_path", "zip_nested", "active_content", "xml_entities"}
)
_ACTIVE_ACTIONS = {"/JavaScript", "/Launch", "/ImportData", "/SubmitForm", "/GoToE", "/GoToR"}
_SLIDE = re.compile(r"^ppt/slides/slide\d+\.xml$")
_XML_PART = re.compile(r"\.(xml|rels|xhtml|opf|ncx|html)$", re.I)
_ENTITY_WINDOW = 8192


@dataclass
class Inspection:
    page_count: int | None = None
    facts: dict = field(default_factory=dict)


def _is_name(obj, *names: str) -> bool:
    try:
        return isinstance(obj, pikepdf.Name) and str(obj) in names
    except Exception:  # noqa: BLE001
        return False


def _walk(obj, active: set[str], depth: int = 0) -> int:
    """Collect action names that can run code from `obj` and the objects nested directly inside it (an /OpenAction
    is usually a direct dictionary, which `pdf.objects` does not list on its own). Returns embedded-file streams
    seen. Indirect references are not followed: every indirect object is visited once by the caller."""
    if depth > 40:
        return 0
    found = 0
    if isinstance(obj, pikepdf.Dictionary | pikepdf.Stream):
        s = obj.get("/S")
        if s is not None and _is_name(s, *_ACTIVE_ACTIONS):
            active.add(str(s))
        if "/JS" in obj:
            active.add("/JavaScript")
        if _is_name(obj.get("/Type"), "/EmbeddedFile"):
            found += 1
        for _, v in obj.items():
            if not getattr(v, "is_indirect", False):
                found += _walk(v, active, depth + 1)
    elif isinstance(obj, pikepdf.Array):
        for v in obj:
            if not getattr(v, "is_indirect", False):
                found += _walk(v, active, depth + 1)
    return found


def inspect_pdf(
    data: bytes, *, max_pages: int, reject_encrypted: bool, reject_active: bool
) -> Inspection:
    try:
        pdf = pikepdf.open(io.BytesIO(data))
    except pikepdf.PasswordError:
        raise Refusal(
            "encrypted", "That PDF is password-protected. Remove the password and upload it again."
        ) from None
    except (pikepdf.PdfError, ValueError, RuntimeError):
        raise Refusal("corrupt", "That PDF is damaged and could not be opened.") from None
    with pdf:
        if pdf.is_encrypted and reject_encrypted:
            raise Refusal(
                "encrypted", "That PDF is encrypted. Save an unprotected copy and upload that."
            )
        pages = len(pdf.pages)
        if pages > max_pages:
            raise Refusal(
                "too_many_pages",
                f"That PDF has {pages} pages, and the limit for your account is {max_pages}. Split it and upload the parts.",
            )
        active: set[str] = set()
        embedded = 0
        for obj in pdf.objects:  # every indirect object; direct children are walked from each
            embedded += _walk(obj, active)
        if active and reject_active:
            raise Refusal(
                "active_content",
                "That PDF contains scripts or actions that can run code, so we cannot accept it. "
                "Save a copy without them (for example by printing to PDF) and upload that.",
            )
        root = pdf.Root
        mark = root.get("/MarkInfo")
        return Inspection(
            pages,
            {
                "pdf_version": str(pdf.pdf_version),
                "tagged": bool(mark is not None and mark.get("/Marked", False)),
                "has_struct_tree": "/StructTreeRoot" in root,
                "has_lang": "/Lang" in root,
                "embedded_files": embedded,
                "active_content": sorted(active),
            },
        )


def inspect_zip_document(
    data: bytes, kind: str, *, max_pages: int, reject_active: bool
) -> Inspection:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise Refusal("corrupt", "That file is damaged and could not be opened.") from None
    names = zf.namelist()
    macros = [n for n in names if n.lower().endswith("vbaproject.bin")]
    embeddings = [n for n in names if "/embeddings/" in n.lower()]
    if macros and reject_active:
        raise Refusal(
            "active_content",
            "That file contains macros, so we cannot accept it. Save a copy without macros and upload that.",
        )
    for n in names:
        if _XML_PART.search(n):
            with zf.open(n) as f:
                head = f.read(_ENTITY_WINDOW)
            if b"<!ENTITY" in head:
                raise Refusal(
                    "xml_entities",
                    "That file contains a construct that is used to attack document readers, so we cannot accept it.",
                )
    pages: int | None = None
    if kind == "pptx":
        pages = sum(1 for n in names if _SLIDE.match(n))
        if pages > max_pages:
            raise Refusal(
                "too_many_pages",
                f"That presentation has {pages} slides, and the limit for your account is {max_pages}.",
            )
    return Inspection(pages, {"macros": bool(macros), "embedded_objects": len(embeddings)})


def inspect_document(
    data: bytes, kind: str, *, max_pages: int, reject_encrypted: bool, reject_active: bool
) -> Inspection:
    if kind == "pdf":
        return inspect_pdf(
            data,
            max_pages=max_pages,
            reject_encrypted=reject_encrypted,
            reject_active=reject_active,
        )
    return inspect_zip_document(data, kind, max_pages=max_pages, reject_active=reject_active)
