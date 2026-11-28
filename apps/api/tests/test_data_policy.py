# ruff: noqa: F811
"""The organisation data policy (ADR 0024): retention, storage region, human review, and AI on documents."""

import uuid
from datetime import UTC, datetime

import pytest
from a11y_core import data_policy, documents, notify, storage
from a11y_core.ai import AIUnavailable, LLMRequest, Message, get_gateway
from a11y_core.ai.adapters import FakeAdapter
from a11y_core.config import Scope, get_config
from a11y_core.models import Role
from a11y_core.storage import MemoryStore, StorageError

from .conftest import make_org, sql, super_admin_headers
from .test_ai_gateway import model, prov
from .test_billing import auth
from .test_document_audits import defective_pdf, needs_verapdf  # noqa: F401
from .test_document_fixes import audited  # noqa: F401
from .test_document_reviews import ask, make_reviewer  # noqa: F401
from .test_documents import (  # noqa: F401
    _clean_settings,
    pdf_bytes,
    put_setting,
    row,
    scan,
    store,
    upload,
    uploaded,
)
from .test_settings import _clean  # noqa: F401  (clears settings + cache around each test)

URL = "/org/data-policy"


async def allow(org, **controls):
    """The platform lets this organisation use some controls."""
    await put_setting("data.controls", Scope.ORG, str(org), **controls)


async def set_policy(client, org, user, **policy):
    return await client.put(URL, headers=auth(org, user), json=policy)


async def put_regions(items, default_id="default"):
    await put_setting("data.regions", Scope.GLOBAL, "", items=items, default_id=default_id)


EU = {"id": "eu", "label": "European Union (Frankfurt)", "bucket": "a11y-eu"}


@pytest.fixture
def stores():
    """One in-memory store per region, so we can see exactly where bytes go."""
    default, eu = MemoryStore(), MemoryStore()
    storage.set_store(default, "default")
    storage.set_store(eu, "eu")
    yield {"default": default, "eu": eu}
    storage.set_store(None)


# --- the three layers ------------------------------------------------------------------------------------------------


async def test_the_defaults_are_the_safe_ones():
    org, *_ = await make_org(plan="GROWTH")
    e = await data_policy.effective(org)
    assert (e.retention_days, e.region.id, e.allow_human_review, e.ai_on_documents) == (
        30,
        "default",
        True,
        False,
    )
    assert e.ai_require_zero_retention is True and e.ai_regions == ()


async def test_a_plan_that_has_not_allowed_a_control_ignores_the_organisations_choice():
    org, user, _ = await make_org(plan="GROWTH")
    # the organisation's own setting exists (written before a downgrade, say) but the plan does not allow it
    await get_config().save(
        "data.policy",
        Scope.ORG,
        str(org),
        {
            "ai_on_documents": True,
            "storage_region": "eu",
            "retention_days": 5,
            "allow_human_review": False,
        },
        comment="test-doc",
        actor=None,
    )
    await put_regions([EU])
    await allow(
        org,
        can_enable_ai=False,
        can_choose_region=False,
        can_set_retention=False,
        can_block_human_review=False,
    )
    e = await data_policy.effective(org)
    assert (e.ai_on_documents, e.region.id, e.retention_days, e.allow_human_review) == (
        False,
        "default",
        30,
        True,
    )
    await allow(
        org,
        can_enable_ai=True,
        can_choose_region=True,
        can_set_retention=True,
        can_block_human_review=True,
    )
    e = await data_policy.effective(org)
    assert (e.ai_on_documents, e.region.id, e.retention_days, e.allow_human_review) == (
        True,
        "eu",
        5,
        False,
    )


async def test_retention_can_only_be_shortened_never_extended_past_the_plan():
    org, user, _ = await make_org(plan="GROWTH")
    await allow(org, min_retention_days=3)
    await put_setting("documents.retention", Scope.GLOBAL, "", retention_days=30)
    for days, expect in (
        (7, 7),
        (1, 3),
        (400, 30),
    ):  # the floor and the ceiling hold even if stored values are out of range
        await get_config().save(
            "data.policy",
            Scope.ORG,
            str(org),
            {"retention_days": days},
            comment="test-doc",
            actor=None,
        )
        assert (await data_policy.effective(org)).retention_days == expect


# --- the organisation's page: what may be set, and what is refused -----------------------------------------------------------


async def test_the_policy_page_is_for_administrators_and_shows_what_is_in_force(client):
    org, admin, _ = await make_org(plan="GROWTH")
    member, mh = await _member(org)
    assert (await client.get(URL, headers=mh)).status_code == 403
    assert (await client.get(URL)).status_code == 401
    r = (await client.get(URL, headers=auth(org, admin))).json()
    assert r["effective"] == {
        "retention_days": 30,
        "retention_ceiling": 30,
        "region": {"id": "default", "label": "Default region"},
        "allow_human_review": True,
        "ai_on_documents": False,
        "ai_require_zero_retention": True,
        "ai_regions": [],
    }
    assert r["controls"]["can_enable_ai"] is False and r["documents"] == {
        "stored": 0,
        "by_region": {},
    }
    assert [x["id"] for x in r["regions"]] == ["default"]


async def _member(org):
    from .test_reports_api import add_member

    uid = await add_member(org)
    return uid, auth(org, uid, role="STANDARD_USER")


async def test_each_refusal_says_what_is_not_allowed_and_nothing_is_saved(client):
    org, user, _ = await make_org(plan="GROWTH")
    await put_regions([EU])
    for body, field, words in (
        ({"ai_on_documents": True}, "ai_on_documents", "does not include using AI"),
        ({"storage_region": "eu"}, "storage_region", "does not let you choose where"),
        (
            {"allow_human_review": True, "retention_days": 5},
            None,
            None,
        ),  # allowed: default controls let retention be shortened
    ):
        r = await set_policy(client, org, user, **body)
        if field:
            assert (
                r.status_code == 422 and r.json()["field"] == field and words in r.json()["detail"]
            ), r.text
        else:
            assert r.status_code == 200, r.text
    await allow(org, can_set_retention=False)
    r = await set_policy(client, org, user, retention_days=9)
    assert r.status_code == 422 and "does not let you choose how long" in r.json()["detail"]
    await allow(org, can_set_retention=True, min_retention_days=7)
    assert (
        "at least 7 days"
        in (await set_policy(client, org, user, retention_days=3)).json()["detail"]
    )
    assert (
        "at most 30 days"
        in (await set_policy(client, org, user, retention_days=90)).json()["detail"]
    )
    await allow(org, can_block_human_review=False)
    assert (
        "switch off human review"
        in (await set_policy(client, org, user, allow_human_review=False)).json()["detail"]
    )
    await allow(org, can_choose_region=True)
    assert (
        "not available"
        in (await set_policy(client, org, user, storage_region="nowhere")).json()["detail"]
    )
    assert (await client.get(URL, headers=auth(org, user))).json()["chosen"][
        "storage_region"
    ] is None


async def test_a_change_is_recorded_and_applies_at_once(client):
    org, user, _ = await make_org(plan="GROWTH")
    await allow(org, can_enable_ai=True)
    r = await set_policy(
        client, org, user, ai_on_documents=True, ai_regions=["EU", " in "], retention_days=14
    )
    assert r.status_code == 200
    e = r.json()["effective"]
    assert e["ai_on_documents"] and e["ai_regions"] == ["eu", "in"] and e["retention_days"] == 14
    a = await sql(
        "SELECT detail FROM audit_log WHERE organization_id=$1 AND action='data_policy.changed'",
        org,
    )
    assert len(a) == 1 and "ai_on_documents" in a[0]["detail"]


# --- retention ---------------------------------------------------------------------------------------------------------------------


async def test_a_shorter_retention_applies_to_new_files_and_shortens_the_ones_already_stored(
    client, store
):
    org, user, _ = await make_org(plan="GROWTH")
    did = await uploaded(client, org, user)
    before = (await row(did))["expires_at"]
    r = await set_policy(client, org, user, retention_days=2)
    assert r.json()["existing_files_shortened"] == 1
    after = (await row(did))["expires_at"]
    assert (
        after < before
        and 1.9 < (after - (await row(did))["created_at"]).total_seconds() / 86400 < 2.1
    )
    fresh = await uploaded(client, org, user)
    assert (
        1.9 < ((await row(fresh))["expires_at"] - datetime.now(UTC)).total_seconds() / 86400 < 2.1
    )
    # lengthening later never brings an already-shortened file back
    await set_policy(client, org, user, retention_days=20)
    assert (await row(did))["expires_at"] == after
    assert (await client.get("/documents/policy", headers=auth(org, user))).json()[
        "retention_days"
    ] == 20


# --- regions: a file never leaves the one it was written to ---------------------------------------------------------------


async def test_files_go_to_the_chosen_region_and_stay_there(client, stores):
    org, user, _ = await make_org(plan="GROWTH")
    await put_regions([EU])
    await allow(org, can_choose_region=True)
    h = auth(org, user)
    d0 = await uploaded(
        client, org, user, "a.pdf", pdf_bytes(1)
    )  # before choosing: the default region
    assert (
        (await row(d0))["region"] == "default"
        and len(stores["default"].objects) == 1
        and stores["eu"].objects == {}
    )
    assert (await set_policy(client, org, user, storage_region="eu")).status_code == 200
    d1 = await uploaded(client, org, user, "b.pdf", pdf_bytes(2))
    assert (await row(d1))["region"] == "eu"
    assert (
        len(stores["eu"].objects) == 1 and len(stores["default"].objects) == 1
    )  # the new bytes went only to the EU store
    assert list(stores["eu"].objects)[0].endswith(f"{d1}/original")
    assert await scan(org, d1) == "CLEAN" and await scan(org, d0) == "CLEAN"
    # switching back does not move anything: each file is read from, and deleted in, its own region
    assert (await set_policy(client, org, user, storage_region="default")).status_code == 200
    assert (await client.get(f"/documents/{d1}/download", headers=h)).content == pdf_bytes(2)
    assert (await client.get(f"/documents/{d0}/download", headers=h)).content == pdf_bytes(1)
    assert (await client.delete(f"/documents/{d1}", headers=h)).status_code == 204
    assert stores["eu"].objects == {} and len(stores["default"].objects) == 1
    assert (await client.get(URL, headers=h)).json()["documents"]["by_region"] == {"default": 1}


async def test_an_unknown_or_switched_off_region_is_never_silently_replaced():
    storage.set_store(None)
    with pytest.raises(StorageError, match="not configured"):
        await storage.store_for("nowhere")
    org, *_ = await make_org(plan="GROWTH")
    await put_regions([{**EU, "is_active": False}])
    await allow(org, can_choose_region=True)
    await get_config().save(
        "data.policy", Scope.ORG, str(org), {"storage_region": "eu"}, comment="test-doc", actor=None
    )
    e = await data_policy.effective(org)
    assert e.region.id == "default" and "eu" not in [
        r.id for r in e.offered_regions
    ]  # not offered for new files...
    assert (await storage.regions())[0][
        "eu"
    ].is_active is False  # ...but still known, so its existing files stay readable


async def test_region_settings_are_guarded():
    from a11y_core.config.registry import GuardrailError, get_def

    d = get_def("data.regions")
    with pytest.raises(GuardrailError):
        d.validate({"items": [EU, EU]})
    with pytest.raises(GuardrailError):
        d.validate({"items": [EU], "default_id": "nope"})
    with pytest.raises(GuardrailError):
        d.validate({"items": [{**EU, "is_active": False}], "default_id": "eu"})
    assert d.validate({"items": [EU], "default_id": "eu"})["default_id"] == "eu"


@needs_verapdf
async def test_a_fixed_copy_stays_in_the_region_of_the_file_it_came_from(client, stores):
    from a11y_documents import fix_task

    org, user, _ = await make_org(plan="GROWTH")
    await put_regions([EU])
    await allow(org, can_choose_region=True)
    await set_policy(client, org, user, storage_region="eu")
    did = await audited(client, org, user, defective_pdf())
    await set_policy(client, org, user, storage_region="default")  # the organisation moves on...
    await client.put(f"/documents/{did}/fix", headers=auth(org, user), json={"language": "en"})
    fid = (await client.post(f"/documents/{did}/fix/build", headers=auth(org, user))).json()["id"]
    assert await fix_task.run_fix(org, uuid.UUID(fid)) == "READY"
    copy = (await client.get(f"/documents/{did}/fix", headers=auth(org, user))).json()["fix"][
        "result_document_id"
    ]
    assert (await row(copy))["region"] == "eu" and stores[
        "default"
    ].objects == {}  # ...but the copy is made where the original is


# --- people may be told not to look -----------------------------------------------------------------------------------------------


@needs_verapdf
async def test_an_organisation_can_forbid_human_review(client, monkeypatch):
    org, user, _ = await make_org(plan="GROWTH")
    did = await audited(client, org, user, defective_pdf())
    assert (await set_policy(client, org, user, allow_human_review=False)).status_code == 200
    r = await ask(client, org, user, did)
    assert (
        r.status_code == 403
        and r.json()["code"] == "review_blocked_by_policy"
        and "data policy" in r.json()["detail"]
    )
    assert (await client.get("/documents/policy", headers=auth(org, user))).json()[
        "human_review_allowed"
    ] is False
    assert await sql("SELECT 1 FROM document_reviews WHERE organization_id=$1", org) == []
    await set_policy(client, org, user, allow_human_review=True)
    assert (await ask(client, org, user, did)).status_code == 202


# --- AI: nothing leaves unless the policy allows it, and it fails closed ---------------------------------------------------------


def doc_req(org, **kw):
    return LLMRequest(
        "alt_text",
        [Message("user", "describe this page")],
        org_id=org,
        data_class="customer_document",
        **kw,
    )


async def setup_ai(*providers, task="alt_text"):
    cfg = get_config()
    await cfg.save(
        "ai.providers",
        Scope.GLOBAL,
        "",
        {"items": [prov(p, **kw) for p, kw in providers]},
        comment="test-ai",
        actor=None,
    )
    await cfg.save(
        "ai.models",
        Scope.GLOBAL,
        "",
        {"items": [model(f"m-{p}", p, caps=("vision", "text")) for p, _ in providers]},
        comment="test-ai",
        actor=None,
    )
    await cfg.save(
        f"ai.route.{task}",
        Scope.GLOBAL,
        "",
        {
            "primary_model_id": f"m-{providers[0][0]}",
            "fallback_model_ids": [f"m-{p}" for p, _ in providers[1:]],
        },
        comment="test-ai",
        actor=None,
    )


GOOD = {"data_policy": {"zero_retention": True, "processing_regions": ["eu"]}}
KEEPS = {"data_policy": {"zero_retention": False, "processing_regions": ["eu"]}}
ABROAD = {"data_policy": {"zero_retention": True, "processing_regions": ["us"]}}


@pytest.fixture(autouse=True)
async def _ai_clean():
    FakeAdapter.calls.clear()
    yield
    await sql("DELETE FROM ai_usage WHERE task_key = 'alt_text'")


async def test_by_default_no_customer_document_is_sent_to_any_ai_provider():
    org, *_ = await make_org(plan="GROWTH")
    await setup_ai(("good", GOOD))
    with pytest.raises(AIUnavailable) as e:
        await get_gateway().complete(doc_req(org))
    assert e.value.reason == "blocked_by_data_policy" and "does not allow AI" in str(e.value)
    assert FakeAdapter.calls == []  # nothing reached any provider
    # other AI work that carries no customer file is not affected
    assert (
        await get_gateway().complete(LLMRequest("alt_text", [Message("user", "x")], org_id=org))
    ).provider_id == "good"


async def test_a_plan_that_does_not_include_ai_on_documents_blocks_it_even_if_the_organisation_asked():
    org, *_ = await make_org(plan="GROWTH")
    await setup_ai(("good", GOOD))
    await get_config().save(
        "data.policy",
        Scope.ORG,
        str(org),
        {"ai_on_documents": True},
        comment="test-doc",
        actor=None,
    )
    with pytest.raises(AIUnavailable) as e:
        await get_gateway().complete(doc_req(org))
    assert e.value.reason == "blocked_by_data_policy" and FakeAdapter.calls == []


async def test_only_providers_that_keep_nothing_and_process_in_the_allowed_regions_are_used():
    org, *_ = await make_org(plan="GROWTH")
    await allow(org, can_enable_ai=True)
    await get_config().save(
        "data.policy",
        Scope.ORG,
        str(org),
        {"ai_on_documents": True, "ai_regions": ["eu"]},
        comment="test-doc",
        actor=None,
    )
    # the preferred provider keeps data and the next processes abroad; only the third qualifies
    await setup_ai(("keeps", KEEPS), ("abroad", ABROAD), ("good", GOOD))
    r = await get_gateway().complete(doc_req(org))
    assert r.provider_id == "good" and [c["provider"] for c in FakeAdapter.calls] == ["good"]


async def test_when_no_provider_qualifies_nothing_is_sent_and_the_reasons_are_given():
    org, *_ = await make_org(plan="GROWTH")
    await allow(org, can_enable_ai=True)
    await get_config().save(
        "data.policy",
        Scope.ORG,
        str(org),
        {"ai_on_documents": True, "ai_regions": ["in"]},
        comment="test-doc",
        actor=None,
    )
    await setup_ai(("keeps", KEEPS), ("abroad", ABROAD))
    with pytest.raises(AIUnavailable) as e:
        await get_gateway().complete(doc_req(org))
    msg = str(e.value)
    assert (
        e.value.reason == "blocked_by_data_policy"
        and "does not promise to keep nothing" in msg
        and "does not process in in" in msg
    )
    assert FakeAdapter.calls == []


async def test_a_zero_retention_requirement_can_be_relaxed_by_the_organisation_but_not_the_region_rule():
    org, *_ = await make_org(plan="GROWTH")
    await allow(org, can_enable_ai=True)
    await get_config().save(
        "data.policy",
        Scope.ORG,
        str(org),
        {"ai_on_documents": True, "ai_require_zero_retention": False, "ai_regions": ["eu"]},
        comment="test-doc",
        actor=None,
    )
    await setup_ai(("abroad", ABROAD), ("keeps", KEEPS))
    assert (
        await get_gateway().complete(doc_req(org))
    ).provider_id == "keeps"  # may keep data, but is in the right region


async def test_a_request_with_no_organisation_is_refused():
    await setup_ai(("good", GOOD))
    with pytest.raises(AIUnavailable) as e:
        await get_gateway().complete(doc_req(None))
    assert e.value.reason == "blocked_by_data_policy" and FakeAdapter.calls == []


# --- deletion on request --------------------------------------------------------------------------------------------------------------


async def test_an_administrator_can_delete_every_document_in_every_region(client, stores):
    org, user, _ = await make_org(plan="GROWTH")
    await put_regions([EU])
    await allow(org, can_choose_region=True)
    h = auth(org, user)
    await uploaded(client, org, user, "a.pdf")
    await set_policy(client, org, user, storage_region="eu")
    await uploaded(client, org, user, "b.pdf", pdf_bytes(2))
    assert (
        await client.post(f"{URL}/delete-documents", headers=h, json={})
    ).status_code == 422  # must confirm
    assert stores["eu"].objects and stores["default"].objects
    r = await client.post(f"{URL}/delete-documents", headers=h, json={"confirm": True})
    assert r.status_code == 200 and r.json() == {"deleted": 2}
    assert stores["eu"].objects == {} and stores["default"].objects == {}
    assert (await client.get("/documents", headers=h)).json() == []
    assert await sql(
        "SELECT 1 FROM audit_log WHERE organization_id=$1 AND action='documents.deleted_all'", org
    )
    member, mh = await _member(org)
    assert (
        await client.post(f"{URL}/delete-documents", headers=mh, json={"confirm": True})
    ).status_code == 403


# --- the owner's view ----------------------------------------------------------------------------------------------------------------------


async def test_the_owner_sees_where_files_are_and_whether_each_region_is_configured(client, stores):
    org, user, _ = await make_org(plan="GROWTH")
    await put_regions([EU])
    await allow(org, can_choose_region=True)
    await uploaded(client, org, user, "a.pdf")
    await set_policy(client, org, user, storage_region="eu")
    await uploaded(client, org, user, "b.pdf", pdf_bytes(2))
    ov = (await client.get("/admin/documents/overview", headers=super_admin_headers())).json()
    regions = {x["region"]: x for x in ov["by_region"]}
    assert (
        regions["eu"]["configured"]
        and regions["eu"]["files"] >= 1
        and regions["default"]["files"] >= 1
    )
    assert (
        ov["health"]["regions"] == {"default": "ok", "eu": "ok"} and ov["health"]["storage"] == "ok"
    )
    # a region that was removed while it still holds files is reported, never hidden
    await put_regions([])
    ov = (await client.get("/admin/documents/overview", headers=super_admin_headers())).json()
    assert {x["region"]: x["configured"] for x in ov["by_region"]}["eu"] is False
    assert Role and notify and documents  # (shared imports kept for readability of the suite)


async def test_the_document_layout_task_is_always_subject_to_the_policy_whatever_the_caller_says():
    org, *_ = await make_org(plan="GROWTH")
    await setup_ai(("good", GOOD), task="doc_layout")
    plain = LLMRequest(
        "doc_layout", [Message("user", "layout of this page")], org_id=org
    )  # the caller forgot data_class
    with pytest.raises(AIUnavailable) as e:
        await get_gateway().complete(plain)
    assert e.value.reason == "blocked_by_data_policy" and FakeAdapter.calls == []
