"""Rule registry (PROJECT_PLAN 3.8): WCAG criteria, standards, canonical cross-engine rules.

The data lives in the repo-root ``rules/`` directory (YAML, version-controlled, SME-reviewed) and is
validated on load: unknown criteria, dangling bases or duplicate mappings fail loudly at startup, never
silently at scan time. Nothing here claims compliance: ``summarise`` reports AUTOMATED COVERAGE only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

LEVELS = ("A", "AA", "AAA")
WCAG_VERSIONS = ("2.0", "2.1", "2.2")


def rules_dir() -> Path:
    if env := os.environ.get("A11Y_RULES_DIR"):
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        if (parent / "rules" / "wcag.yaml").exists():
            return parent / "rules"
    raise FileNotFoundError("rules/ directory not found (set A11Y_RULES_DIR)")


def _sc_key(sc: str) -> list[int]:
    return [int(x) for x in sc.split(".")]


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


class Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    level: Literal["A", "AA", "AAA"]
    since: Literal["2.0", "2.1", "2.2"]
    removed_in: Literal["2.2"] | None = None


class Standard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    kind: Literal["wcag", "derived"]
    wcag_version: Literal["2.0", "2.1", "2.2"] | None = None
    level: Literal["A", "AA", "AAA"] | None = None
    base: str | None = None
    legal_status: Literal[
        "regulation", "benchmark", "recommended_target", "reference", "informational"
    ]
    clause_format: str | None = None
    citation: str | None = None
    notes: str | None = None


class EngineRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    tags: list[str] = Field(
        default_factory=list
    )  # element tag names this mapping applies to; empty = any


def _refs(v: list) -> list[EngineRef]:
    return [EngineRef(id=x) if isinstance(x, str) else EngineRef(**x) for x in v]


class CanonicalRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    sc: list[str]
    scope: Literal["element", "document"] = "element"
    best_practice: bool = False
    verified: str | None = None
    axe: list[EngineRef] = Field(default_factory=list)
    ibm: list[EngineRef] = Field(default_factory=list)
    htmlcs: list[EngineRef] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, d):
        for k in ("axe", "ibm", "htmlcs"):
            d[k] = _refs(d.get(k) or [])
        return d

    def engines_covering(self) -> set[str]:
        return {e for e in ("axe", "ibm", "htmlcs") if getattr(self, e)}


class ContentLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    url: str

    @model_validator(mode="after")
    def _https(self):
        if not self.url.startswith("https://"):
            raise ValueError(f"link {self.url!r} must be https")
        return self


class ContentExample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stack: Literal["html", "react"]
    before: str
    after: str


class RuleContent(BaseModel):
    """Plain-language guidance for one canonical rule (PROJECT_PLAN 3.13). ``draft`` until an
    accessibility SME reviews it, like the standards mappings; the UI says so."""

    model_config = ConfigDict(extra="forbid")
    id: str
    status: Literal["draft", "reviewed"] = "draft"
    summary: str = Field(min_length=10)
    why: str = Field(min_length=10)
    who: list[str] = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    examples: list[ContentExample] = Field(min_length=1)
    links: list[ContentLink] = []
    test: str = ""
    # False when no engine can tell a bad example from a good one: a person must check the fix.
    machine_check: bool = True
    manual_reason: str = ""

    def html_example(self) -> ContentExample:
        return next(e for e in self.examples if e.stack == "html")

    @model_validator(mode="after")
    def _needs_html_example(self):
        if not self.machine_check and not self.manual_reason:
            raise ValueError(f"{self.id}: say why it cannot be machine-checked")
        if not any(e.stack == "html" for e in self.examples):
            raise ValueError(
                f"{self.id}: needs an html example (it is what the re-scan oracle checks)"
            )
        return self


@dataclass(frozen=True)
class Summary:
    """Per-standard result. Deliberately NOT a pass/fail or a percentage 'score': automated tools
    test only part of WCAG (PROJECT_PLAN 1.7)."""

    standard: str
    criteria_total: int
    failed: list[str]  # criteria with at least one automated failure
    needs_review: list[str]  # criteria with only 'needs review' items
    no_issues_found: list[str]  # automated checks exist and found nothing; NOT proof of conformance
    not_tested: list[str]  # no automated check can tell: needs manual evaluation

    @property
    def automated_coverage(self) -> tuple[int, int]:
        tested = len(self.failed) + len(self.needs_review) + len(self.no_issues_found)
        return tested, self.criteria_total


class Registry:
    def __init__(self, root: Path) -> None:
        wcag = yaml.safe_load((root / "wcag.yaml").read_text())
        std = yaml.safe_load((root / "standards.yaml").read_text())
        can = yaml.safe_load((root / "canonical.yaml").read_text())
        cat = json.loads((root / "engine-catalog.json").read_text())

        self.criteria: dict[str, Criterion] = {c["id"]: Criterion(**c) for c in wcag["criteria"]}
        self.standards: dict[str, Standard] = {s["id"]: Standard(**s) for s in std["standards"]}
        self.standards_version: str = std["version"]
        self.review: dict = std["review"]
        self.canonical: dict[str, CanonicalRule] = {}
        for r in can["rules"]:
            cr = CanonicalRule(**r)
            if cr.id in self.canonical:
                raise ValueError(f"duplicate canonical rule {cr.id}")
            self.canonical[cr.id] = cr
        self.content: dict[str, RuleContent] = {}
        for f in sorted((root / "content").glob("*.yaml")):
            rc = RuleContent(**yaml.safe_load(f.read_text()))
            if rc.id != f.stem:
                raise ValueError(f"content file {f.name} declares id {rc.id!r}")
            if rc.id in self.content:
                raise ValueError(f"duplicate content for {rc.id}")
            self.content[rc.id] = rc
        self.engine_versions: dict[str, str] = cat["engine_versions"]
        self.automated_sc: set[str] = set(cat["automated_sc_coverage"])
        self._catalog = cat
        self._validate()
        self._index: dict[tuple[str, str], list[tuple[EngineRef, CanonicalRule]]] = {}
        for cr in self.canonical.values():
            for eng in ("axe", "ibm", "htmlcs"):
                for ref in getattr(cr, eng):
                    self._index.setdefault((eng, ref.id), []).append((ref, cr))

    def _validate(self) -> None:
        for s in self.standards.values():
            if s.kind == "wcag" and not (s.wcag_version and s.level):
                raise ValueError(f"{s.id}: wcag standards need wcag_version and level")
            if s.kind == "derived" and (
                s.base not in self.standards or self.standards[s.base].kind != "wcag"
            ):
                raise ValueError(f"{s.id}: base {s.base!r} must be a wcag standard")
        for cid in self.content:
            if cid not in self.canonical:
                raise ValueError(f"content for unknown canonical rule {cid}")
        for cr in self.canonical.values():
            for sc in cr.sc:
                if sc not in self.criteria:
                    raise ValueError(f"canonical rule {cr.id}: unknown criterion {sc}")
        seen: dict[tuple[str, str, tuple], str] = {}
        for cr in self.canonical.values():
            for eng in ("axe", "ibm", "htmlcs"):
                for ref in getattr(cr, eng):
                    key = (eng, ref.id, tuple(sorted(ref.tags)))
                    if key in seen:
                        raise ValueError(
                            f"{eng} rule {ref.id} is mapped to both {seen[key]} and {cr.id}"
                        )
                    seen[key] = cr.id

    # -- standards ------------------------------------------------------------------------------
    def criteria_for(self, standard_id: str) -> list[Criterion]:
        s = self.standards[standard_id]
        if s.kind == "derived":
            return self.criteria_for(s.base)  # type: ignore[arg-type]
        v, lvl = _ver(s.wcag_version), LEVELS.index(s.level)  # type: ignore[arg-type]
        out = [
            c
            for c in self.criteria.values()
            if _ver(c.since) <= v
            and LEVELS.index(c.level) <= lvl
            and not (c.removed_in and _ver(c.removed_in) <= v)
        ]
        return sorted(out, key=lambda c: _sc_key(c.id))

    def clause(self, standard_id: str, sc: str) -> str:
        fmt = self.standards[standard_id].clause_format
        return fmt.format(sc=sc.replace(".", ".")) if fmt else f"WCAG {sc}"

    # -- mapping findings -------------------------------------------------------------------------
    @staticmethod
    def element_key(tag: str | None, type_: str | None = None) -> str | None:
        """'input:button' for <input type=button>, else the tag name."""
        return f"{tag}:{type_.lower()}" if tag == "input" and type_ else tag

    def canonical_for(
        self, engine: str, rule_id: str, tag: str | None = None, type_: str | None = None
    ) -> CanonicalRule | None:
        """Canonical rule for an engine rule, resolved by the most SPECIFIC matching entry:
        an entry restricted to `input:button` beats one for `input`, which beats an unrestricted one;
        for HTML_CodeSniffer (patterns ending in `*`) a longer pattern beats a shorter one."""
        key, base = self.element_key(tag, type_), tag
        best: tuple[int, int, CanonicalRule] | None = None
        for (eng, pattern), entries in self._index.items():
            if eng != engine:
                continue
            if engine == "htmlcs":
                if not fnmatchcase(rule_id, pattern):
                    continue
                plen = len(
                    pattern.replace("*", "")
                )  # literal characters: more literal = more specific
            elif pattern == rule_id:
                plen = 0
            else:
                continue
            for ref, cr in entries:
                if not ref.tags:
                    spec = 0
                elif key in ref.tags:
                    spec = 2
                elif base in ref.tags:
                    spec = 1
                else:
                    continue
                if best is None or (spec, plen) > (best[0], best[1]):
                    best = (spec, plen, cr)
        return best[2] if best else None

    # -- summaries --------------------------------------------------------------------------------
    def summarise(self, standard_id: str, findings: list[dict]) -> Summary:
        """``findings``: dicts with ``sc`` (list), ``kind`` (violation|needs_review|best_practice).
        Switching standards just recomputes this from stored findings: no rescan needed."""
        crit = [c.id for c in self.criteria_for(standard_id)]
        in_scope = set(crit)
        failed: set[str] = set()
        review: set[str] = set()
        for f in findings:
            for sc in f.get("sc", []):
                if sc in in_scope:
                    if f["kind"] == "violation":
                        failed.add(sc)
                    elif f["kind"] == "needs_review":
                        review.add(sc)
        review -= failed
        tested = {c for c in crit if c in self.automated_sc}
        clean = sorted(tested - failed - review, key=_sc_key)
        untested = sorted((set(crit) - tested) - failed - review, key=_sc_key)
        return Summary(
            standard_id,
            len(crit),
            sorted(failed, key=_sc_key),
            sorted(review, key=_sc_key),
            clean,
            untested,
        )


@lru_cache
def get_registry() -> Registry:
    return Registry(rules_dir())
