"""Reports end to end: real scan -> report job (real renderers and gates) -> download; VPAT sign-off flow."""

import csv
import hashlib
import io
import uuid

import pikepdf
import pytest
from a11y_core.celery_app import celery_app  # noqa: F401
from a11y_documents.csv_export import check_csv
from a11y_documents.docx_check import check_docx
from a11y_documents.tasks import GateFailed, render_report
from a11y_documents.verapdf import VeraPdfUnavailable, runner_available, validate_pdf_ua
from a11y_web_audit.tasks import run_scan

from .conftest import make_org, sql
from .test_billing import auth
from .test_scans_api import FAST, _cfg_reset, create, dev, high_ports, site  # noqa: F401, F811  (fixtures)

needs_verapdf = pytest.mark.skipif(not runner_available(), reason="veraPDF not available")


async def add_member(org) -> uuid.UUID:
    """A STANDARD_USER in an existing organisation."""
    from a11y_core.db import tenant_session
    from a11y_core.models import User

    from a11y_api.security import hash_password

    uid = uuid.uuid4()
    async with tenant_session(org) as db:
        db.add(
            User(
                id=uid,
                organization_id=org,
                email=f"m-{uid.hex[:8]}@example.com",
                hashed_password=hash_password("correct horse battery"),
                role="STANDARD_USER",
            )
        )
    return uid


async def finished_scan(client, site, org, user, standards=("WCAG_2_2_AA",), page="bad.html"):
    h = auth(org, user)
    sid = uuid.UUID(
        (await create(client, h, f"{site}/{page}", standards=list(standards))).json()["id"]
    )
    assert await run_scan(org, sid, opts_override=FAST) == "SUCCEEDED"
    return sid, h


async def make_report(client, h, sid, kind, **kw):
    r = await client.post(f"/scans/{sid}/reports", headers=h, json={"kind": kind, **kw})
    assert r.status_code == 202, r.text
    return uuid.UUID(r.json()["id"]), r.json()


# --- audit reports ----------------------------------------------------------------------------------------------


@needs_verapdf
async def test_audit_pdf_is_queued_rendered_gated_and_downloadable(client, site, dev):
    org, user, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    dev.clear()
    rid, body = await make_report(client, h, sid, "audit_pdf")
    assert body["status"] == "QUEUED" and dev == [
        ("docs.render_report", [str(org), str(rid)], "docs")
    ]  # on the documents queue
    assert (
        await client.get(f"/reports/{rid}/download", headers=h)
    ).status_code == 409  # not ready: nothing to download yet

    assert await render_report(org, rid) == "READY"
    r = (await client.get(f"/reports/{rid}", headers=h)).json()
    assert (
        r["status"] == "READY"
        and r["validation"]["gate"] == "veraPDF PDF/UA-1"
        and r["validation"]["passed"] is True
    )
    assert r["template_version"].startswith("audit_report@v1+") and r["size_bytes"] > 5000

    d = await client.get(f"/reports/{rid}/download", headers=h)
    assert (
        d.status_code == 200
        and d.headers["content-type"] == "application/pdf"
        and d.content.startswith(b"%PDF")
    )
    assert (
        d.headers["cache-control"] == "private, no-store"
        and d.headers["x-content-type-options"] == "nosniff"
    )
    assert d.headers["content-disposition"].startswith(
        'attachment; filename="a11y-audit-127.0.0.1-'
    )
    assert (
        hashlib.sha256(d.content).hexdigest()
        == (await sql("SELECT sha256 FROM reports WHERE id=$1", rid))[0]["sha256"]
    )
    assert validate_pdf_ua(d.content).compliant  # independent re-check of the delivered bytes
    pdf = pikepdf.open(io.BytesIO(d.content))
    assert "Accessibility audit report" in str(pdf.docinfo.Title) and str(pdf.Root.Lang) == "en"


async def test_audit_docx_and_csv_pass_their_gates(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    dx, _ = await make_report(client, h, sid, "audit_docx")
    cv, _ = await make_report(client, h, sid, "audit_csv")
    assert await render_report(org, dx) == "READY" and await render_report(org, cv) == "READY"
    docx = await client.get(f"/reports/{dx}/download", headers=h)
    assert (
        docx.headers["content-type"].endswith("wordprocessingml.document")
        and check_docx(docx.content) == []
    )
    c = await client.get(f"/reports/{cv}/download", headers=h)
    assert c.headers["content-type"].startswith("text/csv") and check_csv(c.content) == []
    rows = list(csv.DictReader(io.StringIO(c.content.decode("utf-8-sig"))))
    n = (await client.get(f"/scans/{sid}/findings?kind=violation&limit=200", headers=h)).json()[
        "total"
    ]
    assert (
        len([r for r in rows if r["type"] == "failure"]) == n
    )  # the CSV lists every failure the app shows
    assert {r["severity"] for r in rows} >= {"critical", "serious"} and rows[0][
        "severity"
    ] == "critical"
    img = next(r for r in rows if r["rule"] == "image-alt")
    assert (
        img["clauses"] == "WCAG 1.1.1"
        and img["engines_agreeing"]
        and img["page"].endswith("/bad.html")
    )


async def test_csv_uses_the_standard_s_clause_numbers_and_re_filters(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    rid, _ = await make_report(client, h, sid, "audit_csv", standard="EU_EAA_EN_301_549")
    await render_report(org, rid)
    rows = list(
        csv.DictReader(
            io.StringIO(
                (await client.get(f"/reports/{rid}/download", headers=h)).content.decode(
                    "utf-8-sig"
                )
            )
        )
    )
    assert any(r["clauses"] == "9.1.1.1" for r in rows) and all(
        r["standard"] == "EU_EAA_EN_301_549" for r in rows
    )


async def test_same_request_reuses_the_report_regenerate_makes_a_new_one(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    a, _ = await make_report(client, h, sid, "audit_csv")
    b, body = await make_report(client, h, sid, "audit_csv")
    assert a == b and body["reused"] is True
    c, body = await make_report(client, h, sid, "audit_csv", regenerate=True)
    assert c != a and body["reused"] is False


async def test_finished_reports_are_never_rewritten_by_a_redelivered_task(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    rid, _ = await make_report(client, h, sid, "audit_csv")
    await render_report(org, rid)
    first = (await sql("SELECT sha256, finished_at FROM reports WHERE id=$1", rid))[0]
    assert await render_report(org, rid) == "READY"
    assert (await sql("SELECT sha256, finished_at FROM reports WHERE id=$1", rid))[0] == first


async def test_a_file_that_fails_its_gate_is_never_stored_or_offered(client, site, monkeypatch):
    import a11y_documents.tasks as tasks

    org, user, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    rid, _ = await make_report(client, h, sid, "audit_pdf")

    def failing(html):
        raise GateFailed(["7.3#1 x1"])

    monkeypatch.setattr(tasks, "_pdf", failing)
    assert await render_report(org, rid) == "FAILED"
    r = (await client.get(f"/reports/{rid}", headers=h)).json()
    assert (
        r["status"] == "FAILED"
        and r["error_code"] == "validation_failed"
        and "did not deliver it" in r["error_detail"]
    )
    assert "7.3" not in r["error_detail"]  # internals are not shown to the customer
    assert (await sql("SELECT content FROM reports WHERE id=$1", rid))[0]["content"] is None
    assert (await client.get(f"/reports/{rid}/download", headers=h)).status_code == 409


async def test_validator_down_and_crashes_fail_cleanly(client, site, monkeypatch):
    import a11y_documents.tasks as tasks

    org, user, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    a, _ = await make_report(client, h, sid, "audit_pdf")

    def down(html):
        raise VeraPdfUnavailable("no docker")

    monkeypatch.setattr(tasks, "_pdf", down)
    await render_report(org, a)
    assert (await client.get(f"/reports/{a}", headers=h)).json()[
        "error_code"
    ] == "validator_unavailable"
    b, _ = await make_report(client, h, sid, "audit_docx")

    async def boom(*args, **kw):
        raise RuntimeError("template exploded")

    monkeypatch.setattr(tasks, "load_audit_data", boom)
    assert await render_report(org, b) == "FAILED"
    assert (await client.get(f"/reports/{b}", headers=h)).json()["error_code"] == "system_error"


async def test_validation_errors_and_tenant_isolation(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    other, ouser, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    queued = uuid.UUID(
        (await create(client, h, f"{site}/good.html")).json()["id"]
    )  # not run: still QUEUED
    assert (
        await client.post(f"/scans/{queued}/reports", headers=h, json={"kind": "audit_pdf"})
    ).json()["code"] == "scan_not_finished"
    assert (
        await client.post(
            f"/scans/{sid}/reports", headers=h, json={"kind": "audit_pdf", "standard": "NOPE"}
        )
    ).status_code == 422
    assert (
        await client.post(f"/scans/{sid}/reports", headers=h, json={"kind": "exe"})
    ).status_code == 422
    rid, _ = await make_report(client, h, sid, "audit_csv")
    await render_report(org, rid)
    ho = auth(other, ouser)
    for url in (f"/reports/{rid}", f"/reports/{rid}/download"):
        assert (await client.get(url, headers=ho)).status_code == 404
    assert (await client.get(f"/scans/{sid}/reports", headers=ho)).status_code == 404
    assert (
        await client.post(f"/scans/{sid}/reports", headers=ho, json={"kind": "audit_csv"})
    ).status_code == 404
    assert [x["id"] for x in (await client.get(f"/scans/{sid}/reports", headers=h)).json()] == [
        str(rid)
    ]


async def test_too_many_reports_in_flight_are_refused(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    kinds = ["audit_pdf", "audit_docx", "audit_csv"]
    stds = ["WCAG_2_2_AA", "WCAG_2_1_AA"]
    sent = [
        await client.post(f"/scans/{sid}/reports", headers=h, json={"kind": k, "standard": s})
        for k in kinds
        for s in stds
    ]
    assert (
        [r.status_code for r in sent[:5]] == [202] * 5
        and sent[5].status_code == 429
        and sent[5].json()["code"] == "too_many_reports"
    )


# --- VPAT ----------------------------------------------------------------------------------------------------------


async def make_vpat(client, h, sid, **kw):
    r = await client.post(f"/scans/{sid}/vpat", headers=h, json=kw)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_vpat_defaults_never_overstate_what_automation_proved(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    vid = await make_vpat(client, h, sid)
    v = (await client.get(f"/vpats/{vid}", headers=h)).json()
    rows = {c["id"]: c for c in v["criteria"]}
    assert v["total"] == 55 and v["status"] == "DRAFT" and v["mapping_review"] == "draft"
    assert not any(
        c["conformance"] == "Supports" for c in v["criteria"]
    )  # automation can never prove support
    assert (
        rows["1.1.1"]["conformance"] == "Does Not Support" and "failure" in rows["1.1.1"]["remarks"]
    )  # failures on the only page scanned
    assert (
        rows["1.1.1"]["source"] == "automated"
        and rows["1.1.1"]["failing_pages"] == 1
        and rows["1.1.1"]["scanned_pages"] == 1
    )
    assert (
        rows["1.2.5"]["conformance"] == "Not Evaluated"
        and "cannot evaluate" in rows["1.2.5"]["remarks"]
    )
    clean = next(c for c in v["criteria"] if c["automated_check_exists"] and not c["failures"])
    assert (
        clean["conformance"] == "Not Evaluated" and "still evaluate it" in clean["remarks"]
    )  # no issue found != supported
    assert v["not_evaluated"] > 20 and v["signoff"] is None
    assert await make_vpat(client, h, sid) == vid  # idempotent per (scan, standard, edition)
    assert (
        await client.post(f"/scans/{sid}/vpat", headers=h, json={"edition": "INT"})
    ).status_code == 201


async def test_partial_when_only_some_pages_fail(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    await sql(
        "INSERT INTO verified_domains (id, organization_id, host, token, verified_at, method) VALUES (gen_random_uuid(), $1, '127.0.0.1', 't', now(), 'file')",
        org,
    )
    sid = uuid.UUID(
        (await create(client, h, f"{site}/index.html", mode="crawl", max_pages=3)).json()["id"]
    )
    assert await run_scan(org, sid, opts_override=FAST) == "SUCCEEDED"
    vid = await make_vpat(client, h, sid)
    rows = {c["id"]: c for c in (await client.get(f"/vpats/{vid}", headers=h)).json()["criteria"]}
    assert (
        rows["1.1.1"]["conformance"] == "Partially Supports"
        and rows["1.1.1"]["scanned_pages"] == 3
        and 0 < rows["1.1.1"]["failing_pages"] < 3
    )


async def test_vpat_editing_rules_and_roles(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    vid = await make_vpat(client, h, sid)
    patch = lambda body, hh=h: client.patch(f"/vpats/{vid}", headers=hh, json=body)  # noqa: E731
    assert (
        await patch({"criteria": [{"id": "9.9.9", "conformance": "Supports"}]})
    ).status_code == 422
    assert (await patch({"criteria": [{"id": "1.2.5", "conformance": "Maybe"}]})).status_code == 422
    r = await patch(
        {"criteria": [{"id": "1.2.5", "conformance": "Partially Supports", "remarks": ""}]}
    )
    assert r.status_code == 422 and "explain why" in r.json()["detail"]
    ok = (
        await patch(
            {
                "criteria": [
                    {
                        "id": "1.2.5",
                        "conformance": "Supports",
                        "remarks": "Audio description is provided for all videos.",
                    }
                ],
                "product": {
                    "name": "Acme Portal",
                    "version": "4.2",
                    "contact": "a11y@acme.example",
                },
            }
        )
    ).json()
    c = next(x for x in ok["criteria"] if x["id"] == "1.2.5")
    assert (c["conformance"], c["source"]) == ("Supports", "manual") and ok["product"][
        "name"
    ] == "Acme Portal"
    # overriding an automated failure to "Supports" needs a reason, and sign-off refuses a missing one
    over = await patch({"criteria": [{"id": "1.1.1", "conformance": "Supports", "remarks": ""}]})
    assert over.status_code == 200 and any(
        "automated tests found failures" in p for p in over.json()["problems"]
    )
    assert (
        await client.post(
            f"/vpats/{vid}/signoff",
            headers=h,
            json={"name": "A B", "role": "Lead", "confirm": True},
        )
    ).status_code == 422
    # a plain member of the SAME organisation can read the draft but not edit, sign off, export or reopen it
    mid = await add_member(org)
    hm = auth(org, mid, "STANDARD_USER")
    assert (await client.get(f"/vpats/{vid}", headers=hm)).status_code == 200
    assert (await patch({"product": {"name": "Hacked"}}, hm)).status_code == 403
    assert (
        await client.post(
            f"/vpats/{vid}/signoff",
            headers=hm,
            json={"name": "A B", "role": "Lead", "confirm": True},
        )
    ).status_code == 403
    assert (
        await client.post(f"/vpats/{vid}/export", headers=hm, json={"format": "pdf"})
    ).status_code == 403
    assert (await client.post(f"/vpats/{vid}/reopen", headers=hm)).status_code == 403
    assert (await client.post(f"/scans/{sid}/vpat", headers=hm, json={})).status_code == 403
    # ...but can generate and download audit reports
    rid, _ = await make_report(client, hm, sid, "audit_csv")
    await render_report(org, rid)
    assert (await client.get(f"/reports/{rid}/download", headers=hm)).status_code == 200
    # and another organisation cannot even see it
    other, ouser, _ = await make_org(plan="GROWTH")
    assert (await client.get(f"/vpats/{vid}", headers=auth(other, ouser))).status_code == 404


async def test_signoff_locks_the_document_and_unlocks_export(client, site, dev):
    org, user, email = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    vid = await make_vpat(client, h, sid)
    exp = lambda fmt="pdf": client.post(f"/vpats/{vid}/export", headers=h, json={"format": fmt})  # noqa: E731
    r = await exp()
    assert r.status_code == 409 and r.json()["code"] == "vpat_not_signed_off"
    assert (
        await client.post(
            f"/vpats/{vid}/signoff",
            headers=h,
            json={"name": "Priya N", "role": "Accessibility lead", "confirm": False},
        )
    ).status_code == 422
    so = await client.post(
        f"/vpats/{vid}/signoff",
        headers=h,
        json={"name": "Priya N", "role": "Accessibility lead", "confirm": True},
    )
    assert (
        so.status_code == 200
        and so.json()["status"] == "SIGNED_OFF"
        and so.json()["signoff"]["name"] == "Priya N"
        and so.json()["signoff"]["user_id"] == str(user)
    )
    audit = await sql(
        "SELECT detail FROM audit_log WHERE organization_id=$1 AND action='vpat.signed_off'", org
    )
    assert len(audit) == 1
    assert (
        await client.patch(
            f"/vpats/{vid}",
            headers=h,
            json={"criteria": [{"id": "1.2.5", "conformance": "Not Applicable"}]},
        )
    ).json()["code"] == "vpat_locked"
    assert (
        await client.post(
            f"/vpats/{vid}/signoff", headers=h, json={"name": "X Y", "role": "Z Z", "confirm": True}
        )
    ).status_code == 409
    dev.clear()
    ok = await exp("docx")
    assert ok.status_code == 202 and dev[0][0] == "docs.render_report"
    # reopening clears the sign-off and blocks export again
    re_ = (await client.post(f"/vpats/{vid}/reopen", headers=h)).json()
    assert re_["status"] == "DRAFT" and re_["signoff"] is None
    assert (await exp()).status_code == 409
    assert (
        len(
            await sql(
                "SELECT 1 FROM audit_log WHERE organization_id=$1 AND action='vpat.reopened'", org
            )
        )
        == 1
    )


@needs_verapdf
async def test_vpat_pdf_and_docx_are_produced_only_from_a_signed_vpat(client, site):
    org, user, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    vid = await make_vpat(client, h, sid)
    await client.patch(f"/vpats/{vid}", headers=h, json={"product": {"name": "Acme Portal"}})
    await client.post(
        f"/vpats/{vid}/signoff",
        headers=h,
        json={"name": "Priya N", "role": "Accessibility lead", "confirm": True},
    )
    pdf_id = uuid.UUID(
        (await client.post(f"/vpats/{vid}/export", headers=h, json={"format": "pdf"})).json()["id"]
    )
    docx_id = uuid.UUID(
        (await client.post(f"/vpats/{vid}/export", headers=h, json={"format": "docx"})).json()["id"]
    )
    assert (
        await render_report(org, pdf_id) == "READY" and await render_report(org, docx_id) == "READY"
    )
    pdf = await client.get(f"/reports/{pdf_id}/download", headers=h)
    assert (
        validate_pdf_ua(pdf.content).compliant
        and "a11y-vpat-" in pdf.headers["content-disposition"]
    )
    dx = await client.get(f"/reports/{docx_id}/download", headers=h)
    assert check_docx(dx.content) == [] and b"Priya N" in __import__("zipfile").ZipFile(
        io.BytesIO(dx.content)
    ).read("word/document.xml")
    assert (
        (await client.get(f"/reports/{pdf_id}", headers=h))
        .json()["template_version"]
        .startswith("vpat@v1+")
    )


async def test_rendering_a_vpat_that_is_not_signed_off_is_refused(client, site):
    """Defence in depth: even if a job is created some other way, the worker refuses an unsigned VPAT."""
    org, user, _ = await make_org(plan="GROWTH")
    sid, h = await finished_scan(client, site, org, user)
    vid = await make_vpat(client, h, sid)
    rid = uuid.uuid4()
    await sql(
        "INSERT INTO reports (id, organization_id, scan_id, vpat_id, kind, standard) VALUES ($1,$2,$3,$4,'vpat_docx','WCAG_2_2_AA')",
        rid,
        org,
        sid,
        uuid.UUID(vid),
    )
    assert await render_report(org, rid) == "FAILED"
    assert (await sql("SELECT content, error_code FROM reports WHERE id=$1", rid))[0][
        "content"
    ] is None
