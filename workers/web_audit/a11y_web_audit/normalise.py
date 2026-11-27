"""Raw per-engine findings -> one finding per (canonical rule, element), with a confidence score.

* Same defect found by several engines is merged (matched by canonical rule + shared element xpath).
* Page-level rules (scope: document) are keyed on the document, whichever element an engine blames.
* Kind: a violation from ANY engine makes it a violation; otherwise needs_review; best practices are
  kept apart and never count as non-conformance.
* Confidence compares how many engines AGREE with how many are able to detect the rule at all:
    high    two or more engines report it
    medium  one engine reports it and it is the only engine that covers this rule
    low     one engine reports it although other engines cover the rule and did NOT report it
    review  needs human judgement (not a confirmed failure)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from a11y_core.rules import Registry

SEVERITY_ORDER = {"minor": 0, "moderate": 1, "serious": 2, "critical": 3}
ENGINE_PREFERENCE = ("axe", "ibm", "htmlcs")  # whose message/element wins
_NTH = re.compile(r":nth-of-type\(\d+\)")
DOC_XPATH = "/html[1]"


@dataclass
class Finding:
    canonical_rule_id: str
    title: str
    sc: list[str]
    kind: str  # violation | needs_review | best_practice
    severity: str
    confidence: str  # high | medium | low | review
    engines: list[str]  # engines that reported it
    covering: list[str]  # engines (that ran) able to detect it
    engine_rule_ids: dict[str, list[str]]
    xpath: str
    css: str
    tag: str
    html: str
    message: str
    rect: dict | None
    cluster_key: str
    fingerprint: str
    help_url: str | None = None
    mapped: bool = True
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _merge_kind(kinds: set[str], best_practice: bool) -> str:
    if best_practice:
        return "best_practice"
    if "violation" in kinds:
        return "violation"
    return "needs_review" if "needs_review" in kinds else "best_practice"


def normalise(raw: list[dict], reg: Registry, *, ran_ok: set[str]) -> list[Finding]:
    groups: dict[tuple[str, str], list[tuple[dict, object]]] = {}
    for f in raw:
        el = f["element"]
        cr = reg.canonical_for(f["engine"], f["rule_id"], el.get("tag"))
        cid = cr.id if cr else f"{f['engine']}:{f['rule_id']}"
        xpath = DOC_XPATH if (cr and cr.scope == "document") else el["xpath"]
        groups.setdefault((cid, xpath), []).append((f, cr))

    out: list[Finding] = []
    for (cid, xpath), members in groups.items():
        cr = members[0][1]
        members.sort(key=lambda m: ENGINE_PREFERENCE.index(m[0]["engine"]))
        primary = members[0][0]
        engines = sorted({m[0]["engine"] for m in members}, key=ENGINE_PREFERENCE.index)
        kinds = {m[0]["kind"] for m in members}
        best = bool(cr and cr.best_practice) or all(
            m[0].get("best_practice") or m[0]["kind"] == "best_practice" for m in members
        )
        kind = _merge_kind(kinds, best)
        severity = max(
            (m[0].get("impact") or "moderate" for m in members),
            key=lambda s: SEVERITY_ORDER.get(s, 1),
        )
        if kind == "best_practice":
            severity = "minor" if severity not in ("moderate", "minor") else severity
        covering = (
            sorted(
                (cr.engines_covering() if cr else {primary["engine"]}) & ran_ok,
                key=ENGINE_PREFERENCE.index,
            )
            or engines
        )
        if kind == "needs_review":
            confidence = "review"
        elif len(engines) >= 2:
            confidence = "high"
        else:
            confidence = "medium" if len(covering) <= 1 else "low"
        sc = list(cr.sc) if cr else sorted({s for m in members for s in m[0].get("sc", [])})
        ids: dict[str, list[str]] = {}
        for m, _ in members:
            ids.setdefault(m["engine"], [])
            if m["rule_id"] not in ids[m["engine"]]:
                ids[m["engine"]].append(m["rule_id"])
        el = (
            primary["element"]
            if not (cr and cr.scope == "document")
            else {**primary["element"], "xpath": DOC_XPATH}
        )
        out.append(
            Finding(
                canonical_rule_id=cid,
                title=cr.title if cr else (primary.get("help") or primary["rule_id"]),
                sc=sc,
                kind=kind,
                severity=severity,
                confidence=confidence,
                engines=engines,
                covering=covering,
                engine_rule_ids=ids,
                xpath=xpath,
                css=el["css"],
                tag=el["tag"],
                html=el["html"],
                message=primary.get("message") or "",
                rect=el.get("rect"),
                # Same defect in the same kind of place across pages shares a cluster, so 500 product
                # pages with the same broken template group into ONE root cause.
                cluster_key=hashlib.sha256(f"{cid}|{_NTH.sub('', el['css'])}".encode()).hexdigest()[
                    :16
                ],
                fingerprint=hashlib.sha256(f"{cid}|{xpath}".encode()).hexdigest()[:16],
                help_url=primary.get("help_url"),
                mapped=cr is not None,
            )
        )
    out.sort(key=lambda x: (-SEVERITY_ORDER.get(x.severity, 1), x.canonical_rule_id, x.xpath))
    return out
