"""V1: deterministic checks on a proposed fix (PROJECT_PLAN 3.13). No tokens, no opinions.

A model's output is untrusted text. These checks run on every fix, whoever produced it, before the re-scan oracle."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from .tag import Tag

MAX_FIX_CHARS = 3000
# Attributes that carry the page's own wiring: a fix must not rewrite them.
KEEP_UNCHANGED = (
    "href",
    "src",
    "action",
    "formaction",
    "id",
    "for",
    "name",
    "type",
    "value",
    "data-",
)
_FILE = re.compile(r"\.(png|jpe?g|gif|svg|webp|avif|bmp|ico)\b|^[\w-]+\d{2,}[\w-]*$", re.I)
_IMAGE_OF = re.compile(
    r"^\s*(an? )?(image|picture|photo|graphic|icon|screenshot)( of| showing)?\b", re.I
)
_GENERIC = {
    "image",
    "picture",
    "photo",
    "graphic",
    "icon",
    "button",
    "link",
    "click here",
    "here",
    "read more",
    "more",
    "img",
}
_URL = re.compile(r"(?:https?:)?//[^\s\"'<>]+", re.I)


@dataclass
class Check:
    name: str  # a short, plain-language statement shown to the person
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


class _Collect(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, list[tuple[str, str | None]]]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, attrs))

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, attrs))


def _tags(src: str):
    p = _Collect()
    p.feed(src)
    p.close()
    return p.tags


def _words_ok(label: str, *, decorative_ok: bool) -> str | None:
    s = label.strip()
    if not s:
        return None if decorative_ok else "is empty"
    if len(s) > 125:
        return "is longer than 125 characters"
    if _IMAGE_OF.match(s):
        return 'starts with "image of" or similar: screen readers already say it is an image'
    if _FILE.search(s):
        return "looks like a file name"
    if s.lower() in _GENERIC:
        return "is too generic to tell people anything"
    return None


def static_checks(original: Tag, fixed: str, *, removes: bool) -> list[Check]:
    out: list[Check] = []
    out.append(
        Check(
            "The fix is short enough to review",
            len(fixed) <= MAX_FIX_CHARS,
            f"{len(fixed)} characters",
        )
    )
    try:
        tags = _tags(fixed)
        out.append(
            Check(
                "The fix is valid HTML",
                bool(tags) or removes,
                "" if tags or removes else "no element found",
            )
        )
    except Exception as e:  # noqa: BLE001
        tags = []
        out.append(Check("The fix is valid HTML", False, str(e)[:120]))
        return out

    names = {n for n, _ in tags}
    bad = names & {"script", "style", "iframe", "object", "embed", "form", "base", "link"} - {
        original.name
    }
    # Event handlers (onclick, onchange...) that the customer's own element already had are theirs and may stay as they are;
    # a fix must not ADD one or CHANGE one. Compared by name and value on the element itself, never by searching the text.
    mine = set(original.attrs)
    handlers = sorted(
        f"{k}"
        for n, attrs in tags
        for k, v in attrs
        if k.startswith("on") and not (n == original.name and (k, v) in mine)
    )
    out.append(
        Check(
            "The fix adds no scripts or embedded content",
            not bad and not handlers,
            ", ".join(sorted(bad) + handlers),
        )
    )
    js = re.search(
        r"(?:href|src|action|formaction)\s*=\s*[\"']?\s*(?:javascript|data):", fixed, re.I
    )
    out.append(Check("The fix adds no script links", not js))
    new_urls = set(_URL.findall(fixed)) - set(_URL.findall(original.render()))
    out.append(
        Check("The fix adds no new web addresses", not new_urls, ", ".join(sorted(new_urls))[:120])
    )

    # The element itself: the first tag that matches the original's name must keep its wiring unchanged.
    me = next((a for n, a in tags if n == original.name), None)
    if me is not None and not removes:
        mine = dict(me)
        changed = []
        for k, v in original.attrs:
            if k.startswith(KEEP_UNCHANGED) and mine.get(k) != v:
                changed.append(k)
        out.append(
            Check("Links, ids and field names are unchanged", not changed, ", ".join(changed))
        )

    # Text we invented that people will read or hear.
    decorative = (
        original.get("role") in ("presentation", "none") or original.get("aria-hidden") == "true"
    )
    problems: list[str] = []
    for n, attrs in tags:
        for k, v in attrs:
            if k in ("alt", "aria-label") and v is not None:
                before = original.get(k) if n == original.name else None
                if v == before:
                    continue
                if why := _words_ok(v, decorative_ok=(k == "alt" and (decorative or v == ""))):
                    problems.append(f'{k}="{v[:40]}" {why}')
    out.append(
        Check(
            "Any text we wrote for screen readers is meaningful", not problems, "; ".join(problems)
        )
    )
    return out
