# ruff: noqa: F811
"""Page screenshots and element positions: the raw material of the Fix Workbench."""

import uuid
from functools import partial

import pytest
from a11y_core.config import Scope, get_config
from a11y_web_audit import tasks
from a11y_web_audit.scanner import ScanOptions
from a11y_web_audit.tasks import run_scan
from playwright.async_api import async_playwright

from .conftest import make_org, sql
from .test_billing import auth
from .test_scans_api import FAST, PORTS, _cfg_reset, create, dev, high_ports, site  # noqa: F401  (fixtures)

SHOT = ScanOptions(
    page_timeout_s=20,
    settle_ms=100,
    politeness_delay_ms=0,
    ports=PORTS,
    screenshot=True,
    screenshot_max_height=1000,
)


@pytest.fixture(autouse=True)
async def _clean_settings():
    async def wipe():
        await sql("DELETE FROM setting_versions WHERE comment LIKE 'test-%'")
        r = get_config()._r()
        for k in await r.keys("cfg:*"):
            await r.delete(k)

    await wipe()
    yield
    await wipe()


async def scan(client, site, page, *, opts=SHOT, **kw):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    sid = uuid.UUID((await create(client, h, f"{site}/{page}", **kw)).json()["id"])
    assert await run_scan(org, sid, opts_override=opts) == "SUCCEEDED"
    return org, user, sid, h


async def test_screenshot_is_saved_capped_and_served_privately(client, site, dev):
    org, user, sid, h = await scan(client, site, "tall.html")
    s = (await client.get(f"/scans/{sid}", headers=h)).json()
    shot = s["pages"][0]["screenshot"]
    assert shot["width"] == 1280 and shot["height"] == 1000  # capped at the setting
    assert shot["truncated"] is True and shot["page_height"] >= 3000

    pid = s["pages"][0]["id"]
    r = await client.get(f"/scans/{sid}/pages/{pid}/screenshot", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content[:3] == b"\xff\xd8\xff" and r.headers["x-content-type-options"] == "nosniff"
    assert "private" in r.headers["cache-control"]
    assert len(r.content) < 400_000  # small enough to keep many per scan

    org2, user2, _ = await make_org(plan="GROWTH")
    h2 = auth(org2, user2)
    assert (await client.get(f"/scans/{sid}/pages/{pid}/screenshot", headers=h2)).status_code == 404
    assert (await client.get(f"/scans/{sid}/pages/{pid}/screenshot")).status_code == 401
    assert (
        await client.get(f"/scans/{sid}/pages/{uuid.uuid4()}/screenshot", headers=h)
    ).status_code == 404


async def test_a_short_page_is_not_marked_truncated(client, site, dev):
    org, user, sid, h = await scan(
        client,
        site,
        "good.html",
        opts=ScanOptions(**{**SHOT.__dict__, "screenshot_max_height": 5000}),
    )
    shot = (await client.get(f"/scans/{sid}", headers=h)).json()["pages"][0]["screenshot"]
    assert shot["truncated"] is False and shot["height"] == shot["page_height"]


async def test_scans_without_screenshots_still_work(client, site, dev):
    org, user, sid, h = await scan(client, site, "bad.html", opts=FAST)
    assert (await client.get(f"/scans/{sid}", headers=h)).json()["pages"][0]["screenshot"] is None


async def test_findings_carry_the_elements_position_in_page_pixels(client, site, dev):
    org, user, sid, h = await scan(client, site, "tall.html")
    fs = (await client.get(f"/scans/{sid}/findings?rule=image-alt&limit=10", headers=h)).json()[
        "findings"
    ]
    rects = sorted((f["element"]["rect"] for f in fs), key=lambda r: r["y"])
    assert rects[0] == {"x": 100, "y": 200, "w": 50, "h": 50}
    assert rects[1] == {"x": 10, "y": 2600, "w": 30, "h": 30}  # below the cap: UI must say so


async def test_an_element_inside_an_iframe_is_positioned_on_the_page_not_the_frame(
    client, site, dev
):
    org, user, sid, h = await scan(client, site, "frames.html")
    fs = (await client.get(f"/scans/{sid}/findings?rule=image-alt&limit=10", headers=h)).json()[
        "findings"
    ]
    assert fs, "the framed image should be reported"
    r = fs[0]["element"]["rect"]
    async with async_playwright() as p:
        b = await p.chromium.launch(chromium_sandbox=False)
        pg = await b.new_page(viewport={"width": 1280, "height": 800})
        await pg.goto(f"{site}/frames.html")
        f = await pg.evaluate(
            "() => { const r = document.querySelector('iframe').getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; }"
        )
        await b.close()
    assert f["x"] <= r["x"] <= f["x"] + f["w"] and f["y"] <= r["y"] <= f["y"] + f["h"], (r, f)


async def test_settings_decide_how_many_pages_keep_a_screenshot(client, site, dev, monkeypatch):
    monkeypatch.setattr(tasks, "ScanOptions", partial(ScanOptions, ports=PORTS))
    org, user, _ = await make_org(plan="GROWTH")
    await get_config().save(
        "scan.engines",
        Scope.ORG,
        str(org),
        {"screenshot_pages": 1, "politeness_delay_ms": 0},
        comment="test-shots",
        actor=None,
    )
    h = auth(org, user)
    sid = uuid.UUID((await create(client, h, f"{site}/", mode="crawl", max_pages=3)).json()["id"])
    res = await run_scan(org, sid)
    assert res == "SUCCEEDED", (
        await sql("SELECT error_code, error_detail FROM scan_jobs WHERE id=$1", sid)
    )[0]  # real settings -> real options
    pages = (await client.get(f"/scans/{sid}", headers=h)).json()["pages"]
    assert len(pages) >= 2 and sum(1 for x in pages if x["screenshot"]) == 1


async def test_screenshots_can_be_switched_off(client, site, dev, monkeypatch):
    monkeypatch.setattr(tasks, "ScanOptions", partial(ScanOptions, ports=PORTS))
    org, user, _ = await make_org(plan="GROWTH")
    await get_config().save(
        "scan.engines", Scope.ORG, str(org), {"screenshots": False}, comment="test-off", actor=None
    )
    h = auth(org, user)
    sid = uuid.UUID((await create(client, h, f"{site}/good.html")).json()["id"])
    assert await run_scan(org, sid) == "SUCCEEDED"
    assert (await client.get(f"/scans/{sid}", headers=h)).json()["pages"][0]["screenshot"] is None


async def test_a_saved_screenshot_cannot_be_edited(client, site, dev):
    org, user, sid, h = await scan(client, site, "good.html")
    with pytest.raises(Exception, match="permission denied"):
        from a11y_core.db import tenant_session
        from sqlalchemy import text

        async with tenant_session(org) as db:
            await db.execute(text("UPDATE page_screenshots SET width = 1"))
