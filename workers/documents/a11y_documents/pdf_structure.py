"""Read the editable parts of a tagged PDF: its figures, headings and document properties (ADR 0022).

Everything here is read-only and bounded (node and text caps), because the file is untrusted. Elements are addressed by
their PDF object number (`"12-0"`), which is stable inside one file and is what the fix operations refer to. Only INDIRECT
structure elements can be addressed; the rare direct ones are listed as not editable rather than guessed at."""

from __future__ import annotations

import contextlib
import io
import re
from dataclasses import dataclass, field

import pikepdf

MAX_NODES = 60_000
MAX_DEPTH = 80
MAX_ITEMS = 500
MAX_TEXT = 160
_HEADING = re.compile(r"^H([1-6])$")


@dataclass
class Structure:
    has_structure: bool = False
    title: str = ""
    language: str = ""
    pages: int = 0
    figures: list[dict] = field(default_factory=list)
    headings: list[dict] = field(default_factory=list)
    truncated: bool = False

    def as_dict(self) -> dict:
        return {
            "has_structure": self.has_structure,
            "title": self.title,
            "language": self.language,
            "pages": self.pages,
            "figures": self.figures,
            "headings": self.headings,
            "truncated": self.truncated,
        }


def element_id(obj) -> str | None:
    try:
        n, g = obj.objgen
    except Exception:  # noqa: BLE001
        return None
    return f"{n}-{g}" if n else None


def find_element(pdf: pikepdf.Pdf, eid: str):
    """The structure element object with this id, or None. Never resolves ids that are not plain `<n>-<g>`."""
    m = re.fullmatch(r"(\d{1,9})-(\d{1,5})", eid or "")
    if not m:
        return None
    try:
        return pdf.get_object((int(m.group(1)), int(m.group(2))))
    except Exception:  # noqa: BLE001
        return None


def _role(el, rolemap) -> str:
    s = str(el.get("/S", ""))[1:]
    seen = 0
    while rolemap is not None and f"/{s}" in rolemap and seen < 5:  # custom tag -> standard tag
        s = str(rolemap[f"/{s}"])[1:]
        seen += 1
    return s


def _mcids(el, depth: int = 0) -> list[int]:
    """Marked-content ids under an element, including its descendants (a heading's text usually sits in child spans)."""
    out: list[int] = []
    if depth > 12:
        return out
    k = el.get("/K")
    items = [k] if k is not None and not isinstance(k, pikepdf.Array) else list(k or [])
    for it in items:
        if isinstance(it, int):
            out.append(int(it))
        elif isinstance(it, pikepdf.Dictionary):
            if "/MCID" in it:
                out.append(int(it.MCID))
            elif "/S" in it:
                out.extend(_mcids(it, depth + 1))
    return out[:200]


def _walk_text(pdf, page, wanted: set[int]) -> dict[int, str]:
    """Best-effort text for the marked-content ids in `wanted` on one page."""
    from .pdf_text import mcid_text  # noqa: PLC0415

    with contextlib.suppress(Exception):
        return mcid_text(pdf, page, wanted)
    return {}


def inspect_structure(data: bytes) -> Structure:
    s = Structure()
    pdf = pikepdf.open(io.BytesIO(data))
    with pdf:
        root = pdf.Root
        s.pages = len(pdf.pages)
        with contextlib.suppress(Exception):
            s.title = str(pdf.docinfo.get("/Title", "")).strip()
        s.language = str(root.get("/Lang", "")).strip()
        if "/StructTreeRoot" not in root:
            return s
        s.has_structure = True
        str_root = root.StructTreeRoot
        rolemap = str_root.get("/RoleMap")
        page_index = {pg.objgen: i + 1 for i, pg in enumerate(pdf.pages)}
        raw_figs: list[tuple[dict, list[int], int | None]] = []
        raw_heads: list[tuple[dict, list[int], int | None]] = []
        nodes = 0

        def children(k) -> list:
            if k is None:
                return []
            return list(k) if isinstance(k, pikepdf.Array) else [k]

        # Depth-first in document order: push siblings reversed so the first one is popped first.
        stack = [(el, None, 0) for el in reversed(children(str_root.get("/K")))]
        while stack:
            el, inherited_pg, depth = stack.pop()
            if not isinstance(el, pikepdf.Dictionary) or depth > MAX_DEPTH:
                continue
            nodes += 1
            if nodes > MAX_NODES:
                s.truncated = True
                break
            if "/S" not in el:  # a marked-content reference or similar: nothing to list
                continue
            pg_obj = el.get("/Pg")
            pg = page_index.get(pg_obj.objgen) if pg_obj is not None else inherited_pg
            role = _role(el, rolemap)
            eid = element_id(el)
            if role == "Figure" and len(raw_figs) < MAX_ITEMS:
                raw_figs.append(
                    (
                        {
                            "id": eid,
                            "editable": eid is not None,
                            "page": pg,
                            "alt": str(el.get("/Alt", "")).strip(),
                            "actual_text": str(el.get("/ActualText", "")).strip(),
                        },
                        _mcids(el),
                        pg,
                    )
                )
            elif ((m := _HEADING.match(role)) or role == "H") and len(raw_heads) < MAX_ITEMS:
                raw_heads.append(
                    (
                        {
                            "id": eid,
                            "editable": eid is not None,
                            "page": pg,
                            "level": int(m.group(1)) if m else 1,
                            "generic": role == "H",
                        },
                        _mcids(el),
                        pg,
                    )
                )
            for child in reversed(children(el.get("/K"))):
                stack.append((child, pg, depth + 1))
        # Text for headings, read from the page content by marked-content id (best effort).
        by_page: dict[int, set[int]] = {}
        for _, mc, pg in raw_heads:
            if pg:
                by_page.setdefault(pg, set()).update(mc)
        texts: dict[int, dict[int, str]] = {}
        for pg, wanted in by_page.items():
            if wanted and pg - 1 < len(pdf.pages):
                texts[pg] = _walk_text(pdf, pdf.pages[pg - 1], wanted)
        s.figures = [f for f, _, _ in raw_figs]
        for h, mc, pg in raw_heads:
            t = " ".join(texts.get(pg or 0, {}).get(i, "") for i in mc).strip()
            h["text"] = re.sub(r"\s+", " ", t)[:MAX_TEXT]
            s.headings.append(h)
    return s
