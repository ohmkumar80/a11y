"""Best-effort text for marked-content ids on a page, for showing a person which heading is which (ADR 0022).

It decodes simple strings through the font's ToUnicode map when there is one, and as Latin-1 for simple fonts otherwise. It
never fails the caller: anything it cannot read is left out, and the editor then shows "text not available"."""

from __future__ import annotations

import contextlib
import re

import pikepdf

_TEXT_OPS = {"Tj", "'", '"', "TJ"}
_BFCHAR = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_BFRANGE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
MAX_OPS = 200_000


def _hex_to_str(h: bytes) -> str:
    return bytes.fromhex(h.decode()).decode("utf-16-be", "replace")


def _parse_tounicode(stream) -> tuple[dict[int, str], int]:
    data = stream.read_bytes()[:2_000_000]
    mapping: dict[int, str] = {}
    width = 1
    if (m := re.search(rb"begincodespacerange\s*<([0-9A-Fa-f]+)>", data)) is not None:
        width = max(1, len(m.group(1)) // 2)
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for a, b in _BFCHAR.findall(block):
            mapping[int(a, 16)] = _hex_to_str(b)
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for a, b, c in _BFRANGE.findall(block):
            lo, hi, start = int(a, 16), int(b, 16), int(c, 16)
            for i in range(min(hi - lo + 1, 65536)):
                mapping[lo + i] = chr(start + i)
    return mapping, width


class _Font:
    def __init__(self, font) -> None:
        self.map: dict[int, str] = {}
        self.width = 1
        self.usable = True
        with contextlib.suppress(Exception):
            if "/ToUnicode" in font:
                self.map, self.width = _parse_tounicode(font.ToUnicode)
            elif str(font.get("/Subtype")) == "/Type0":
                self.usable = False  # a composite font with no map: we cannot know the characters

    def decode(self, raw: bytes) -> str:
        if not self.usable:
            return ""
        if not self.map:
            return raw.decode("latin-1")
        w = self.width
        return "".join(
            self.map.get(int.from_bytes(raw[i : i + w], "big"), "") for i in range(0, len(raw), w)
        )


def mcid_text(pdf, page, wanted: set[int]) -> dict[int, str]:
    fonts: dict[str, _Font] = {}
    resources = page.get("/Resources")
    font_res = resources.get("/Font") if resources is not None else None
    props = resources.get("/Properties") if resources is not None else None
    cur_font: _Font | None = None
    stack: list[int | None] = []
    out: dict[int, list[str]] = {}
    n = 0
    for operands, op in pikepdf.parse_content_stream(page):
        n += 1
        if n > MAX_OPS:
            break
        name = str(op)
        if name == "BDC":
            mcid = None
            prop = operands[1] if len(operands) > 1 else None
            if isinstance(prop, pikepdf.Name) and props is not None and str(prop) in props:
                prop = props[str(prop)]
            if isinstance(prop, pikepdf.Dictionary) and "/MCID" in prop:
                mcid = int(prop.MCID)
            stack.append(mcid)
        elif name == "BMC":
            stack.append(None)
        elif name == "EMC":
            if stack:
                stack.pop()
        elif name == "Tf" and font_res is not None and operands:
            key = str(operands[0])
            if key not in fonts and key in font_res:
                fonts[key] = _Font(font_res[key])
            cur_font = fonts.get(key)
        elif name in _TEXT_OPS:
            active = next((m for m in reversed(stack) if m is not None), None)
            if active is None or active not in wanted:
                continue
            strings = []
            if name == "TJ":
                strings = [bytes(x) for x in operands[0] if isinstance(x, pikepdf.String)]
            elif operands and isinstance(operands[-1], pikepdf.String):
                strings = [bytes(operands[-1])]
            font = cur_font or _Font({})
            out.setdefault(active, []).extend(font.decode(s) for s in strings)
    return {k: "".join(v) for k, v in out.items()}
