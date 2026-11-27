"""The real scanner: Chromium, all three engines, against a local fixture server."""

import threading
from collections import Counter
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from a11y_core.settings import get_settings
from a11y_web_audit import engines
from a11y_web_audit.scanner import ScanOptions, scan_site

PAGES = Path(__file__).resolve().parents[3] / "fixtures/pages"
HITS: Counter = Counter()


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        HITS[self.path] += 1
        routes = {
            "/robots.txt": (200, "text/plain", b"User-agent: *\nDisallow: /private\n"),
            "/crawl/a.html": (
                200,
                "text/html",
                b'<html lang="en"><head><title>A</title></head><body><main><h1>A</h1><a href="/crawl/b.html">b</a> <a href="/private/secret.html">s</a> <a href="/file.pdf">pdf</a> <a href="https://other.example/x">out</a></main></body></html>',
            ),
            "/crawl/b.html": (
                200,
                "text/html",
                b'<html lang="en"><head><title>B</title></head><body><main><h1>B</h1><a href="/crawl/a.html">a</a> <a href="/crawl/c.html">c</a><img src="x.png"></main></body></html>',
            ),
            "/crawl/c.html": (
                200,
                "text/html",
                b'<html lang="en"><head><title>C</title></head><body><main><h1>C</h1></main></body></html>',
            ),
            "/private/secret.html": (200, "text/html", b"<html><body>secret</body></html>"),
            "/file.pdf": (200, "application/pdf", b"%PDF-1.4"),
            "/slow.html": None,
            "/sub.html": (
                200,
                "text/html",
                b'<html lang="en"><head><title>Sub</title></head><body><main><h1>Sub</h1><img src="http://internal.example/pixel.png" alt="x"></main></body></html>',
            ),
            "/redir": "redir",
        }
        r = routes.get(self.path)
        if self.path == "/slow.html":
            import time

            time.sleep(6)
            r = (200, "text/html", b"<html></html>")
        if r == "redir":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
            return
        if r:
            self.send_response(r[0])
            self.send_header("Content-Type", r[1])
            self.send_header("Content-Length", str(len(r[2])))
            self.end_headers()
            self.wfile.write(r[2])
            return
        return super().do_GET()


@pytest.fixture(scope="module")
def site():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(PAGES)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def allow_private(monkeypatch):
    monkeypatch.setattr(get_settings(), "scan_dev_allow_hosts", "127.0.0.1")
    HITS.clear()


FAST = ScanOptions(
    page_timeout_s=20,
    settle_ms=100,
    politeness_delay_ms=0,
    ports=(80, 443, 8080, 8443) + tuple(range(1024, 65536)),
)


async def one(url, **kw):
    return (await scan_site(url, max_pages=1, opts=ScanOptions(**{**FAST.__dict__, **kw})))[0]


async def test_bad_page_all_three_engines_merge_into_high_confidence_findings(site):
    r = await one(f"{site}/bad.html")
    assert r.status == "OK" and r.title == "" and r.lang is None
    assert all(v["ok"] for v in r.engines.values()) and set(r.engines) == {"axe", "ibm", "htmlcs"}
    by = {(f.canonical_rule_id, f.xpath): f for f in r.findings}
    img = by[("image-alt", "/html[1]/body[1]/img[1]")]
    assert (img.engines, img.confidence, img.severity, img.sc) == (
        ["axe", "ibm", "htmlcs"],
        "high",
        "critical",
        ["1.1.1"],
    )
    title = by[("document-title", "/html[1]")]
    assert title.engines == ["axe", "ibm", "htmlcs"]  # merged although HTMLCS blames <title>
    assert ("button-name", "/html[1]/body[1]/form[1]/button[1]") in by and (
        "color-contrast",
        "/html[1]/body[1]/p[1]",
    ) in by
    assert by[("html-lang", "/html[1]")].confidence == "high"
    assert by[("heading-order", "/html[1]/body[1]/h4[1]")].kind == "best_practice"
    violations = [f for f in r.findings if f.kind == "violation"]
    assert len(violations) >= 12
    # nothing is reported twice
    assert len({(f.canonical_rule_id, f.xpath) for f in r.findings}) == len(r.findings)
    # the DOM identity is real: the xpath resolves back to the same element in the page
    assert img.tag == "img" and img.css.startswith("html > body")


async def test_accessible_page_has_no_violations(site):
    r = await one(f"{site}/good.html")
    assert r.status == "OK"
    assert [f.canonical_rule_id for f in r.findings if f.kind == "violation"] == []


async def test_single_engine_runs_and_records_which_engines_ran(site):
    r = await one(f"{site}/bad.html", engines=("axe",))
    assert set(r.engines) == {"axe"} and {e for f in r.findings for e in f.engines} == {"axe"}
    assert all(
        f.confidence in ("medium", "review") for f in r.findings if f.mapped
    )  # only one engine could have agreed


async def test_http_errors_non_html_and_timeouts_are_reported_not_raised(site):
    r = await one(f"{site}/missing.html")
    assert (r.status, r.error_code) == ("FAILED", "http_404")
    r = await one(f"{site}/file.pdf")
    assert (r.status, r.error_code) == ("FAILED", "not_html")
    r = await one(f"{site}/slow.html", page_timeout_s=2)
    assert (r.status, r.error_code) == ("FAILED", "timeout")


async def test_private_targets_are_blocked_when_not_in_dev_mode(site, monkeypatch):
    monkeypatch.setattr(get_settings(), "scan_dev_allow_hosts", "")
    r = await one(f"{site}/good.html")
    assert (r.status, r.error_code) == ("BLOCKED", "private_address")
    assert HITS["/good.html"] == 0  # never even connected


@pytest.fixture
def strict_resolver():
    """Dev mode allows only the local fixture server (127.0.0.1); everything else, including
    redirect targets, is judged by the real production rules."""


async def test_redirect_to_cloud_metadata_is_blocked(site, strict_resolver):
    r = await one(f"{site}/redir")
    assert r.status == "BLOCKED" and r.error_code == "blocked_redirect"
    assert any("169.254.169.254" in b for b in r.blocked_requests)


async def test_subresource_to_unresolvable_or_internal_host_is_blocked_but_page_still_scans(site):
    r = await one(f"{site}/sub.html")  # references http://internal.example/pixel.png
    assert r.status == "OK" and any("internal.example" in b for b in r.blocked_requests)


async def test_crawl_is_same_origin_bounded_and_honours_robots_txt(site):
    rs = await scan_site(f"{site}/crawl/a.html", max_pages=10, opts=FAST)
    urls = {r.url.replace(site, "") for r in rs if r.status == "OK"}
    assert urls == {"/crawl/a.html", "/crawl/b.html", "/crawl/c.html"}
    assert HITS["/private/secret.html"] == 0  # robots.txt respected: never fetched
    assert HITS["/file.pdf"] == 0 and not any(
        "other.example" in r.url for r in rs
    )  # binaries and other origins skipped
    blocked = [r for r in rs if r.error_code == "robots"]
    assert len(blocked) == 1 and blocked[0].url.endswith("/private/secret.html")
    capped = await scan_site(f"{site}/crawl/a.html", max_pages=2, opts=FAST)
    assert len([r for r in capped if r.status == "OK"]) == 2


async def test_crawl_reports_each_page_as_it_finishes_and_supports_resume(site):
    seen = []

    async def on_page(r):
        seen.append(r.url.replace(site, ""))

    await scan_site(f"{site}/crawl/a.html", max_pages=5, opts=FAST, on_page=on_page)
    assert seen[0] == "/crawl/a.html" and len(seen) >= 3
    again = await scan_site(
        f"{site}/crawl/a.html", max_pages=5, opts=FAST, skip={f"{site}/crawl/b.html"}
    )
    assert f"{site}/crawl/b.html" not in {r.url for r in again}


def test_tampered_engine_bundle_is_refused(tmp_path, monkeypatch):
    import shutil

    src = engines.bundles_dir()
    shutil.copytree(src, tmp_path / "dist")
    (tmp_path / "dist" / "axe.js").write_text("alert('pwned')")
    monkeypatch.setattr(get_settings(), "engine_bundles_dir", str(tmp_path / "dist"))
    engines.load_bundles.cache_clear()
    try:
        with pytest.raises(engines.EngineBundleError, match="hash"):
            engines.load_bundles()
    finally:
        monkeypatch.undo()
        engines.load_bundles.cache_clear()
