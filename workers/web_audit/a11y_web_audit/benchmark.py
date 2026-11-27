"""Scanner benchmark: recall and false positives against fixtures with embedded ground truth.

Ground truth lives in the fixture HTML (fixtures/benchmark/cases/*.html):
  data-bench-expect="<canonical rule id>[,<rule>...]"  a PLANTED defect on this element (or, for
                                                       page-level rules, on the page)
  data-bench-expect="none"                             a KNOWN-GOOD element: any failure on it or inside
                                                       it is a false positive

Reported, for the three engines merged and for each engine alone: how many planted defects were found
(recall), how many failures were raised on known-good elements (false positives), and failures nobody
planted ("unexpected": usually a fixture mistake or a real extra defect, so each one is reviewed).
CI compares the result with fixtures/benchmark/baseline.json (PROJECT_PLAN 3.2, Phase 1 exit criteria).

Run:  python -m a11y_web_audit.benchmark [--write-baseline] [--markdown docs/benchmark.md]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from a11y_core.rules import get_registry
from playwright.async_api import async_playwright

from .engines import ENGINE_IDS, load_bundles, runner_source
from .normalise import normalise

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "fixtures/benchmark/cases"
BASELINE = ROOT / "fixtures/benchmark/baseline.json"
GOVUK = ROOT / "fixtures/benchmark/govuk"
GOVUK_REVIEW = ROOT / "fixtures/benchmark/govuk-review.json"
TRUTH_JS = """() => [...document.querySelectorAll('[data-bench-expect]')].map(e =>
  ({ expect: e.getAttribute('data-bench-expect'), xpath: window.__a11yIdentity(e).xpath })).concat(
  [...document.querySelectorAll('[data-bench-review]')].map(e =>
  ({ review: e.getAttribute('data-bench-review'), xpath: window.__a11yIdentity(e).xpath })))"""
DETECTED_KINDS = ("violation", "best_practice")


def _inside(xpath: str, ancestor: str) -> bool:
    return xpath == ancestor or xpath.startswith(ancestor + "/")


def _hit(finding: dict, rule: str, xpath: str, doc_scope: bool) -> bool:
    return finding["rule"] == rule and (doc_scope or _inside(finding["xpath"], xpath))


async def run_benchmark(cases_dir: Path = CASES) -> dict:
    reg = get_registry()
    sources, versions = load_bundles()
    expected: list[dict] = []
    clean: list[dict] = []
    reviews: list[
        dict
    ] = []  # cannot be decided by a machine: the right outcome is 'flagged for human review'
    findings: dict[str, list[dict]] = {k: [] for k in ("merged", *ENGINE_IDS)}
    case_names = sorted(p.stem for p in cases_dir.glob("*.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch(chromium_sandbox=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        for name in case_names:
            page = await ctx.new_page()
            await page.goto((cases_dir / f"{name}.html").as_uri())
            for eng in ENGINE_IDS:
                await page.add_script_tag(content=sources[eng])
            await page.add_script_tag(content=runner_source())
            truth = await page.evaluate(TRUTH_JS)
            raw = await page.evaluate("() => window.__a11yScan()")
            ran_ok = {k for k, v in raw["engines"].items() if v.get("ok")}
            for t in truth:
                if t.get("review"):
                    reviews.append({"case": name, "rule": t["review"], "xpath": t["xpath"]})
                    continue
                if t["expect"] == "none":
                    clean.append({"case": name, "xpath": t["xpath"]})
                    continue
                for rule in (r.strip() for r in t["expect"].split(",")):
                    cr = reg.canonical.get(rule)
                    if cr is None:
                        raise ValueError(
                            f"{name}: unknown canonical rule {rule!r} in data-bench-expect"
                        )
                    expected.append(
                        {
                            "case": name,
                            "rule": rule,
                            "xpath": t["xpath"],
                            "doc": cr.scope == "document",
                        }
                    )
            for f in normalise(raw["findings"], reg, ran_ok=ran_ok):
                findings["merged"].append(
                    {
                        "case": name,
                        "rule": f.canonical_rule_id,
                        "xpath": f.xpath,
                        "kind": f.kind,
                        "confidence": f.confidence,
                        "engines": f.engines,
                    }
                )
            for f in raw["findings"]:
                cr = reg.canonical_for(
                    f["engine"], f["rule_id"], f["element"]["tag"], f["element"].get("type")
                )
                findings[f["engine"]].append(
                    {
                        "case": name,
                        "rule": cr.id if cr else f"{f['engine']}:{f['rule_id']}",
                        "xpath": f["element"]["xpath"],
                        "kind": f["kind"],
                    }
                )
            await page.close()
        await browser.close()

    def detected(exp: dict, fs: list[dict], kinds=DETECTED_KINDS, conf: str | None = None) -> bool:
        return any(
            f["case"] == exp["case"]
            and f["kind"] in kinds
            and (conf is None or f.get("confidence") == conf)
            and _hit(f, exp["rule"], exp["xpath"], exp["doc"])
            for f in fs
        )

    by_rule: dict[str, dict] = {}
    totals = {k: 0 for k in ("merged", "high_confidence", "needs_review_only", *ENGINE_IDS)}
    missed = []
    for e in expected:
        r = by_rule.setdefault(
            e["rule"], {"expected": 0, **{k: 0 for k in ("merged", *ENGINE_IDS)}}
        )
        r["expected"] += 1
        for k in ("merged", *ENGINE_IDS):
            if detected(e, findings[k]):
                r[k] += 1
                totals[k] += 1
        if detected(e, findings["merged"], conf="high"):
            totals["high_confidence"] += 1
        if not detected(e, findings["merged"]):
            if detected(e, findings["merged"], kinds=("needs_review",)):
                totals["needs_review_only"] += 1
            missed.append({"case": e["case"], "rule": e["rule"], "xpath": e["xpath"]})

    def in_clean(f: dict) -> bool:
        return any(f["case"] == c["case"] and _inside(f["xpath"], c["xpath"]) for c in clean)

    fp = {
        k: [f for f in findings[k] if f["kind"] == "violation" and in_clean(f)]
        for k in ("merged", *ENGINE_IDS)
    }
    judged_true = [
        f
        for f in findings["merged"]
        if f["kind"] in DETECTED_KINDS
        and any(
            f["case"] == e["case"] and _hit(f, e["rule"], e["xpath"], e["doc"]) for e in expected
        )
    ]
    unexpected = [
        f
        for f in findings["merged"]
        if f["kind"] == "violation" and not in_clean(f) and f not in judged_true
    ]
    review_flagged = [
        r
        for r in reviews
        if any(
            f["case"] == r["case"]
            and _hit(f, r["rule"], r["xpath"], reg.canonical[r["rule"]].scope == "document")
            for f in findings["merged"]
        )
    ]
    n = len(expected) or 1
    tp = len([f for f in judged_true if f["kind"] == "violation"])
    return {
        "engine_versions": versions,
        "rules_version": reg.standards_version,
        "cases": len(case_names),
        "expected_defects": len(expected),
        "clean_elements": len(clean),
        "recall": {k: round(totals[k] / n, 4) for k in ("merged", "high_confidence", *ENGINE_IDS)},
        "found": {k: totals[k] for k in ("merged", "high_confidence", *ENGINE_IDS)},
        "needs_review_only": totals["needs_review_only"],
        "review_expected": len(reviews),
        "review_flagged": len(review_flagged),
        "false_positives_on_clean": {k: len(v) for k, v in fp.items()},
        "false_positive_detail": fp["merged"],
        "unexpected_failures": {"count": len(unexpected), "items": unexpected},
        "strict_precision": round(tp / (tp + len(fp["merged"]) + len(unexpected)), 4)
        if tp
        else 0.0,
        "by_rule": dict(sorted(by_rule.items())),
        "missed": missed,
    }


# In the suite's tests.json a tool "found" a failure when its result is one of these; "warning" and "manual"
# are partial and "notfound" is a miss.
HISTORIC_HIT = ("error", "error_paid", "identified")
CONTROL_HTML = '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Control page</title></head><body><h1>Control</h1><main></main></body></html>'
_norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731


def _govuk_historic() -> dict[str, dict]:
    """Test name -> historical results of other tools, from the suite's own tests.json."""
    data = json.loads((GOVUK / "tests.json").read_text()) if (GOVUK / "tests.json").exists() else {}
    out = {}
    for cat, items in data.items():
        for name, d in items.items():
            out[_norm(cat + name)] = d["results"]
    return out


async def run_govuk() -> dict:
    """Independent ground truth: every GOV.UK test page demonstrates ONE failure that should be reported.

    A page counts as DETECTED when the engines raise a failure other than what a control page (same
    template, empty <main>) already raises; REVIEW when they only flag it for human review; MISSED
    otherwise. 'Detected' means "a real failure was reported on the page", not that it was the planted
    one, so this is an upper bound that is spot-checked by hand (see `sample`)."""
    reg = get_registry()
    sources, versions = load_bundles()
    historic = _govuk_historic()
    pages = sorted((GOVUK / "tests").glob("*.html"))
    rows = []

    async def scan(page, kind: str):
        for eng in ENGINE_IDS:
            await page.add_script_tag(content=sources[eng])
        await page.add_script_tag(content=runner_source())
        raw = await page.evaluate("() => window.__a11yScan()")
        ran_ok = {k for k, v in raw["engines"].items() if v.get("ok")}
        merged = normalise(raw["findings"], reg, ran_ok=ran_ok)
        per = {e: set() for e in ENGINE_IDS}
        per_rev = {e: set() for e in ENGINE_IDS}
        for f in raw["findings"]:
            cr = reg.canonical_for(
                f["engine"], f["rule_id"], f["element"]["tag"], f["element"].get("type")
            )
            key = cr.id if cr else f"{f['engine']}:{f['rule_id']}"
            if f["kind"] in ("violation", "best_practice"):
                per[f["engine"]].add(key)
            elif f["kind"] == "needs_review":
                per_rev[f["engine"]].add(key)
        return (
            {f.canonical_rule_id for f in merged if f.kind in ("violation", "best_practice")},
            {f.canonical_rule_id for f in merged if f.kind == "violation"},
            {f.canonical_rule_id for f in merged if f.kind == "needs_review"},
            per,
            per_rev,
        )

    async with async_playwright() as p:
        browser = await p.chromium.launch(chromium_sandbox=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()
        await page.set_content(CONTROL_HTML)
        c_v, c_hard, c_r, c_per, c_rev = await scan(page, "control")
        await page.close()
        for f in pages:
            # 12 tests are wrappers: the failure lives on a linked example page, which is what must be scanned.
            m = re.search(r'href="\.\./example-pages/([^"#?]+)"', f.read_text())
            target = (GOVUK / "example-pages" / m.group(1)) if m else f
            page = await ctx.new_page()
            await page.goto(target.as_uri())
            await page.wait_for_timeout(100)
            v, hard, rv, per, per_rev = await scan(page, "test")
            v, hard, rv = v - c_v, hard - c_hard, rv - c_r - v
            ours = {e: bool(per[e] - c_per[e]) for e in ENGINE_IDS}
            ours_rev = {e: bool(per_rev[e] - c_rev[e]) or ours[e] for e in ENGINE_IDS}
            h = historic.get(_norm(f.stem), {})
            rows.append(
                {
                    "test": f.stem,
                    "detected": bool(v),
                    "hard": bool(hard),
                    "review": (not v) and bool(rv),
                    "rules": sorted(v),
                    "engine": ours,
                    "engine_review": ours_rev,
                    "historic_identified": sorted(t for t, r in h.items() if r in HISTORIC_HIT),
                }
            )
            await page.close()
        await browser.close()

    coincidental = (
        tuple(json.loads(GOVUK_REVIEW.read_text())["coincidental_prefixes"])
        if GOVUK_REVIEW.exists()
        else ()
    )
    for r in rows:
        r["confirmed"] = r["detected"] and not r["test"].startswith(coincidental)
    n = len(rows)
    auto = [r for r in rows if r["historic_identified"]]
    pct = lambda a, b: round(a / b, 4) if b else 0.0  # noqa: E731
    hist_tools = {}
    for r in rows:
        for t in r["historic_identified"]:
            hist_tools[t] = hist_tools.get(t, 0) + 1
    return {
        "engine_versions": versions,
        "pages": n,
        "control_rules": sorted(c_v),
        "detected": sum(r["detected"] for r in rows),
        "detected_hard_failures": sum(r["hard"] for r in rows),
        "confirmed": sum(r["confirmed"] for r in rows),
        "confirmed_recall": pct(sum(r["confirmed"] for r in rows), n),
        "coincidental": sum(r["detected"] and not r["confirmed"] for r in rows),
        "automatable_confirmed": sum(r["confirmed"] for r in auto),
        "automatable_confirmed_recall": pct(sum(r["confirmed"] for r in auto), len(auto)),
        "review_only": sum(r["review"] for r in rows),
        "missed": [r["test"] for r in rows if not r["detected"]],
        "recall": pct(sum(r["detected"] for r in rows), n),
        "by_engine": {e: sum(r["engine"][e] for r in rows) for e in ENGINE_IDS},
        "automatable_pages": len(auto),
        "automatable_detected": sum(r["detected"] for r in auto),
        "automatable_recall": pct(sum(r["detected"] for r in auto), len(auto)),
        "automatable_missed": [r["test"] for r in auto if not r["detected"]],
        "never_identified_by_any_tool": n - len(auto),
        "historic_tools_identified": dict(sorted(hist_tools.items(), key=lambda kv: -kv[1])),
        "detections": [{"test": r["test"], "rules": r["rules"]} for r in rows if r["detected"]],
    }


def to_markdown(r: dict, g: dict | None = None) -> str:
    pct = lambda x: f"{x * 100:.0f}%"  # noqa: E731
    v = ", ".join(f"{k} {x}" for k, x in r["engine_versions"].items())
    out = [
        "# Scanner benchmark",
        "",
        f"Engines: {v}. Rules {r['rules_version']}. {r['cases']} fixture pages, {r['expected_defects']} planted defects, "
        f"{r['clean_elements']} known-good elements. Ground truth is embedded in `fixtures/benchmark/cases`.",
        "",
        "| | Planted defects found | Recall | False failures on known-good elements |",
        "|---|---|---|---|",
    ]
    for k, label in (
        ("merged", "**All three engines merged**"),
        ("high_confidence", "Merged, high confidence only"),
        ("axe", "axe-core alone"),
        ("ibm", "IBM Equal Access alone"),
        ("htmlcs", "HTML_CodeSniffer alone"),
    ):
        fpv = r["false_positives_on_clean"].get(k, "n/a" if k == "high_confidence" else "")
        out.append(
            f"| {label} | {r['found'][k]} of {r['expected_defects']} | {pct(r['recall'][k])} | {fpv} |"
        )
    out += [
        "",
        f"Strict precision (planted defects found / those + false failures + unexpected failures): **{pct(r['strict_precision'])}**. "
        f"Unexpected failures (nobody planted them; each is reviewed): {r['unexpected_failures']['count']}. "
        f"Defects the merged result only flagged as 'needs review': {r['needs_review_only']}. "
        f"Items no machine can decide (should be flagged for human review): {r['review_flagged']} of {r['review_expected']} flagged.",
        "",
        "## By rule",
        "",
        "| Rule | Planted | Merged | axe | IBM | HTMLCS |",
        "|---|---|---|---|---|---|",
    ]
    for rule, x in r["by_rule"].items():
        out.append(
            f"| {rule} | {x['expected']} | {x['merged']} | {x['axe']} | {x['ibm']} | {x['htmlcs']} |"
        )
    if r["missed"]:
        out += ["", "## Missed by every engine", ""] + [
            f"- `{m['rule']}` in {m['case']} at `{m['xpath']}`" for m in r["missed"]
        ]
    if g:
        out += [
            "",
            "## Independent check: GOV.UK accessibility-tool-audit",
            "",
            f"{g['pages']} test pages, each demonstrating ONE failure (MIT licence, by the UK Government Digital Service; we did not write or tune them). "
            f"A page is a candidate detection when the engines report a failure or best-practice issue beyond what an empty control page already reports "
            f"(control: {', '.join(g['control_rules']) or 'none'}). Every candidate was then compared by hand with the test's description.",
            "",
            "| | Pages |",
            "|---|---|",
            f"| **Detected, and related to the planted failure** (three engines merged) | **{g['confirmed']} of {g['pages']} ({pct(g['confirmed_recall'])})** |",
            f"| Something was reported, but unrelated to the planted failure (not counted) | {g['coincidental']} |",
            f"| Nothing reported | {len(g['missed'])} |",
            f"| Candidates by engine alone: axe-core / IBM / HTML_CodeSniffer (not hand-reviewed) | {g['by_engine']['axe']} / {g['by_engine']['ibm']} / {g['by_engine']['htmlcs']} |",
            "",
            f"The suite's own 2017 to 2019 results show that {g['never_identified_by_any_tool']} of these {g['pages']} failures were not reported as a failure by ANY of the 13 tools it tested "
            f"(for example plain language or consistent navigation: no automation can judge them). On the {g['automatable_pages']} failures that at least one of those tools reported, "
            f"we confirm **{g['automatable_confirmed']} ({pct(g['automatable_confirmed_recall'])})**.",
            "",
            "The hand review (`fixtures/benchmark/govuk-review.json`) was done by an AI assistant comparing each reported rule with the test's description. "
            "An accessibility specialist should re-check it before these numbers are quoted outside the team.",
        ]
        if g["automatable_missed"]:
            out += ["", "### Reported by another tool in 2017 to 2019 but not by us now", ""] + [
                f"- {t}" for t in g["automatable_missed"]
            ]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--markdown")
    a = ap.parse_args()
    res = asyncio.run(run_benchmark())
    gov = asyncio.run(run_govuk())
    print(to_markdown(res, gov))
    if res["false_positive_detail"] or res["unexpected_failures"]["items"]:
        print(
            "False failures on known-good elements:",
            json.dumps(res["false_positive_detail"], indent=1),
        )
        print("Unexpected failures:", json.dumps(res["unexpected_failures"]["items"], indent=1))
    if a.write_baseline:
        BASELINE.write_text(
            json.dumps(
                {
                    k: res[k]
                    for k in (
                        "engine_versions",
                        "rules_version",
                        "cases",
                        "expected_defects",
                        "clean_elements",
                        "review_expected",
                        "review_flagged",
                        "recall",
                        "false_positives_on_clean",
                        "strict_precision",
                    )
                }
                | {"unexpected_failures": res["unexpected_failures"]["count"]}
                | {
                    "govuk": {
                        k: gov[k]
                        for k in (
                            "pages",
                            "confirmed",
                            "confirmed_recall",
                            "coincidental",
                            "automatable_pages",
                            "automatable_confirmed",
                            "automatable_confirmed_recall",
                        )
                    }
                },
                indent=1,
            )
            + "\n"
        )
    if a.markdown:
        Path(a.markdown).write_text(to_markdown(res, gov))


if __name__ == "__main__":
    main()
