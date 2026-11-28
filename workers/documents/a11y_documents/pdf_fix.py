"""Apply a guided-fix plan to a PDF (ADR 0022). The original is never touched: this returns new bytes.

Only changes that need no guesswork are made: document properties, the text alternative of an existing figure, and the level
of an existing heading. Nothing is added to or removed from the page content, so what a sighted reader sees is unchanged."""

from __future__ import annotations

import contextlib
import io

import pikepdf
from a11y_core.doc_fix import FixPlan

from .pdf_structure import _HEADING, _role, find_element


class FixError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def apply_plan(data: bytes, plan: FixPlan) -> bytes:
    try:
        pdf = pikepdf.open(io.BytesIO(data))
    except (pikepdf.PdfError, pikepdf.PasswordError, ValueError):
        raise FixError("corrupt", "That PDF could not be opened.") from None
    with pdf:
        root = pdf.Root
        rolemap = root.StructTreeRoot.get("/RoleMap") if "/StructTreeRoot" in root else None
        if plan.title:
            pdf.docinfo["/Title"] = pikepdf.String(plan.title)
            vp = root.get("/ViewerPreferences")
            if vp is None:
                root.ViewerPreferences = pdf.make_indirect(pikepdf.Dictionary(DisplayDocTitle=True))
            else:
                vp["/DisplayDocTitle"] = True
        if plan.language:
            root.Lang = pikepdf.String(plan.language)
        # Create XMP metadata only when a title is being set (it then carries the title). Writing metadata for a language alone
        # would make the checker start looking at a title the file never had, which would look like a new problem.
        if plan.title or (plan.language and "/Metadata" in root):
            with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as meta:
                if plan.title:
                    meta["dc:title"] = plan.title
                if plan.language:
                    meta["dc:language"] = [plan.language]
        for eid, alt in plan.alt.items():
            el = find_element(pdf, eid)
            if not isinstance(el, pikepdf.Dictionary) or _role(el, rolemap) != "Figure":
                raise FixError("stale_plan", "An image you described is no longer in the file.")
            el["/Alt"] = pikepdf.String(alt)
        for eid, level in plan.heading_levels.items():
            el = find_element(pdf, eid)
            if not isinstance(el, pikepdf.Dictionary):
                raise FixError("stale_plan", "A heading you changed is no longer in the file.")
            r = _role(el, rolemap)
            if not (_HEADING.match(r) or r == "H"):
                raise FixError("stale_plan", "A heading you changed is no longer in the file.")
            el["/S"] = pikepdf.Name(f"/H{level}")
        if "/StructTreeRoot" in root:
            mark = root.get("/MarkInfo")
            if mark is None:
                root.MarkInfo = pdf.make_indirect(pikepdf.Dictionary(Marked=True))
            else:
                mark["/Marked"] = True
        out = io.BytesIO()
        pdf.save(out)
    with contextlib.suppress(Exception):
        pikepdf.open(io.BytesIO(out.getvalue())).close()  # the result must open again
    return out.getvalue()
