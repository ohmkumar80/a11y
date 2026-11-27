"""Re-scan oracle: run a snippet of HTML through the same three engines and normaliser a real scan uses.

This is how a proposed fix is judged (PROJECT_PLAN 3.13, V1): the rule must be gone AND nothing new may
appear. It never trusts an AI model's opinion that a fix works. The snippet is loaded as an inert page from
``set_content``; it never reaches the network.
"""

from __future__ import annotations

import re

from a11y_core.rules import get_registry
from playwright.async_api import Browser

from .engines import ENGINE_IDS, load_bundles, runner_source
from .normalise import Finding, normalise

_HEAD = "<head><title>Example page</title></head>"
_BODY = "<body><main><h1>Example</h1>{}</main></body>"


def wrap(snippet: str) -> str:
    """Place a fragment where it belongs in a valid page, so only the thing being tested can fail.
    Whole documents, ``<html>``/``<head>``/``<body>`` snippets, and head-only snippets are respected."""
    s = snippet.strip()
    low = s.lower()
    if low.startswith("<!doctype"):
        return s
    if low.startswith("<html"):
        return f"<!doctype html>{s}{_HEAD}{_BODY.format('<p>Text</p>')}</html>"
    if low.startswith("<head"):
        return f'<!doctype html><html lang="en">{s}{_BODY.format("<p>Text</p>")}</html>'
    if low.startswith("<body"):
        return f'<!doctype html><html lang="en">{_HEAD}{s}</html>'
    if re.match(r"<(meta|style|link|title)\b", low):
        return f'<!doctype html><html lang="en"><head><title>Example page</title>{s}</head>{_BODY.format("<p>Text</p>")}</html>'
    return f'<!doctype html><html lang="en">{_HEAD}{_BODY.format(s)}</html>'


async def scan_snippet(browser: Browser, snippet: str) -> list[Finding]:
    sources, _ = load_bundles()
    ctx = await browser.new_context(
        viewport={"width": 1280, "height": 800}, java_script_enabled=True
    )
    try:
        page = await ctx.new_page()
        await page.route(
            "**/*",
            lambda r: (
                r.abort() if not r.request.url.startswith(("data:", "about:")) else r.continue_()
            ),
        )
        await page.set_content(wrap(snippet))
        for eng in ENGINE_IDS:
            await page.add_script_tag(content=sources[eng])
        await page.add_script_tag(content=runner_source())
        raw = await page.evaluate("() => window.__a11yScan()")
        ran_ok = {k for k, v in raw["engines"].items() if v.get("ok")}
        return normalise(raw["findings"], get_registry(), ran_ok=ran_ok)
    finally:
        await ctx.close()


def found(findings: list[Finding], rule: str) -> list[Finding]:
    """Findings of this rule that count as a failure or a flag for review (best practices do not)."""
    return [f for f in findings if f.canonical_rule_id == rule and f.kind != "best_practice"] or [
        f
        for f in findings
        if f.canonical_rule_id == rule and get_registry().canonical[rule].best_practice
    ]
