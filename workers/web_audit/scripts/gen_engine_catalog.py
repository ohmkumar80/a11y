"""Writes rules/engine-catalog.json: every rule id of the pinned axe-core and IBM engines with the WCAG
criteria it maps to, plus the criteria HTML_CodeSniffer has sniffs for. Tests use it to prove that
rules/canonical.yaml only references rules that really exist in the pinned engine versions, so an
engine upgrade that renames or removes a rule fails CI instead of silently losing findings.

Run:  .venv/bin/python workers/web_audit/scripts/gen_engine_catalog.py
"""

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "packages/engine-bundles/dist"
HTMLCS_SNIFFS = next(
    (ROOT / "node_modules/.pnpm").glob(
        "html_codesniffer@*/node_modules/html_codesniffer/Standards/WCAG2AAA/Sniffs"
    )
)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("about:blank")
        await page.add_script_tag(content=(DIST / "axe.js").read_text())
        await page.add_script_tag(content=(DIST / "ace.js").read_text())
        axe = await page.evaluate(
            "() => Object.fromEntries(axe.getRules().map(r => [r.ruleId, r.tags.filter(t => /^wcag\\d{3,}$/.test(t)).map(t => `${t[4]}.${t[5]}.${t.slice(6)}`)]))"
        )
        ibm = await page.evaluate(
            """() => { const e = new ace.Checker().engine; return Object.fromEntries(e.getRulesIds().map(id => {
                 const r = e.getRule(id); const nums = [];
                 (r.rulesets || []).filter(s => [].concat(s.id).includes('IBM_Accessibility')).forEach(s => nums.push(...[].concat(s.num)));
                 const lv = (r.rulesets || []).filter(s => [].concat(s.id).includes('IBM_Accessibility')).map(s => s.level)[0] || null;
                 return [id, {sc: [...new Set(nums.filter(n => /^\\d\\.\\d\\.\\d+$/.test(n)))], level: lv}]; })); }"""
        )
        await browser.close()
    htmlcs_sc = sorted(
        {
            ".".join(f.stem.split("_"))
            for f in HTMLCS_SNIFFS.rglob("*.js")
            if re.fullmatch(r"\d_\d_\d+", f.stem)
        }
    )
    versions = json.loads((DIST / "versions.json").read_text())
    # "Automated coverage" counts only criteria where an engine can produce a DEFINITE failure:
    # axe rules and IBM VIOLATION-level rules. HTML_CodeSniffer sniffs are mostly manual-review
    # warnings, so they do not count (counting them would overstate what automation tests).
    covered = sorted(
        {s for v in axe.values() for s in v}
        | {s for v in ibm.values() if v["level"] == "VIOLATION" for s in v["sc"]},
        key=lambda s: [int(x) for x in s.split(".")],
    )
    out = {
        "engine_versions": {k: v["version"] for k, v in versions.items()},
        "axe": dict(sorted(axe.items())),
        "ibm": dict(sorted(ibm.items())),
        "htmlcs_sc": htmlcs_sc,
        "automated_sc_coverage": covered,
    }
    (ROOT / "rules/engine-catalog.json").write_text(json.dumps(out, indent=1) + "\n")
    print(
        len(axe),
        "axe rules,",
        len(ibm),
        "IBM rules,",
        len(covered),
        "criteria with at least one automated check",
    )


asyncio.run(main())
