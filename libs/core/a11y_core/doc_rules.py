"""Plain-language text for document checks (rules/documents/*.yaml). Same policy as the web rule content: `draft` until
an accessibility specialist has reviewed it. A check we have no text for is still shown, honestly marked as one we do not
yet explain, with its source description, and as needing a person: we never hide a failure because we lack wording."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from .rules import rules_dir

SEVERITIES = ("critical", "serious", "moderate", "minor")


@dataclass(frozen=True)
class RuleText:
    rule_id: str
    severity: str
    title: str
    why: str
    fix: str
    wcag: tuple[str, ...] = field(default_factory=tuple)
    needs_human: bool = False
    explained: bool = True  # False when we fell back to the clause or to the generic text


@lru_cache
def _catalog() -> dict:
    return yaml.safe_load((rules_dir() / "documents" / "pdfua1.yaml").read_text())


def catalog_rule_ids() -> list[str]:
    return sorted(_catalog()["rules"])


def lookup(clause: str, test: int, description: str = "") -> RuleText:
    """Text for veraPDF rule `<clause>-<test>` (e.g. "7.3-1")."""
    rid = f"{clause}-{test}"
    cat = _catalog()
    if (r := cat["rules"].get(rid)) is not None:
        return RuleText(
            rid, r["severity"], r["title"], r["why"], r["fix"], tuple(r.get("wcag", [])), bool(r.get("needs_human")), True
        )
    # Fall back to the longest matching clause prefix: "7.4.2" -> "7.4".
    parts = clause.split(".")
    for n in range(len(parts), 0, -1):
        c = cat["clauses"].get(".".join(parts[:n]))
        if c is not None:
            return RuleText(
                rid,
                c["severity"],
                (description[:140] or f"A check in the area “{c['area']}” failed"),
                f"{c['why']} We do not have a plain-language explanation of this exact check yet.",
                "Open the file in an accessibility checker, such as the free PAC or Acrobat's accessibility checker, for the exact location and fix guidance.",
                (),
                True,
                False,
            )
    return RuleText(
        rid,
        "moderate",
        description[:140] or "A PDF/UA check failed",
        "This is a check from the PDF/UA standard that we do not yet explain in plain language.",
        "Open the file in an accessibility checker, such as the free PAC or Acrobat's accessibility checker, for the exact location and fix guidance.",
        (),
        True,
        False,
    )
