"""Scans one page (and, bounded, a same-origin crawl) with all three engines in ONE Playwright page.

One page load, one DOM state, one browser: engines run one after another on the same document, so
results are comparable and memory is a fraction of running pa11y's own browser (PROJECT_PLAN 1.4).
Every request the browser makes (document, redirects, sub-resources) passes the SSRF guard.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urldefrag, urljoin, urlsplit

from a11y_core.rules import get_registry
from a11y_core.ssrf import BlockedTarget, check_url, dev_allow_hosts, parse_url, resolve_public
from playwright.async_api import Browser, async_playwright
from playwright.async_api import Error as PlaywrightError

from .egress import EgressProxy
from .engines import load_bundles, runner_source
from .normalise import Finding, normalise

log = logging.getLogger(__name__)
USER_AGENT = (
    "a11y-scanner/0.1 (+https://a11y.example/bot; accessibility audit requested by the site owner)"
)
VIEWPORT = {"width": 1280, "height": 800}
CHROMIUM_ARGS = [
    "--no-first-run",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--disable-background-networking",
    "--mute-audio",
]


@dataclass
class ScanOptions:
    engines: tuple[str, ...] = ("axe", "ibm", "htmlcs")
    page_timeout_s: int = 45
    settle_ms: int = 500
    respect_robots: bool = True
    politeness_delay_ms: int = 250
    screenshot: bool = False
    screenshot_quality: int = 60
    screenshot_max_height: int = 5000
    ports: tuple[int, ...] = (80, 443, 8080, 8443)


@dataclass
class PageResult:
    url: str
    final_url: str | None = None
    status: str = "OK"  # OK | FAILED | BLOCKED
    error_code: str | None = None
    error_detail: str | None = None
    http_status: int | None = None
    title: str | None = None
    lang: str | None = None
    engines: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    screenshot: bytes | None = None  # JPEG of the top of the page, page coordinates = pixels
    screenshot_meta: dict | None = None  # width, height, page_height, truncated
    blocked_requests: list[str] = field(default_factory=list)  # sub-requests the SSRF guard refused
    duration_ms: int = 0


class _Guard:
    """Per-scan view of the egress proxy. Every connection the browser makes already passes the
    proxy; this additionally aborts requests the proxy would refuse (so the page does not wait for
    them) and exposes what was blocked."""

    def __init__(self, opts: ScanOptions, proxy: EgressProxy | None = None) -> None:
        self.opts = opts
        self.proxy = proxy
        self._own_blocked: list[str] = []  # used only when there is no proxy (unit tests)

    @property
    def blocked(self) -> list[str]:
        return self.proxy.blocked if self.proxy else self._own_blocked

    async def allows(self, url: str) -> bool:
        if url.startswith(("data:", "blob:", "about:")):
            return True
        try:
            _, host, port = parse_url(url, ports=self.opts.ports)
            await resolve_public(host, port, allow_hosts=dev_allow_hosts())
            return True
        except BlockedTarget as e:
            self.blocked.append(f"{e.code}: {url[:120]}")
            return False


async def _prepare_page(browser: Browser, guard: _Guard):
    ctx = await browser.new_context(
        viewport=VIEWPORT,
        user_agent=USER_AGENT,
        java_script_enabled=True,
        accept_downloads=False,
        service_workers="block",
    )

    async def route(r):
        if await guard.allows(r.request.url):
            await r.continue_()
        else:
            await r.abort("blockedbyclient")

    await ctx.route("**/*", route)
    return ctx, await ctx.new_page()


async def _capture(page, res: PageResult, opts: ScanOptions) -> None:
    """A screenshot is a convenience: any failure here leaves the scan itself untouched."""
    try:
        full = await page.evaluate(
            "() => Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)"
        )
        h = max(1, min(int(full), opts.screenshot_max_height))
        w = VIEWPORT["width"]
        res.screenshot = await page.screenshot(
            full_page=True,
            type="jpeg",
            quality=opts.screenshot_quality,
            clip={"x": 0, "y": 0, "width": w, "height": h},
        )
        res.screenshot_meta = {
            "width": w,
            "height": h,
            "page_height": int(full),
            "truncated": int(full) > h,
        }
    except PlaywrightError as e:
        res.screenshot = res.screenshot_meta = None
        log.warning("screenshot failed url=%s: %s", res.url, str(e)[:160])


async def scan_page(
    browser: Browser, url: str, opts: ScanOptions, guard: _Guard | None = None
) -> PageResult:
    """Scan one URL. Never raises for page-level problems: they are reported on the result."""
    guard = guard or _Guard(opts)
    res = PageResult(url=url)
    blocked_from = len(guard.blocked)
    t0 = time.perf_counter()
    try:
        target = await check_url(url, ports=opts.ports)
        res.url = target.url
    except BlockedTarget as e:
        res.status, res.error_code, res.error_detail = "BLOCKED", e.code, e.message
        return res
    ctx, page = await _prepare_page(browser, guard)
    try:
        try:
            resp = await page.goto(url, wait_until="load", timeout=opts.page_timeout_s * 1000)
        except PlaywrightError as e:
            msg = str(e)
            if len(guard.blocked) > blocked_from:
                res.status, res.error_code, res.error_detail = (
                    "BLOCKED",
                    "blocked_redirect",
                    "The page redirected to an address that cannot be scanned.",
                )
            elif (
                "Download is starting" in msg
            ):  # PDFs, archives, etc. make the browser download instead of render
                res.status, res.error_code, res.error_detail = (
                    "FAILED",
                    "not_html",
                    "That address is not a web page (it is not HTML).",
                )
            elif "Timeout" in msg:
                res.status, res.error_code, res.error_detail = (
                    "FAILED",
                    "timeout",
                    "The page took too long to load.",
                )
            elif "ERR_CERT" in msg or "SSL" in msg:
                res.status, res.error_code, res.error_detail = (
                    "FAILED",
                    "tls_error",
                    "The site's security certificate is not valid.",
                )
            elif "ERR_NAME_NOT_RESOLVED" in msg or "ERR_CONNECTION" in msg:
                res.status, res.error_code, res.error_detail = (
                    "FAILED",
                    "unreachable",
                    "We could not connect to that address.",
                )
            else:
                res.status, res.error_code, res.error_detail = (
                    "FAILED",
                    "navigation_failed",
                    "The page could not be opened.",
                )
            return res
        res.http_status = resp.status if resp else None
        res.final_url = page.url
        if resp and resp.headers.get("x-a11y-blocked"):
            res.status, res.error_code = "BLOCKED", "blocked_redirect"
            res.error_detail = "The page redirected to an address that cannot be scanned."
            return res
        if res.http_status and res.http_status >= 400:
            res.status, res.error_code = "FAILED", f"http_{res.http_status}"
            res.error_detail = f"The site answered with HTTP {res.http_status}."
            return res
        ctype = (resp.headers.get("content-type", "") if resp else "").lower()
        if ctype and "html" not in ctype:
            res.status, res.error_code, res.error_detail = (
                "FAILED",
                "not_html",
                "That address is not a web page (it is not HTML).",
            )
            return res
        try:  # best effort: let late scripts settle, but never fail the scan for a busy page
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightError:
            pass
        await page.wait_for_timeout(opts.settle_ms)

        sources, versions = load_bundles()
        for eng in opts.engines:
            await page.add_script_tag(content=sources[eng])
        await page.add_script_tag(content=runner_source())
        raw = await asyncio.wait_for(
            page.evaluate("(e) => window.__a11yScan(e)", list(opts.engines)),
            timeout=opts.page_timeout_s,
        )
        res.title, res.lang, res.engines = raw.get("title"), raw.get("lang"), raw["engines"]
        ran_ok = {k for k, v in raw["engines"].items() if v.get("ok")}
        if not ran_ok:
            res.status, res.error_code, res.error_detail = (
                "FAILED",
                "engines_failed",
                "The accessibility engines could not run on this page.",
            )
            return res
        res.findings = normalise(raw["findings"], get_registry(), ran_ok=ran_ok)
        res.links = await page.evaluate(
            "() => [...document.querySelectorAll('a[href]')].map(a => a.href)"
        )
        if opts.screenshot:
            await _capture(page, res, opts)
    except (PlaywrightError, TimeoutError) as e:
        res.status, res.error_code, res.error_detail = (
            "FAILED",
            "scan_error",
            "The scan of this page did not finish.",
        )
        log.warning("scan_page error url=%s: %s", url, str(e)[:200])
    finally:
        res.duration_ms = int((time.perf_counter() - t0) * 1000)
        res.blocked_requests = list(guard.blocked[blocked_from:])
        await ctx.close()
    return res


def _same_site_links(base: str, links: list[str], origin: str) -> list[str]:
    out, seen = [], set()
    for href in links:
        u = urldefrag(urljoin(base, href))[0]
        p = urlsplit(u)
        if p.scheme not in ("http", "https") or f"{p.scheme}://{p.netloc}" != origin:
            continue
        if p.path.lower().endswith(
            (
                ".pdf",
                ".zip",
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".svg",
                ".webp",
                ".mp4",
                ".mp3",
                ".css",
                ".js",
                ".xml",
                ".docx",
                ".xlsx",
                ".pptx",
            )
        ):
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def _robots(origin: str, ports: tuple[int, ...]) -> robotparser.RobotFileParser | None:
    import httpx

    rp = robotparser.RobotFileParser()
    try:
        _, host, port = parse_url(origin + "/robots.txt", ports=ports)
        await resolve_public(host, port, allow_hosts=dev_allow_hosts())
        async with httpx.AsyncClient(
            timeout=8, follow_redirects=False, headers={"user-agent": USER_AGENT}
        ) as c:
            r = await c.get(origin + "/robots.txt")
        if r.status_code == 200:
            rp.parse(r.text.splitlines())
            return rp
    except Exception:  # noqa: BLE001 - robots.txt is advisory; absence or failure means "allowed"
        log.debug("robots.txt unavailable for %s", origin)
    return None


async def scan_site(
    start_url: str,
    *,
    max_pages: int,
    opts: ScanOptions | None = None,
    on_page=None,
    skip: set[str] | None = None,
) -> list[PageResult]:
    """Scan ``start_url``, and if ``max_pages`` > 1 crawl same-origin links breadth-first.

    ``on_page(result)`` is awaited after each page (persist + heartbeat there). ``skip``: URLs
    already scanned (resume). robots.txt is honoured (disallowed pages are recorded, not fetched)."""
    opts = opts or ScanOptions()
    origin = f"{urlsplit(start_url).scheme}://{urlsplit(start_url).netloc}"
    robots = await _robots(origin, opts.ports) if (opts.respect_robots and max_pages > 1) else None
    queue: deque[str] = deque([urldefrag(start_url)[0]])
    seen: set[str] = set(queue) | (skip or set())
    results: list[PageResult] = []
    async with async_playwright() as p:
        proxy = EgressProxy(ports=opts.ports, allow_hosts=dev_allow_hosts())
        proxy_port = await proxy.start()
        # <-loopback>: Chromium normally bypasses proxies for localhost; the filter must see everything.
        browser = await p.chromium.launch(
            args=[*CHROMIUM_ARGS, "--proxy-bypass-list=<-loopback>"],
            chromium_sandbox=False,
            proxy={"server": f"http://127.0.0.1:{proxy_port}"},
        )
        guard = _Guard(opts, proxy)
        try:
            while (
                queue
                and len([r for r in results if r.status != "BLOCKED" or r.error_code != "robots"])
                < max_pages
            ):
                url = queue.popleft()
                if url in (skip or set()):
                    continue
                if robots and not robots.can_fetch(USER_AGENT, url) and url != start_url:
                    r = PageResult(
                        url=url,
                        status="BLOCKED",
                        error_code="robots",
                        error_detail="Skipped: the site's robots.txt asks scanners not to visit this page.",
                    )
                else:
                    r = await scan_page(browser, url, opts, guard)
                    if (
                        r.status == "FAILED" and r.error_code == "scan_error"
                    ):  # one retry in a fresh context: browser hiccups happen
                        r = await scan_page(browser, url, opts, guard)
                results.append(r)
                if on_page:
                    await on_page(r)
                if r.status == "OK" and len(seen) < max_pages * 20:
                    for link in _same_site_links(r.final_url or url, r.links, origin):
                        if link not in seen:
                            seen.add(link)
                            queue.append(link)
                if queue:
                    await asyncio.sleep(opts.politeness_delay_ms / 1000)
        finally:
            await browser.close()
            await proxy.stop()
    return results
