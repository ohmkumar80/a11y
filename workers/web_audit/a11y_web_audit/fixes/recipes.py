"""Rung 2 of the resolution ladder: deterministic patches for patterns we can fix without a model.

A recipe never invents content. Where a fix needs a human choice (what an image shows, what language a page is
in) it either declines, or states the assumption in ``notes`` so the person sees it next to the fix."""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .tag import Tag


@dataclass
class Fix:
    fixed_html: str  # may be empty: the fix is to remove the element
    explanation: str
    notes: list[str] = field(default_factory=list)
    removes: bool = False


ARIA_ROLES = frozenset(
    "alert alertdialog application article banner blockquote button caption cell checkbox code columnheader "
    "combobox complementary contentinfo definition deletion dialog directory document emphasis feed figure form "
    "generic grid gridcell group heading img insertion link list listbox listitem log main marquee math meter "
    "menu menubar menuitem menuitemcheckbox menuitemradio navigation none note option paragraph presentation "
    "progressbar radio radiogroup region row rowgroup rowheader scrollbar search searchbox separator slider "
    "spinbutton status strong subscript superscript switch tab table tablist tabpanel term textbox time timer "
    "toolbar tooltip tree treegrid treeitem".split()
)
_NO_LABEL_TYPES = {"hidden", "submit", "button", "reset", "image"}


def _meta_refresh(t: Tag) -> Fix | None:
    if t.name == "meta" and (t.get("http-equiv") or "").lower() == "refresh":
        return Fix(
            "",
            "Remove this tag. A page that redirects or reloads itself on a timer can pull people away before they finish "
            "reading. If you need a redirect, do it on the server, or give a link people choose to follow.",
            removes=True,
        )
    return None


def _viewport_zoom(t: Tag) -> Fix | None:
    if t.name != "meta" or (t.get("name") or "").lower() != "viewport":
        return None
    keep: list[str] = []
    for part in (t.get("content") or "").split(","):
        k, _, v = (x.strip().lower() for x in part.partition("="))
        if not k:
            continue
        if k == "user-scalable" and v in ("no", "0", "false"):
            continue
        if k == "maximum-scale":
            try:
                if float(v) < 5:
                    continue
            except ValueError:
                continue
        keep.append(part.strip())
    if len(keep) == len([p for p in (t.get("content") or "").split(",") if p.strip()]):
        return None
    n = t.copy()
    n.set("content", ", ".join(keep) or "width=device-width, initial-scale=1")
    return Fix(
        n.render(),
        "Remove the settings that stop people zooming. People with low vision rely on pinch-zoom to read.",
    )


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:30] or "field"


def _form_label(t: Tag) -> Fix | None:
    if t.name not in ("input", "select", "textarea"):
        return None
    if (t.get("type") or "text").lower() in _NO_LABEL_TYPES:
        return None
    if t.get("aria-label") or t.get("aria-labelledby"):
        return None
    text = (t.get("placeholder") or t.get("title") or "").strip()
    notes = ["Place the label where you want it to appear, next to the field."]
    if not text:
        text = re.sub(r"[_-]+", " ", t.get("name") or "").strip().capitalize()
        if not text:
            return None
        notes.append(f'We took the label text "{text}" from the field name: check the wording.')
    n = t.copy()
    fid = n.get("id") or f"field-{_slug(text)}"
    n.set("id", fid)
    label = f'<label for="{html.escape(fid, quote=True)}">{html.escape(text)}</label>'
    return Fix(
        f"{label}\n{n.render()}",
        "Add a visible label and connect it to the field. A placeholder is not a label: it disappears as you type "
        "and screen readers do not reliably announce it.",
        notes,
    )


def _moving_content(t: Tag) -> Fix | None:
    repl = {"marquee": "div", "blink": "span"}.get(t.name)
    if not repl:
        return None
    n = Tag(
        repl,
        [
            (k, v)
            for k, v in t.attrs
            if k
            not in ("behavior", "direction", "loop", "scrollamount", "scrolldelay", "truespeed")
        ],
    )
    return Fix(
        n.render(),
        f"Replace <{t.name}> with a plain <{repl}>. Moving and blinking text is hard to read and cannot be paused. "
        "If movement is needed, add a pause button.",
        ["Keep the content between the tags as it is; only the opening tag changes."],
    )


def _html_lang(t: Tag) -> Fix | None:
    if t.name != "html" or (t.get("lang") or "").strip():
        return None
    n = t.copy()
    n.set("lang", "en")
    return Fix(
        n.render(),
        "Set the page language so screen readers choose the right voice and pronunciation.",
        [
            "We assumed English (en). Change it if the page is mainly in another language, for example ta or hi."
        ],
    )


def _aria_roles(t: Tag) -> Fix | None:
    role = t.get("role")
    if role is None:
        return None
    tokens = role.split()
    good = [r for r in tokens if r.lower() in ARIA_ROLES]
    if len(good) == len(tokens):
        return None
    n = t.copy()
    if good:
        n.set("role", " ".join(good))
    else:
        n.remove("role")
    return Fix(
        n.render(),
        "Remove the role that is not a real ARIA role. An unknown role is ignored, so it does nothing but confuse readers of the code.",
        [
            "If the element should behave like a button, link or similar, use the native element instead."
        ],
    )


RECIPES: dict[str, Callable[[Tag], Fix | None]] = {
    "meta-refresh": _meta_refresh,
    "viewport-zoom": _viewport_zoom,
    "form-field-label": _form_label,
    "moving-content": _moving_content,
    "html-lang": _html_lang,
    "aria-roles": _aria_roles,
}
