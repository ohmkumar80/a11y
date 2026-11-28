"""Accessibility check for generated DOCX files: the gate before a Word report may be downloaded
(PROJECT_PLAN 2.5). Checks what a machine can: document title and language, real heading styles in order,
header rows on every table (marked to repeat), alternative text on every picture."""

from __future__ import annotations

import io
import re
import zipfile

import defusedxml.ElementTree as ET  # untrusted input later (customer uploads): no XML entity tricks
from defusedxml import DefusedXmlException

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
DC = "{http://purl.org/dc/elements/1.1/}"


def check_docx(data: bytes) -> list[str]:
    problems: list[str] = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        doc = ET.fromstring(z.read("word/document.xml"))
        styles = ET.fromstring(z.read("word/styles.xml"))
        core = ET.fromstring(z.read("docProps/core.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, DefusedXmlException):
        return ["not a valid Word document"]

    title = core.find(f"{DC}title")
    if title is None or not (title.text or "").strip():
        problems.append("the document has no title property")

    lang = None
    for el in styles.iter(f"{W}lang"):
        lang = el.get(f"{W}val")
        break
    if not lang:
        problems.append("the document language is not set")

    levels: list[int] = []
    for p in doc.iter(f"{W}p"):
        st = p.find(f"{W}pPr/{W}pStyle")
        m = re.fullmatch(r"Heading(\d)", st.get(f"{W}val", "")) if st is not None else None
        if m:
            levels.append(int(m.group(1)))
    if not levels:
        problems.append("the document has no headings")
    else:
        if levels[0] != 1:
            problems.append("the first heading is not level 1")
        for a, b in zip(levels, levels[1:], strict=False):
            if b > a + 1:
                problems.append(f"heading level jumps from {a} to {b}")
                break

    for i, tbl in enumerate(doc.iter(f"{W}tbl"), 1):
        first = tbl.find(f"{W}tr")
        if first is None or first.find(f"{W}trPr/{W}tblHeader") is None:
            problems.append(f"table {i} has no header row that repeats on each page")

    for pic in doc.iter(f"{WP}docPr"):
        if not (pic.get("descr") or "").strip():
            problems.append("a picture has no alternative text")
    return problems
