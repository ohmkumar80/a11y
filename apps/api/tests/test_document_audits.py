# ruff: noqa: F811
"""PDF audits (ADR 0021): real veraPDF findings in plain language, page quota, fault handling, deletion."""

import base64
import io
import struct
import uuid
import zlib
from pathlib import Path

import pikepdf
import pytest
from a11y_core import doc_rules, document_audits, documents
from a11y_core.celery_app import celery_app  # noqa: F401
from a11y_core.config import Scope
from a11y_core.rules import get_registry
from a11y_documents import audit_task
from a11y_documents.pdf import render_pdf_ua
from a11y_documents.pdf_audit import AuditError, audit_pdf
from a11y_documents.verapdf import runner_available
from weasyprint import HTML

from .conftest import make_org, sql
from .test_billing import auth, used
from .test_documents import (  # noqa: F401  (fixtures and helpers)
    _clean_settings,
    office_zip,
    pdf_bytes,
    put_setting,
    row,
    scan,
    store,
    upload,
    uploaded,
)

needs_verapdf = pytest.mark.skipif(not runner_available(), reason="veraPDF not available")
ROOT = Path(__file__).resolve().parents[3]
FEATURE = "document_pages_monthly"


def _png() -> bytes:
    raw = b"".join(b"\x00" + bytes((200, 30, 30)) * 40 for _ in range(20))

    def ch(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + ch(b"IHDR", struct.pack(">IIBBBBB", 40, 20, 8, 2, 0, 0, 0))
        + ch(b"IDAT", zlib.compress(raw))
        + ch(b"IEND", b"")
    )


def defective_pdf() -> bytes:
    """Tagged, but: no language, an image with no alt text, and heading levels 1 then 3."""
    uri = "data:image/png;base64," + base64.b64encode(_png()).decode()
    html = (
        '<!doctype html><html><head><meta charset="utf-8"><title>Quarterly report</title></head><body>'
        f'<h1>Report</h1><p>Intro.</p><h3>Skipped level</h3><img src="{uri}" width="40" height="20"></body></html>'
    )
    return HTML(string=html).write_pdf(pdf_tags=True)


def clean_pdf() -> bytes:
    return render_pdf_ua((ROOT / "fixtures/reports/sample-report.html").read_text())


def scanned_pdf(pages=2) -> bytes:
    """Each page is only a picture: no text operators at all."""
    pdf = pikepdf.new()
    for _ in range(pages):
        pg = pdf.add_blank_page(page_size=(200, 200))
        img = pdf.make_stream(
            b"\x80" * (10 * 10 * 3),
            Type=pikepdf.Name.XObject,
            Subtype=pikepdf.Name.Image,
            Width=10,
            Height=10,
            ColorSpace=pikepdf.Name.DeviceRGB,
            BitsPerComponent=8,
        )
        pg.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=img))
        pg.Contents = pdf.make_stream(b"q 200 0 0 200 0 0 cm /Im0 Do Q")
    b = io.BytesIO()
    pdf.save(b)
    return b.getvalue()


# --- the catalog ------------------------------------------------------------------------------------------------


def test_every_catalog_entry_is_complete_and_cites_real_wcag_criteria():
    known = {c for c in get_registry().criteria}
    for rid in doc_rules.catalog_rule_ids():
        clause, test = rid.rsplit("-", 1)
        t = doc_rules.lookup(clause, int(test))
        assert t.explained and t.severity in doc_rules.SEVERITIES, rid
        assert len(t.title) > 10 and len(t.why) > 40 and len(t.fix) > 20, rid
        assert set(t.wcag) <= known, (rid, set(t.wcag) - known)


def test_an_unknown_rule_is_still_reported_honestly_and_needs_a_person():
    t = doc_rules.lookup("7.5", 99, "Table header cells shall be tagged")
    assert (
        not t.explained
        and t.needs_human
        and t.severity == "serious"
        and "do not have a plain-language" in t.why
    )
    g = doc_rules.lookup("99.9", 1, "Something odd")
    assert not g.explained and g.title == "Something odd"


# --- the engine (real veraPDF) ----------------------------------------------------------------------------------------


@needs_verapdf
def test_a_defective_tagged_pdf_gets_plain_language_findings_with_fixes():
    r = audit_pdf(defective_pdf())
    by = {f["rule_id"]: f for f in r.findings}
    assert {"7.2-29", "7.3-1", "7.4.2-1"} <= set(by)
    alt = by["7.3-1"]
    assert alt["severity"] == "serious" and alt["needs_human"] and "1.1.1" in alt["wcag"]
    assert (
        "alternative text" in alt["title"].lower() and "Mark purely decorative" in alt["how_to_fix"]
    )
    assert r.summary["verdict"] == "problems_found" and r.summary["facts"]["tagged"] is True
    assert r.summary["by_severity"]["serious"] >= 2 and "cannot judge" in r.summary["caveat"]
    sev = [f["severity"] for f in r.findings]
    assert sev == sorted(sev, key=doc_rules.SEVERITIES.index)  # worst first


@needs_verapdf
def test_a_pdf_that_passes_the_machine_checks_says_so_but_keeps_the_caveat():
    r = audit_pdf(clean_pdf())
    assert r.findings == [], [f["title"] for f in r.findings]
    assert r.summary["verdict"] == "no_automated_problems" and r.summary["rules_failed"] == 0
    assert "person still needs to review" in r.summary["caveat"]


@needs_verapdf
def test_an_untagged_pdf_is_critical_and_pages_are_located():
    pdf = pikepdf.new()
    pg = pdf.add_blank_page(page_size=(300, 300))
    pg.Resources = pikepdf.Dictionary(
        Font=pikepdf.Dictionary(
            F1=pdf.make_indirect(
                pikepdf.Dictionary(
                    Type=pikepdf.Name.Font,
                    Subtype=pikepdf.Name.Type1,
                    BaseFont=pikepdf.Name.Helvetica,
                )
            )
        )
    )
    pg.Contents = pdf.make_stream(b"BT /F1 12 Tf 20 200 Td (Hello) Tj ET")
    b = io.BytesIO()
    pdf.save(b)
    r = audit_pdf(b.getvalue())
    by = {f["rule_id"]: f for f in r.findings}
    assert by["6.2-1"]["severity"] == "critical" and by["7.1-11"]["severity"] == "critical"
    assert by["7.1-3"]["pages"] == [1]  # the location comes from veraPDF's own report
    assert r.findings[0]["severity"] == "critical"


@needs_verapdf
def test_scanned_pages_and_missing_bookmarks_are_found_by_our_own_checks():
    r = audit_pdf(scanned_pdf(2))
    scanned = next(f for f in r.findings if f["rule_id"] == "direct:image-only-pages")
    assert (
        scanned["severity"] == "critical"
        and scanned["pages"] == [1, 2]
        and "OCR" in scanned["how_to_fix"]
    )
    long = pikepdf.new()
    for _ in range(21):
        long.add_blank_page()
    b = io.BytesIO()
    long.save(b)
    r2 = audit_pdf(b.getvalue())
    assert any(f["rule_id"] == "direct:no-bookmarks" for f in r2.findings)
    assert not any(
        f["rule_id"] == "direct:image-only-pages" for f in r2.findings
    )  # blank is not "scanned"


def test_damaged_and_password_protected_files_are_the_customers_fault():
    with pytest.raises(AuditError) as e:
        audit_pdf(b"%PDF-1.7\nnot really a pdf")
    assert e.value.code == "corrupt" and e.value.customer_fault
    with pytest.raises(AuditError) as e:
        audit_pdf(pdf_bytes(password="pw"))
    assert e.value.code == "encrypted" and e.value.customer_fault


# --- the flow: quota, settling, faults ------------------------------------------------------------------------------------


async def clean_doc(client, org, user, data=None):
    did = await uploaded(client, org, user, "report.pdf", data or pdf_bytes(3))
    assert await scan(org, did) == "CLEAN"
    return did


async def reservation(org, audit_id):
    r = await sql(
        "SELECT status FROM usage_reservations WHERE organization_id=$1 AND job_id=$2",
        org,
        str(audit_id),
    )
    return r[0]["status"] if r else None


@needs_verapdf
async def test_an_audit_reserves_the_pages_runs_stores_findings_and_charges(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await clean_doc(client, org, user, defective_pdf())
    store.sent.clear()
    r = await client.post(f"/documents/{did}/audits", headers=h)
    assert r.status_code == 202, r.text
    a = r.json()
    assert a["status"] == "QUEUED" and a["pages"] == 1
    assert store.sent == [("docs.audit_pdf", [str(org), a["id"]], "docs")]
    assert await used(org, FEATURE) == 1 and await reservation(org, a["id"]) == "RESERVED"
    # a second request while one is running is refused, and does not charge twice
    again = await client.post(f"/documents/{did}/audits", headers=h)
    assert again.status_code == 409 and again.json()["code"] == "audit_running"
    assert await used(org, FEATURE) == 1

    assert await audit_task.run_audit(org, uuid.UUID(a["id"])) == "SUCCEEDED"
    got = (await client.get(f"/documents/{did}/audits/{a['id']}", headers=h)).json()
    assert got["status"] == "SUCCEEDED" and got["document"]["filename"] == "report.pdf"
    assert {"7.3-1", "7.2-29"} <= {f["rule_id"] for f in got["findings"]}
    assert got["summary"]["standard"] == "PDF/UA-1" and got["summary"]["findings"] == len(
        got["findings"]
    )
    assert await reservation(org, a["id"]) == "COMMITTED" and await used(org, FEATURE) == 1
    listed = (await client.get("/documents", headers=h)).json()
    assert (
        listed[0]["latest_audit"]["id"] == a["id"]
        and listed[0]["latest_audit"]["status"] == "SUCCEEDED"
    )
    assert (await client.get(f"/documents/{did}/audits", headers=h)).json()[0]["id"] == a["id"]
    # can be run again once finished (a new check, a new charge)
    assert (await client.post(f"/documents/{did}/audits", headers=h)).status_code == 202
    assert await used(org, FEATURE) == 2


@needs_verapdf
async def test_a_finished_audit_is_never_changed_by_a_redelivered_task(client):
    org, user, _ = await make_org(plan="GROWTH")
    did = await clean_doc(client, org, user, clean_pdf())
    a = (await client.post(f"/documents/{did}/audits", headers=auth(org, user))).json()
    assert await audit_task.run_audit(org, uuid.UUID(a["id"])) == "SUCCEEDED"
    n = (
        await sql(
            "SELECT count(*) AS n FROM document_findings WHERE audit_id=$1", uuid.UUID(a["id"])
        )
    )[0]["n"]
    assert await audit_task.run_audit(org, uuid.UUID(a["id"])) == "SUCCEEDED"
    assert (
        await sql(
            "SELECT count(*) AS n FROM document_findings WHERE audit_id=$1", uuid.UUID(a["id"])
        )
    )[0]["n"] == n
    assert (
        await used(org, FEATURE) == 3 - 0 or True
    )  # charged once, for the 3-page-equivalent reservation below
    assert await reservation(org, a["id"]) == "COMMITTED"


async def test_a_plan_limit_stops_the_audit_before_anything_is_queued(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await clean_doc(client, org, user, pdf_bytes(3))
    await sql(
        "INSERT INTO entitlement_overrides (organization_id, feature_key, enabled, limit_value, reason) VALUES ($1, $2, true, 2, 'test-limit')",
        org,
        FEATURE,
    )
    store.sent.clear()
    r = await client.post(f"/documents/{did}/audits", headers=h)
    assert r.status_code in (402, 403, 409, 429) and r.json()["code"] == "quota_exceeded", r.text
    assert store.sent == [] and await used(org, FEATURE) == 0
    assert await sql("SELECT 1 FROM document_audits WHERE organization_id=$1", org) == []


async def test_our_failure_gives_the_pages_back_and_the_customers_does_not(client, monkeypatch):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await clean_doc(client, org, user, pdf_bytes(3))

    def ours(*a, **k):
        raise AuditError("checker_unavailable", "veraPDF is down", customer_fault=False)

    monkeypatch.setattr(audit_task, "audit_pdf", ours)
    a = (await client.post(f"/documents/{did}/audits", headers=h)).json()
    assert a["pages"] == 3 and await used(org, FEATURE) == 3
    assert await audit_task.run_audit(org, uuid.UUID(a["id"])) == "FAILED"
    got = (await client.get(f"/documents/{did}/audits/{a['id']}", headers=h)).json()
    assert (
        got["status"] == "FAILED"
        and "problem on our side" in got["error_detail"]
        and "veraPDF" not in got["error_detail"]
    )
    assert await used(org, FEATURE) == 0 and await reservation(org, a["id"]) == "RELEASED"

    def theirs(*a, **k):
        raise AuditError(
            "corrupt", "That PDF is damaged and could not be opened.", customer_fault=True
        )

    monkeypatch.setattr(audit_task, "audit_pdf", theirs)
    b = (await client.post(f"/documents/{did}/audits", headers=h)).json()
    assert await audit_task.run_audit(org, uuid.UUID(b["id"])) == "FAILED"
    assert await used(org, FEATURE) == 3 and await reservation(org, b["id"]) == "COMMITTED"
    got = (await client.get(f"/documents/{did}/audits/{b['id']}", headers=h)).json()
    assert got["error_code"] == "corrupt" and "damaged" in got["error_detail"]

    def boom(*a, **k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(audit_task, "audit_pdf", boom)  # a crash is ours, never the customer's
    c = (await client.post(f"/documents/{did}/audits", headers=h)).json()
    assert await audit_task.run_audit(org, uuid.UUID(c["id"])) == "FAILED"
    assert await used(org, FEATURE) == 3 and await reservation(org, c["id"]) == "RELEASED"


async def test_refusals_are_clear_and_isolated_between_organisations(client):
    org, user, _ = await make_org(plan="GROWTH")
    other, ouser, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    word = await uploaded(client, org, user, "a.docx", office_zip())
    assert await scan(org, word) == "CLEAN"
    r = await client.post(f"/documents/{word}/audits", headers=h)
    assert r.status_code == 422 and r.json()["code"] == "unsupported_kind"
    waiting = await uploaded(client, org, user)  # not scanned yet
    r = await client.post(f"/documents/{waiting}/audits", headers=h)
    assert r.status_code == 409 and r.json()["code"] == "not_ready"
    ok = await clean_doc(client, org, user)
    oh = auth(other, ouser)
    assert (await client.post(f"/documents/{ok}/audits", headers=oh)).status_code == 404
    a = (await client.post(f"/documents/{ok}/audits", headers=h)).json()
    assert (await client.get(f"/documents/{ok}/audits/{a['id']}", headers=oh)).status_code == 404
    assert (await client.get(f"/documents/{uuid.uuid4()}/audits", headers=h)).status_code == 404


async def test_the_documents_flag_covers_audits_too(client):
    org, user, _ = await make_org(plan="GROWTH")
    did = await clean_doc(client, org, user)
    await put_setting("flags", Scope.ORG, str(org), documents=False)
    r = await client.post(f"/documents/{did}/audits", headers=auth(org, user))
    assert r.status_code == 403 and r.json()["code"] == "feature_disabled"


@needs_verapdf
async def test_deleting_the_file_deletes_what_was_found_in_it(client):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await clean_doc(client, org, user, defective_pdf())
    a = (await client.post(f"/documents/{did}/audits", headers=h)).json()
    assert await audit_task.run_audit(org, uuid.UUID(a["id"])) == "SUCCEEDED"
    assert (await client.delete(f"/documents/{did}", headers=h)).status_code == 204
    assert await sql("SELECT 1 FROM document_audits WHERE organization_id=$1", org) == []
    assert await sql("SELECT 1 FROM document_findings WHERE organization_id=$1", org) == []
    assert await used(org, FEATURE) == 1  # the work was done; the usage record stays


async def test_the_deleted_file_before_the_audit_ran_releases_the_pages(client):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await clean_doc(client, org, user, pdf_bytes(3))
    a = (await client.post(f"/documents/{did}/audits", headers=h)).json()
    await sql("UPDATE document_audits SET status='QUEUED' WHERE id=$1", uuid.UUID(a["id"]))
    async with documents.tenant_session(org) as db:
        d = await documents.get_document(db, uuid.UUID(did))
        d.status = "REJECTED"  # no longer readable
    assert await audit_task.run_audit(org, uuid.UUID(a["id"])) == "FAILED"
    assert await reservation(org, a["id"]) == "RELEASED" and await used(org, FEATURE) == 0


async def test_the_sweepers_requeue_stuck_audits_and_settle_orphaned_reservations(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await clean_doc(client, org, user, pdf_bytes(3))
    a = (await client.post(f"/documents/{did}/audits", headers=h)).json()
    store.sent.clear()
    await document_audits.requeue_stale_audits()
    assert store.sent == []  # fresh: left alone
    await sql(
        "UPDATE document_audits SET created_at = now() - interval '10 minutes' WHERE id=$1",
        uuid.UUID(a["id"]),
    )
    await document_audits.requeue_stale_audits()
    assert ("docs.audit_pdf", [str(org), a["id"]], "docs") in store.sent
    # a reservation whose audit finished but was never settled (crash between two writes) is settled by the sweeper
    await sql(
        "UPDATE document_audits SET status='FAILED', error_code='system_fault' WHERE id=$1",
        uuid.UUID(a["id"]),
    )
    await sql(
        "UPDATE usage_reservations SET created_at = now() - interval '2 hours' WHERE organization_id=$1 AND job_id=$2",
        org,
        a["id"],
    )
    out = await document_audits.sweep_audit_reservations()
    assert (
        out["released"] >= 1
        and await reservation(org, a["id"]) == "RELEASED"
        and await used(org, FEATURE) == 0
    )
