"""A start tag, parsed and re-serialised.

The scanner records only an element's OPENING tag (never its children: smaller, and it keeps page text out of
our database). So a fix is a patch to that tag, optionally with a short sibling such as a <label>."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


@dataclass
class Tag:
    name: str
    attrs: list[tuple[str, str | None]] = field(default_factory=list)
    self_closing: bool = False
    closed: bool = False  # had its own (empty) end tag, as the scanner records non-void elements

    def get(self, key: str) -> str | None:
        return next((v for k, v in self.attrs if k == key), None)

    def has(self, key: str) -> bool:
        return any(k == key for k, _ in self.attrs)

    def set(self, key: str, value: str | None) -> None:
        for i, (k, _) in enumerate(self.attrs):
            if k == key:
                self.attrs[i] = (key, value)
                return
        self.attrs.append((key, value))

    def remove(self, key: str) -> None:
        self.attrs = [(k, v) for k, v in self.attrs if k != key]

    def copy(self) -> Tag:
        return Tag(self.name, list(self.attrs), self.self_closing, self.closed)

    def render(self) -> str:
        parts = [self.name]
        for k, v in self.attrs:
            parts.append(k if v is None else f'{k}="{html.escape(v, quote=True)}"')
        slash = " /" if self.self_closing and self.name in VOID else ""
        end = f"</{self.name}>" if self.closed and self.name not in VOID else ""
        return "<" + " ".join(parts) + slash + ">" + end


class _One(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[Tag] = []
        self.other = False
        self.ends: list[str] = []

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text() or ""
        self.tags.append(Tag(tag, [(k, v) for k, v in attrs], raw.rstrip().endswith("/>")))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if data.strip():
            self.other = True

    def handle_endtag(self, tag):
        self.ends.append(tag)


def parse_tag(src: str) -> Tag | None:
    """The one start tag in ``src``, or None if there is not exactly one complete start tag (for instance
    when the scanner cut a very long tag short)."""
    p = _One()
    try:
        p.feed(src.strip())
        p.close()
    except Exception:  # noqa: BLE001 - malformed input is just "not a tag"
        return None
    if len(p.tags) != 1 or p.other or not src.strip().endswith(">"):
        return None
    tag = p.tags[0]
    if p.ends and (p.ends != [tag.name] or tag.name in VOID):
        return None  # more than the element's own empty end tag: not a lone element
    tag.closed = bool(p.ends)
    return tag
