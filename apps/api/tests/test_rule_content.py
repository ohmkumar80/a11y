"""Fix-guidance content library (PROJECT_PLAN 3.13).

Every example is checked by the real engines: the 'before' must be flagged, the 'after' must clear the rule
and introduce nothing new. Content that fails this cannot ship, so we never teach a fix that does not work."""

import asyncio

import pytest
import yaml
from a11y_core.rules import RuleContent, get_registry, rules_dir
from a11y_web_audit.oracle import found, scan_snippet, wrap
from playwright.async_api import async_playwright

REG = get_registry()
MACHINE = sorted(c.id for c in REG.content.values() if c.machine_check)


def test_every_content_file_names_a_real_rule():
    assert REG.content, "no content loaded"
    assert set(REG.content) <= set(REG.canonical)


def test_the_most_common_rules_are_covered():
    # the rules that account for most real-world findings must have guidance
    core = {
        "image-alt",
        "button-name",
        "link-name",
        "form-field-label",
        "color-contrast",
        "html-lang",
        "document-title",
        "frame-title",
        "label-in-name",
        "aria-roles",
    }
    assert core <= set(REG.content)


def test_content_is_draft_until_an_sme_reviews_it():
    assert {c.status for c in REG.content.values()} == {"draft"}


def test_unreviewable_rules_say_why():
    for c in REG.content.values():
        if not c.machine_check:
            assert len(c.manual_reason) > 10, c.id


def test_content_is_plain_language_and_free_of_unsafe_links():
    for c in REG.content.values():
        assert c.summary.endswith("."), c.id
        for link in c.links:
            assert link.url.startswith("https://www.w3.org/"), (c.id, link.url)


def test_bad_content_is_rejected():
    ok = yaml.safe_load((rules_dir() / "content" / "image-alt.yaml").read_text())
    RuleContent(**ok)
    with pytest.raises(ValueError):
        RuleContent(**{**ok, "examples": [{"stack": "react", "before": "a", "after": "b"}]})
    with pytest.raises(ValueError):
        RuleContent(**{**ok, "links": [{"title": "x", "url": "http://insecure.example"}]})
    with pytest.raises(ValueError):
        RuleContent(**{**ok, "machine_check": False})


def test_wrap_builds_valid_pages():
    assert wrap("<p>x</p>").startswith("<!doctype html><html lang=")
    assert "<title>" in wrap("<html lang='en'>")
    assert wrap("<head><title>T</title></head>").count("<head>") == 1
    assert wrap("<body><p>x</p></body>").count("<body>") == 1
    assert "<meta" in wrap('<meta name="viewport" content="x">').split("</head>")[0]


@pytest.fixture(scope="module")
def results():
    async def run():
        out = {}
        async with async_playwright() as p:
            b = await p.chromium.launch(chromium_sandbox=False)
            for cid in MACHINE:
                e = REG.content[cid].html_example()
                out[cid] = (await scan_snippet(b, e.before), await scan_snippet(b, e.after))
            await b.close()
        return out

    return asyncio.run(run())


@pytest.mark.parametrize("cid", MACHINE)
def test_before_is_flagged_and_after_is_clean(results, cid):
    before, after = results[cid]
    assert found(before, cid), f"{cid}: the 'before' example is not flagged by any engine"
    assert not found(after, cid), f"{cid}: the 'after' example still fails"
    new = {f.canonical_rule_id for f in after if f.kind == "violation"} - {
        f.canonical_rule_id for f in before if f.kind == "violation"
    }
    assert not new, f"{cid}: the fix introduces {sorted(new)}"


async def test_guidance_endpoint(client):
    from .conftest import make_org
    from .test_billing import auth

    org, user, _ = await make_org()
    h = auth(org, user)
    r = await client.get("/rules/image-alt/guidance", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["review_status"] == "draft" and body["steps"] and body["examples"][0]["before"]
    assert (await client.get("/rules/not-a-rule/guidance", headers=h)).status_code == 404
    assert (await client.get("/rules/image-alt/guidance")).status_code == 401
    # honest about rules a machine cannot verify
    m = await client.get("/rules/focus-visible/guidance", headers=h)
    assert m.json()["machine_checked"] is False
