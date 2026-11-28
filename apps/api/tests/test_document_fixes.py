# ruff: noqa: F811
"""Guided PDF fixes (ADR 0022): structure reading, the fix engine, the build gate, quota and fault handling."""

import io
import uuid

import pikepdf
import pytest
from a11y_core import document_fixes, documents
from a11y_core.config import Scope
from a11y_core.doc_fix import FixPlan, check_against
from a11y_documents import audit_task, fix_task
from a11y_documents.pdf_audit import audit_pdf
from a11y_documents.pdf_fix import FixError, apply_plan
from a11y_documents.pdf_structure import inspect_structure

from .conftest import make_org, sql
from .test_billing import auth, used
from .test_document_audits import (  # noqa: F401  (fixtures and helpers)
    FEATURE,
    clean_pdf,
    defective_pdf,
    needs_verapdf,
    reservation,
    scanned_pdf,
)
from .test_documents import (  # noqa: F401
    _clean_settings,
    pdf_bytes,
    put_setting,
    row,
    scan,
    store,
    uploaded,
)


def text_plan(st) -> FixPlan:
    return FixPlan(
        title="Quarterly report",
        language="en-GB",
        alt={st.figures[0]["id"]: "A red rectangle used as a sample picture"},
        heading_levels={st.headings[1]["id"]: 2},
    )


# --- reading the structure ----------------------------------------------------------------------------


def test_structure_lists_figures_and_headings_in_document_order_with_their_text():
    st = inspect_structure(defective_pdf())
    assert st.has_structure and st.pages == 1
    assert [(h["level"], h["text"]) for h in st.headings] == [(1, "Report"), (3, "Skipped level")]
    assert len(st.figures) == 1 and st.figures[0]["alt"] == "" and st.figures[0]["editable"]
    assert all(h["page"] == 1 for h in st.headings) and st.figures[0]["page"] == 1


def test_an_untagged_file_reports_no_structure_and_cannot_be_given_alt_text():
    st = inspect_structure(pdf_bytes())
    assert not st.has_structure and st.figures == [] and st.headings == []
    problems = check_against(FixPlan(alt={"5-0": "x"}), st.as_dict())
    assert any("no tags" in p for p in problems)


# --- the plan --------------------------------------------------------------------------------------------


def test_a_plan_is_checked_in_plain_words():
    st = inspect_structure(defective_pdf()).as_dict()
    with pytest.raises(ValueError, match="language code"):
        FixPlan(language="english please")
    with pytest.raises(ValueError, match="1 to 6"):
        FixPlan(heading_levels={"1-0": 7})
    with pytest.raises(ValueError, match="1000"):
        FixPlan(alt={"1-0": "x" * 1001})
    assert FixPlan(alt={"1-0": "   "}, title="  ").is_empty()  # blanks mean "no change"
    assert check_against(FixPlan(alt={"999-0": "x"}), st)[0].startswith("One of the images")
    assert check_against(FixPlan(heading_levels={"999-0": 2}), st)[0].startswith(
        "One of the headings"
    )
    assert check_against(FixPlan(alt={"../../etc": "x"}), st) != []


# --- the engine (real veraPDF) ---------------------------------------------------------------------------


@needs_verapdf
def test_the_plan_fixes_what_it_says_and_nothing_else_and_never_touches_the_original():
    original = defective_pdf()
    keep = bytes(original)
    st = inspect_structure(original)
    before = audit_pdf(original)
    assert {"7.2-29", "7.3-1", "7.4.2-1"} <= {f["rule_id"] for f in before.findings}
    out = apply_plan(original, text_plan(st))
    assert original == keep and out != original
    after = audit_pdf(out)
    # Everything the plan addressed is gone. The only thing left is the file's own "I follow PDF/UA" label, which we never
    # add on a person's behalf (it is a claim of conformance).
    assert {f["rule_id"] for f in after.findings} <= {"5-1"}, [f["title"] for f in after.findings]
    assert all(f["severity"] == "minor" for f in after.findings)
    st2 = inspect_structure(out)
    assert (st2.title, st2.language) == ("Quarterly report", "en-GB")
    assert st2.figures[0]["alt"].startswith("A red rectangle")
    assert [(h["level"], h["text"]) for h in st2.headings] == [(1, "Report"), (2, "Skipped level")]
    assert st2.pages == st.pages  # the pages themselves are untouched
    pdf = pikepdf.open(io.BytesIO(out))
    assert bool(pdf.Root.ViewerPreferences.DisplayDocTitle) and bool(pdf.Root.MarkInfo.Marked)


@needs_verapdf
def test_changing_only_one_thing_changes_only_that_thing():
    data = defective_pdf()
    out = apply_plan(data, FixPlan(language="hi"))
    st = inspect_structure(out)
    assert (
        st.language == "hi"
        and st.figures[0]["alt"] == ""
        and [h["level"] for h in st.headings] == [1, 3]
    )


def test_a_plan_for_an_element_that_is_gone_is_refused_not_guessed():
    with pytest.raises(FixError) as e:
        apply_plan(defective_pdf(), FixPlan(alt={"9999-0": "x"}))
    assert e.value.code == "stale_plan"
    st = inspect_structure(defective_pdf())
    with pytest.raises(FixError):  # a figure id used as a heading
        apply_plan(defective_pdf(), FixPlan(heading_levels={st.figures[0]["id"]: 2}))
    with pytest.raises(FixError):
        apply_plan(b"not a pdf", FixPlan(language="en"))


# --- the flow ------------------------------------------------------------------------------------------------


async def audited(client, org, user, data):
    did = await uploaded(client, org, user, "report.pdf", data)
    assert await scan(org, did) == "CLEAN"
    a = (await client.post(f"/documents/{did}/audits", headers=auth(org, user))).json()
    assert await audit_task.run_audit(org, uuid.UUID(a["id"])) == "SUCCEEDED"
    return did


@needs_verapdf
async def test_the_whole_flow_edit_build_recheck_download(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await audited(client, org, user, defective_pdf())
    original_bytes = (await client.get(f"/documents/{did}/download", headers=h)).content
    base_used = await used(org, FEATURE)

    state = (await client.get(f"/documents/{did}/fix", headers=h)).json()
    st = state["structure"]
    assert st["has_structure"] and state["fix"] is None and len(st["figures"]) == 1
    plan = {
        "title": "Quarterly report",
        "language": "en-GB",
        "alt": {st["figures"][0]["id"]: "A red rectangle used as a sample picture"},
        "heading_levels": {st["headings"][1]["id"]: 2},
    }
    saved = await client.put(f"/documents/{did}/fix", headers=h, json=plan)
    assert (
        saved.status_code == 200
        and saved.json()["status"] == "DRAFT"
        and saved.json()["plan"]["language"] == "en-GB"
    )
    assert await used(org, FEATURE) == base_used  # saving costs nothing

    store.sent.clear()
    b = await client.post(f"/documents/{did}/fix/build", headers=h)
    assert b.status_code == 202 and b.json()["status"] == "QUEUED" and b.json()["pages"] == 1
    fid = b.json()["id"]
    assert store.sent == [("docs.build_fix", [str(org), fid], "docs")]
    assert await used(org, FEATURE) == base_used + 1 and await reservation(org, fid) == "RESERVED"
    # while it builds, the plan cannot be changed and a second build is refused (and not charged)
    assert (await client.put(f"/documents/{did}/fix", headers=h, json=plan)).json()[
        "code"
    ] == "fix_running"
    assert (await client.post(f"/documents/{did}/fix/build", headers=h)).json()[
        "code"
    ] == "fix_running"
    assert await used(org, FEATURE) == base_used + 1

    assert await fix_task.run_fix(org, uuid.UUID(fid)) == "READY"
    fix = (await client.get(f"/documents/{did}/fix", headers=h)).json()["fix"]
    assert fix["status"] == "READY" and fix["result"]["after"]["findings"] <= 1
    assert (
        fix["result"]["after"]["by_severity"]["critical"]
        == fix["result"]["after"]["by_severity"]["serious"]
        == 0
    )
    assert fix["result"]["before"]["findings"] >= 3 and fix["result"]["edits"] == 4
    assert {r["rule_id"] for r in fix["result"]["resolved"]} >= {"7.2-29", "7.3-1", "7.4.2-1"}
    assert await reservation(org, fid) == "COMMITTED" and await used(org, FEATURE) == base_used + 1

    copy_id = fix["result_document_id"]
    docs = {d["id"]: d for d in (await client.get("/documents", headers=h)).json()}
    assert (
        docs[copy_id]["derived_from"] == did
        and docs[copy_id]["filename"] == "report (fixed).pdf"
        and docs[copy_id]["ready"]
    )
    assert (
        docs[copy_id]["latest_audit"]["status"] == "SUCCEEDED"
        and docs[copy_id]["latest_audit"]["summary"]["findings"] <= 1
    )
    fixed = (await client.get(f"/documents/{copy_id}/download", headers=h)).content
    assert inspect_structure(fixed).title == "Quarterly report"
    assert (
        await client.get(f"/documents/{did}/download", headers=h)
    ).content == original_bytes  # untouched
    # the copy is stored encrypted like any file
    assert b"%PDF" not in b"".join(store.objects.values())[:0] and all(
        b"%PDF" not in v for v in store.objects.values()
    )


@needs_verapdf
async def test_a_file_must_be_checked_before_it_can_be_fixed_and_untagged_files_say_why(client):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await uploaded(client, org, user, "a.pdf", defective_pdf())
    assert (
        await client.get(f"/documents/{did}/fix", headers=h)
    ).status_code == 409  # not scanned yet
    assert await scan(org, did) == "CLEAN"
    r = await client.get(f"/documents/{did}/fix", headers=h)
    assert r.status_code == 409 and r.json()["code"] == "needs_audit"
    untagged = await audited(client, org, user, pdf_bytes())
    st = (await client.get(f"/documents/{untagged}/fix", headers=h)).json()["structure"]
    assert st["has_structure"] is False
    r = await client.put(f"/documents/{untagged}/fix", headers=h, json={"alt": {"5-0": "x"}})
    assert r.status_code == 422 and "no tags" in r.json()["detail"]
    ok = await client.put(
        f"/documents/{untagged}/fix", headers=h, json={"title": "Just a title", "language": "en"}
    )
    assert ok.status_code == 200  # properties can still be set


@needs_verapdf
async def test_building_with_nothing_chosen_or_an_invalid_plan_is_refused_clearly(client):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await audited(client, org, user, defective_pdf())
    assert (await client.post(f"/documents/{did}/fix/build", headers=h)).json()["code"] == "no_plan"
    assert (await client.put(f"/documents/{did}/fix", headers=h, json={})).status_code == 200
    assert (await client.post(f"/documents/{did}/fix/build", headers=h)).json()["code"] == "no_plan"
    r = await client.put(f"/documents/{did}/fix", headers=h, json={"language": "not a code"})
    assert r.status_code == 422 and "language code" in str(r.json())
    r = await client.put(f"/documents/{did}/fix", headers=h, json={"alt": {"999-0": "x"}})
    assert r.status_code == 422 and r.json()["code"] == "invalid_plan"


@needs_verapdf
async def test_a_plan_limit_stops_the_build_and_keeps_the_draft(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await audited(client, org, user, defective_pdf())
    await client.put(f"/documents/{did}/fix", headers=h, json={"language": "en"})
    await sql(
        "INSERT INTO entitlement_overrides (organization_id, feature_key, enabled, limit_value, reason) VALUES ($1, $2, true, $3, 'test-limit')",
        org,
        FEATURE,
        await used(org, FEATURE),
    )
    store.sent.clear()
    r = await client.post(f"/documents/{did}/fix/build", headers=h)
    assert r.json()["code"] == "quota_exceeded" and store.sent == []
    fix = (await client.get(f"/documents/{did}/fix", headers=h)).json()["fix"]
    assert fix["status"] == "DRAFT" and fix["plan"]["language"] == "en"  # nothing was lost


@needs_verapdf
async def test_a_fix_that_makes_things_worse_is_not_delivered_and_the_pages_come_back(
    client, store, monkeypatch
):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await audited(client, org, user, defective_pdf())
    base_used, base_objects = await used(org, FEATURE), len(store.objects)
    await client.put(f"/documents/{did}/fix", headers=h, json={"language": "en"})
    fid = (await client.post(f"/documents/{did}/fix/build", headers=h)).json()["id"]

    real = fix_task.audit_pdf

    def worse(data, **kw):
        r = real(data, **kw)
        r.findings.append(
            {
                "rule_id": "7.1-11",
                "source": "verapdf",
                "severity": "critical",
                "title": "The PDF has no structure (no tags)",
                "explanation": "x",
                "how_to_fix": "y",
                "wcag": [],
                "needs_human": False,
                "count": 1,
                "pages": [],
                "pages_total": 0,
                "examples": [],
            }
        )
        return r

    monkeypatch.setattr(fix_task, "audit_pdf", worse)
    assert await fix_task.run_fix(org, uuid.UUID(fid)) == "FAILED"
    fix = (await client.get(f"/documents/{did}/fix", headers=h)).json()["fix"]
    assert fix["error_code"] == "regressed" and "did not produce a file" in fix["error_detail"]
    assert fix["result_document_id"] is None and len(store.objects) == base_objects
    assert await reservation(org, fid) == "RELEASED" and await used(org, FEATURE) == base_used


@needs_verapdf
async def test_a_crash_or_a_vanished_element_fails_safely_and_gives_the_pages_back(
    client, store, monkeypatch
):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await audited(client, org, user, defective_pdf())
    base_used = await used(org, FEATURE)
    await client.put(f"/documents/{did}/fix", headers=h, json={"language": "en"})
    fid = (await client.post(f"/documents/{did}/fix/build", headers=h)).json()["id"]

    def boom(*a, **k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(fix_task, "apply_plan", boom)
    assert await fix_task.run_fix(org, uuid.UUID(fid)) == "FAILED"
    fix = (await client.get(f"/documents/{did}/fix", headers=h)).json()["fix"]
    assert fix["error_code"] == "system_fault" and "problem on our side" in fix["error_detail"]
    assert await reservation(org, fid) == "RELEASED" and await used(org, FEATURE) == base_used
    # the person can start again straight away
    assert (
        await client.put(f"/documents/{did}/fix", headers=h, json={"language": "en"})
    ).status_code == 200


@needs_verapdf
async def test_a_finished_build_is_never_run_twice(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await audited(client, org, user, defective_pdf())
    await client.put(f"/documents/{did}/fix", headers=h, json={"language": "en"})
    fid = (await client.post(f"/documents/{did}/fix/build", headers=h)).json()["id"]
    assert await fix_task.run_fix(org, uuid.UUID(fid)) == "READY"
    n = len(store.objects)
    assert await fix_task.run_fix(org, uuid.UUID(fid)) == "READY" and len(store.objects) == n


async def test_isolation_kinds_and_the_flag(client):
    org, user, _ = await make_org(plan="GROWTH")
    other, ouser, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    from .test_documents import office_zip

    word = await uploaded(client, org, user, "a.docx", office_zip())
    assert await scan(org, word) == "CLEAN"
    assert (await client.get(f"/documents/{word}/fix", headers=h)).json()[
        "code"
    ] == "unsupported_kind"
    did = await uploaded(client, org, user, "a.pdf", pdf_bytes())
    assert await scan(org, did) == "CLEAN"
    oh = auth(other, ouser)
    for call in (
        client.get(f"/documents/{did}/fix", headers=oh),
        client.put(f"/documents/{did}/fix", headers=oh, json={"language": "en"}),
        client.post(f"/documents/{did}/fix/build", headers=oh),
    ):
        assert (await call).status_code == 404
    await put_setting("flags", Scope.ORG, str(org), documents=False)
    assert (await client.get(f"/documents/{did}/fix", headers=h)).json()[
        "code"
    ] == "feature_disabled"


@needs_verapdf
async def test_deleting_the_original_removes_its_plans_but_not_the_fixed_copy(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await audited(client, org, user, defective_pdf())
    await client.put(f"/documents/{did}/fix", headers=h, json={"language": "en"})
    fid = (await client.post(f"/documents/{did}/fix/build", headers=h)).json()["id"]
    assert await fix_task.run_fix(org, uuid.UUID(fid)) == "READY"
    copy_id = (await client.get(f"/documents/{did}/fix", headers=h)).json()["fix"][
        "result_document_id"
    ]
    assert (await client.delete(f"/documents/{did}", headers=h)).status_code == 204
    assert await sql("SELECT 1 FROM document_fixes WHERE organization_id=$1", org) == []
    assert (
        await client.get(f"/documents/{copy_id}/download", headers=h)
    ).status_code == 200  # the copy is its own file
    assert (
        await client.delete(f"/documents/{copy_id}", headers=h)
    ).status_code == 204 and store.objects == {}


@needs_verapdf
async def test_the_sweepers_requeue_stuck_builds_and_settle_orphaned_reservations(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await audited(client, org, user, defective_pdf())
    await client.put(f"/documents/{did}/fix", headers=h, json={"language": "en"})
    fid = (await client.post(f"/documents/{did}/fix/build", headers=h)).json()["id"]
    store.sent.clear()
    await document_fixes.requeue_stale_fixes()
    assert store.sent == []
    await sql(
        "UPDATE document_fixes SET updated_at = now() - interval '10 minutes' WHERE id=$1",
        uuid.UUID(fid),
    )
    await document_fixes.requeue_stale_fixes()
    assert ("docs.build_fix", [str(org), fid], "docs") in store.sent
    # a build that finished READY but crashed before settling is charged by the sweeper
    await sql("UPDATE document_fixes SET status='READY' WHERE id=$1", uuid.UUID(fid))
    await sql(
        "UPDATE usage_reservations SET created_at = now() - interval '2 hours' WHERE organization_id=$1 AND job_id=$2",
        org,
        fid,
    )
    from a11y_core import document_audits

    out = await document_audits.sweep_audit_reservations()
    assert out["committed"] >= 1 and await reservation(org, fid) == "COMMITTED"
    assert (
        documents and clean_pdf and scanned_pdf and row
    )  # (shared helpers imported for the suite)
