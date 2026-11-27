"""Legal pages: public, versioned, and never invented by the platform."""

from datetime import date

import pytest
from a11y_core import legal
from a11y_core.config import Scope, get_config
from a11y_core.config.registry import GuardrailError

from .conftest import sql, super_admin_headers

BODY = "# Terms\n\nThese are the real terms the company wrote. " + "x" * 60


@pytest.fixture(autouse=True)
async def _clean():
    async def wipe():
        await sql("DELETE FROM setting_versions WHERE comment LIKE 'test-%'")
        r = get_config()._r()
        for k in await r.keys("cfg:*"):
            await r.delete(k)

    await wipe()
    yield
    await wipe()


async def save(items, comment="test-legal"):
    await get_config().save(
        "legal.pages", Scope.GLOBAL, "", {"items": items}, comment=comment, actor=None
    )


async def test_the_platform_ships_no_legal_text(client):
    assert (await get_config().effective("legal.pages")).value.items == []
    assert (await client.get("/legal")).json() == []
    assert (await client.get("/legal/terms")).status_code == 404


async def test_a_published_page_is_public_without_signing_in(client):
    await save(
        [
            {
                "slug": "terms",
                "status": "published",
                "version": "2026-12",
                "effective_date": "2026-12-01",
                "body": BODY,
            }
        ]
    )
    listed = await client.get("/legal")
    assert (
        listed.json() == [{"slug": "terms", "title": "Terms of service"}]
        and "max-age" in listed.headers["cache-control"]
    )
    page = (await client.get("/legal/terms")).json()
    assert (
        page["body"] == BODY
        and page["version"] == "2026-12"
        and page["effective_date"] == "2026-12-01"
        and page["title"] == "Terms of service"
    )


async def test_drafts_are_not_public_and_unknown_pages_are_404(client):
    await save(
        [
            {"slug": "privacy", "status": "draft", "body": BODY},
            {"slug": "terms", "status": "published", "effective_date": "2026-12-01", "body": BODY},
        ]
    )
    assert [p["slug"] for p in (await client.get("/legal")).json()] == ["terms"]
    assert (
        await client.get("/legal/privacy")
    ).status_code == 404  # a draft is invisible, however it is asked for
    assert (await client.get("/legal/not-a-page")).status_code == 404
    assert (await client.get("/legal/..%2Fterms")).status_code == 404


async def test_a_custom_title_is_used(client):
    await save(
        [
            {
                "slug": "privacy",
                "title": "How we handle your data",
                "status": "published",
                "effective_date": "2026-12-01",
                "body": BODY,
            }
        ]
    )
    assert (await client.get("/legal/privacy")).json()["title"] == "How we handle your data"


@pytest.mark.parametrize(
    "page,why",
    [
        (
            {
                "slug": "terms",
                "status": "published",
                "effective_date": "2026-12-01",
                "body": "short",
            },
            "needs its text",
        ),
        ({"slug": "terms", "status": "published", "body": BODY}, "effective date"),
    ],
)
async def test_a_half_written_page_cannot_be_published(page, why):
    with pytest.raises(GuardrailError, match=why):
        await save([page])


async def test_each_page_can_appear_once():
    with pytest.raises(GuardrailError):
        await save([{"slug": "terms"}, {"slug": "terms"}])


async def test_changes_are_versioned_audited_and_flagged_high_risk(client):
    await save(
        [{"slug": "terms", "status": "published", "effective_date": "2026-12-01", "body": BODY}],
        comment="test-v1",
    )
    await save(
        [
            {
                "slug": "terms",
                "status": "published",
                "effective_date": "2027-01-01",
                "body": BODY + " revised",
            }
        ],
        comment="test-v2",
    )
    h = super_admin_headers()
    hist = (await client.get("/admin/settings/legal.pages/history", headers=h)).json()
    assert [v["comment"] for v in hist[:2]] == [
        "test-v2",
        "test-v1",
    ]  # which text was live when is always answerable
    defs = {d["key"]: d for d in (await client.get("/admin/settings", headers=h)).json()}
    assert (
        defs["legal.pages"]["high_risk"] is True
        and "platform provides none" in defs["legal.pages"]["description"]
    )
    assert (
        date(2027, 1, 1).isoformat() == (await client.get("/legal/terms")).json()["effective_date"]
    )
    assert set(legal.SLUGS) == set(legal.TITLES)
