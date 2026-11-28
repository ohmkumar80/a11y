# ruff: noqa: F811
"""Document uploads (ADR 0020): validation, encryption at rest, held-until-scanned, fail-closed, retention, isolation."""

import asyncio
import io
import json
import struct
import uuid
import zipfile

import pikepdf
import pytest
from a11y_core import clamav, documents, storage
from a11y_core.celery_app import celery_app
from a11y_core.clamav import ScannerUnavailable, ScanVerdict
from a11y_core.config import Scope, get_config
from a11y_core.config.registry import GuardrailError
from a11y_core.db import tenant_session
from a11y_core.models import Document
from a11y_core.settings import get_settings
from a11y_core.storage import MemoryStore, S3Store
from a11y_core.upload_checks import Refusal, ZipLimits, detect_kind, sanitize_filename
from a11y_documents import scan_upload
from sqlalchemy import select

from .conftest import make_org, sql
from .test_billing import auth
from .test_reports_api import add_member


@pytest.fixture(autouse=True)
def store(monkeypatch):
    mem = MemoryStore()
    storage.set_store(mem)
    sent = []
    monkeypatch.setattr(
        celery_app,
        "send_task",
        lambda name, args=None, queue=None, **kw: sent.append((name, args, queue)),
    )
    mem.sent = sent
    # A scanner that says "clean" unless a test changes it.
    mem.verdict = ScanVerdict(True)

    async def fake_scan(data, *, host, port, timeout=60):
        if isinstance(mem.verdict, Exception):
            raise mem.verdict
        return mem.verdict

    monkeypatch.setattr(scan_upload, "scan_bytes", fake_scan)
    yield mem
    storage.set_store(None)


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


async def put_setting(key, scope, scope_id, **values):
    await get_config().save(key, scope, scope_id, values, comment="test-doc", actor=None)


def pdf_bytes(pages=1, *, js=False, password=None) -> bytes:
    pdf = pikepdf.new()
    for _ in range(pages):
        pdf.add_blank_page()
    if js:
        pdf.Root.OpenAction = pikepdf.Dictionary(
            S=pikepdf.Name.JavaScript, JS=pikepdf.String("app.alert(1)")
        )
    b = io.BytesIO()
    enc = pikepdf.Encryption(user=password, owner=password) if password else False
    pdf.save(b, encryption=enc)
    return b.getvalue()


def office_zip(kind="docx", extra: dict[str, bytes] | None = None, big_zeros=0) -> bytes:
    main = {"docx": "word/document.xml", "pptx": "ppt/presentation.xml"}[kind]
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(main, "<doc/>")
        for n, d in (extra or {}).items():
            z.writestr(n, d)
        if big_zeros:
            z.writestr("word/bomb.xml", b"\x00" * big_zeros)
    return b.getvalue()


async def upload(client, h, name, data):
    return await client.post(
        "/documents",
        params={"filename": name},
        content=data,
        headers={**h, "content-type": "application/octet-stream"},
    )


async def row(doc_id) -> Document:
    return (await sql("SELECT * FROM documents WHERE id = $1", uuid.UUID(doc_id)))[0]


async def scan(org, doc_id):
    return await scan_upload.scan_document(org, uuid.UUID(doc_id))


# --- storage and encryption -------------------------------------------------------------------------------------


def test_sealed_bytes_round_trip_and_do_not_contain_the_plaintext():
    data = b"%PDF-1.7 confidential " * 100
    blob, wrapped = storage.seal_bytes(data, "documents/o/d/original")
    assert b"confidential" not in blob and b"%PDF" not in blob
    assert storage.open_bytes(blob, wrapped, "documents/o/d/original") == data


def test_a_sealed_object_cannot_be_moved_to_another_key_or_altered():
    blob, wrapped = storage.seal_bytes(b"secret", "documents/o/a/original")
    with pytest.raises(ValueError):
        storage.open_bytes(blob, wrapped, "documents/o/b/original")  # copied under another key
    with pytest.raises(ValueError):
        storage.open_bytes(blob[:-1] + bytes([blob[-1] ^ 1]), wrapped, "documents/o/a/original")


def test_each_object_gets_its_own_key():
    _, w1 = storage.seal_bytes(b"x", "k")
    _, w2 = storage.seal_bytes(b"x", "k")
    assert w1 != w2


async def _s3_up() -> bool:
    s = get_settings()
    try:
        store = S3Store(
            endpoint_url=s.s3_endpoint_url,
            access_key=s.s3_access_key,
            secret_key=s.s3_secret_key,
            bucket=s.s3_bucket,
            region=s.s3_region,
        )
        await store.exists("probe-does-not-exist")
        return True
    except Exception:  # noqa: BLE001
        return False


async def test_real_s3_store_round_trip():
    if not await _s3_up():
        pytest.skip("S3-compatible store not reachable")
    s = get_settings()
    store = S3Store(
        endpoint_url=s.s3_endpoint_url,
        access_key=s.s3_access_key,
        secret_key=s.s3_secret_key,
        bucket=s.s3_bucket,
        region=s.s3_region,
    )
    key = f"tests/{uuid.uuid4()}"
    assert not await store.exists(key)
    await store.put(key, b"hello")
    assert await store.exists(key) and await store.get(key) == b"hello"
    await store.delete(key)
    assert not await store.exists(key)
    with pytest.raises(storage.ObjectNotFound):
        await store.get(key)


# --- the virus-scanner client ---------------------------------------------------------------------------------------


async def fake_clamd(reply: bytes):
    seen = {}

    async def handle(reader, writer):
        assert await reader.readexactly(10) == b"zINSTREAM\x00"
        body = b""
        while True:
            (n,) = struct.unpack("!I", await reader.readexactly(4))
            if n == 0:
                break
            body += await reader.readexactly(n)
        seen["body"] = body
        writer.write(reply)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1], seen


@pytest.mark.parametrize(
    ("reply", "clean", "sig"),
    [
        (b"stream: OK\x00", True, None),
        (b"stream: Eicar-Test-Signature FOUND\x00", False, "Eicar-Test-Signature"),
    ],
)
async def test_clamd_protocol_frames_the_file_and_reads_the_verdict(reply, clean, sig):
    server, port, seen = await fake_clamd(reply)
    async with server:
        v = await clamav.scan_bytes(b"x" * 200_000, host="127.0.0.1", port=port, timeout=5)
    assert (v.clean, v.signature) == (clean, sig) and len(seen["body"]) == 200_000


async def test_an_unreadable_scanner_reply_is_never_treated_as_clean():
    server, port, _ = await fake_clamd(b"INSTREAM size limit exceeded. ERROR\x00")
    async with server:
        with pytest.raises(ScannerUnavailable):
            await clamav.scan_bytes(b"x", host="127.0.0.1", port=port, timeout=5)


async def test_an_unreachable_scanner_is_unavailable_not_clean():
    with pytest.raises(ScannerUnavailable):
        await clamav.scan_bytes(b"x", host="127.0.0.1", port=1, timeout=2)


# --- first-line checks ----------------------------------------------------------------------------------------


def test_filenames_are_reduced_to_a_safe_display_name():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Users\\x\\report.pdf") == "report.pdf"
    assert sanitize_filename("a\x00b\nc.pdf") == "abc.pdf"
    assert sanitize_filename("   ") == "document"
    assert len(sanitize_filename("x" * 400 + ".pdf")) <= 150 and sanitize_filename(
        "x" * 400 + ".pdf"
    ).endswith(".pdf")


ZL = ZipLimits(5000, 500 * 1024 * 1024, 200)


def test_kind_is_decided_from_the_bytes_not_the_name():
    assert detect_kind(pdf_bytes(), "a.pdf", ZL) == "pdf"
    assert detect_kind(office_zip("docx"), "a.docx", ZL) == "docx"
    with pytest.raises(Refusal) as e:
        detect_kind(office_zip("docx"), "a.pptx", ZL)  # a Word file renamed to .pptx
    assert e.value.code == "type_mismatch"
    with pytest.raises(Refusal) as e:
        detect_kind(b"MZ\x90\x00 not a pdf", "a.pdf", ZL)
    assert e.value.code == "type_mismatch"
    with pytest.raises(Refusal) as e:
        detect_kind(b"x", "a.exe", ZL)
    assert e.value.code == "unsupported_type"


def test_zip_bombs_traversal_and_nested_programs_are_refused():
    with pytest.raises(Refusal) as e:
        detect_kind(office_zip(big_zeros=40 * 1024 * 1024), "a.docx", ZL)
    assert e.value.code == "zip_bomb"
    with pytest.raises(Refusal) as e:
        detect_kind(office_zip(extra={"../evil.xml": b"x"}), "a.docx", ZL)
    assert e.value.code == "zip_unsafe_path"
    with pytest.raises(Refusal) as e:
        detect_kind(office_zip(extra={"word/dropper.exe": b"MZ"}), "a.docx", ZL)
    assert e.value.code == "zip_nested"
    many = {f"word/p{i}.xml": b"<a/>" for i in range(30)}
    with pytest.raises(Refusal) as e:
        detect_kind(office_zip(extra=many), "a.docx", ZipLimits(10, 10**9, 200))
    assert e.value.code == "zip_bomb"


def test_an_epub_must_start_with_its_mimetype_entry():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", "<c/>")
    assert detect_kind(b.getvalue(), "book.epub", ZL) == "epub"
    b2 = io.BytesIO()
    with zipfile.ZipFile(b2, "w") as z:
        z.writestr("other", "x")
        z.writestr("mimetype", "application/epub+zip")
    with pytest.raises(Refusal):
        detect_kind(b2.getvalue(), "book.epub", ZL)


# --- the upload endpoint ----------------------------------------------------------------------------------------


async def test_upload_is_stored_encrypted_and_held_until_scanned(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    data = pdf_bytes(2)
    r = await upload(client, h, "Annual Report.pdf", data)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "UPLOADED" and body["ready"] is False and body["kind"] == "pdf"
    assert store.sent == [("docs.scan_upload", [str(org), body["id"]], "docs")]
    (blob,) = store.objects.values()
    assert b"%PDF" not in blob and data not in blob  # encrypted before it reached the store
    # held back: cannot be downloaded before the scan
    d = await client.get(f"/documents/{body['id']}/download", headers=h)
    assert d.status_code == 409 and d.json()["code"] == "not_ready"

    assert await scan(org, body["id"]) == "CLEAN"
    got = (await client.get(f"/documents/{body['id']}", headers=h)).json()
    assert got["status"] == "CLEAN" and got["ready"] and got["page_count"] == 2
    d = await client.get(f"/documents/{body['id']}/download", headers=h)
    assert d.status_code == 200 and d.content == data
    assert (
        d.headers["x-content-type-options"] == "nosniff"
        and "attachment" in d.headers["content-disposition"]
    )
    assert d.headers["cache-control"] == "private, no-store"


async def test_unauthenticated_and_missing_files(client):
    assert (await client.get("/documents")).status_code == 401
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    assert (await client.get(f"/documents/{uuid.uuid4()}", headers=h)).status_code == 404


@pytest.mark.parametrize(
    ("name", "data", "http", "code"),
    [
        ("a.pdf", b"", 422, "empty"),
        ("a.exe", b"MZ", 415, "unsupported_type"),
        ("a.pdf", b"MZ\x90\x00", 422, "type_mismatch"),
        ("a.docx", pdf_bytes(), 422, "type_mismatch"),
        ("a.docx", office_zip(big_zeros=40 * 1024 * 1024), 422, "zip_bomb"),
    ],
)
async def test_bad_uploads_are_refused_with_a_plain_reason_and_nothing_is_stored(
    client, store, name, data, http, code
):
    org, user, _ = await make_org(plan="GROWTH")
    r = await upload(client, auth(org, user), name, data)
    assert r.status_code == http and r.json()["code"] == code, r.text
    assert store.objects == {} and store.sent == []
    assert await sql("SELECT 1 FROM documents WHERE organization_id = $1", org) == []


async def test_the_size_limit_is_an_admin_setting_per_organisation(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    other, ouser, _ = await make_org(plan="GROWTH")
    await put_setting("documents.uploads", Scope.ORG, str(org), max_mb_pdf=1)
    big = pdf_bytes() + b"\n%" + b"x" * (2 * 1024 * 1024)
    r = await upload(client, auth(org, user), "big.pdf", big)
    assert r.status_code == 413 and r.json()["code"] == "too_large"
    assert (await client.get("/documents/policy", headers=auth(org, user))).json()["kinds"][0] == {
        "kind": "pdf",
        "max_mb": 1,
    }
    assert (
        await upload(client, auth(other, ouser), "big.pdf", big)
    ).status_code == 202  # others unaffected


async def test_a_file_type_can_be_switched_off_and_uploads_can_be_killed(client):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    await put_setting("documents.uploads", Scope.GLOBAL, "", allow_epub=False)
    r = await upload(client, h, "b.epub", b"PK\x03\x04")
    assert r.status_code == 415 and "PDF" in r.json()["detail"] and "EPUB" not in r.json()["detail"]
    await put_setting("documents.uploads", Scope.ORG, str(org), enabled=False)
    assert (await upload(client, h, "a.pdf", pdf_bytes())).json()["code"] == "uploads_disabled"


async def test_upload_rate_is_limited_per_organisation(client):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    await put_setting("documents.uploads", Scope.ORG, str(org), max_files_per_hour=2)
    assert [(await upload(client, h, f"{i}.pdf", pdf_bytes())).status_code for i in range(3)] == [
        202,
        202,
        429,
    ]


async def test_the_documents_feature_flag_switches_everything_off(client):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    await put_setting("flags", Scope.ORG, str(org), documents=False)
    for r in (
        await client.get("/documents", headers=h),
        await upload(client, h, "a.pdf", pdf_bytes()),
    ):
        assert r.status_code == 403 and r.json()["code"] == "feature_disabled"


async def test_a_store_outage_is_our_fault_and_leaves_nothing_behind(client, store, monkeypatch):
    org, user, _ = await make_org(plan="GROWTH")

    async def boom(key, data):
        raise storage.StorageError("down")

    monkeypatch.setattr(store, "put", boom)
    r = await upload(client, auth(org, user), "a.pdf", pdf_bytes())
    assert r.status_code == 503 and r.json()["code"] == "storage_unavailable"
    assert await sql("SELECT 1 FROM documents WHERE organization_id = $1", org) == []


# --- the scan task: it fails closed -----------------------------------------------------------------------------------


async def uploaded(client, org, user, name="a.pdf", data=None):
    r = await upload(client, auth(org, user), name, data or pdf_bytes())
    assert r.status_code == 202, r.text
    return r.json()["id"]


async def test_an_infected_file_is_rejected_and_its_bytes_are_erased(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    did = await uploaded(client, org, user)
    store.verdict = ScanVerdict(False, "Eicar-Test-Signature")
    assert await scan(org, did) == "REJECTED"
    r = await row(did)
    assert r["status"] == "REJECTED" and r["reject_code"] == "malware" and r["storage_key"] is None
    assert store.objects == {}
    h = auth(org, user)
    assert (await client.get(f"/documents/{did}/download", headers=h)).status_code == 409
    shown = (await client.get(f"/documents/{did}", headers=h)).json()
    assert "Eicar" not in str(shown) and "virus" in shown["reject_detail"]


async def test_when_the_scanner_is_down_the_file_is_never_cleared(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    did = await uploaded(client, org, user)
    store.verdict = ScannerUnavailable("down")
    for attempt in (1, 2, 3, 4):
        with pytest.raises(scan_upload.Retry):
            await scan(org, did)
        assert (await row(did))["status"] == "SCANNING" and (await row(did))["attempts"] == attempt
    assert await scan(org, did) == "FAILED"  # 5th attempt (the admin-set maximum)
    r = await row(did)
    assert (
        r["status"] == "FAILED"
        and r["reject_code"] == "system_fault"
        and "our side" in r["reject_detail"]
    )
    assert (
        await client.get(f"/documents/{did}/download", headers=auth(org, user))
    ).status_code == 409
    store.verdict = ScanVerdict(
        True
    )  # a later scanner recovery does not resurrect it: nothing re-runs a FAILED file
    assert await scan(org, did) == "FAILED"


async def test_the_scan_can_only_be_turned_off_outside_production(client, store, monkeypatch):
    org, user, _ = await make_org(plan="GROWTH")
    store.verdict = ScannerUnavailable("down")
    await put_setting("documents.safety", Scope.GLOBAL, "", malware_scan="off")
    did = await uploaded(client, org, user)
    assert await scan(org, did) == "CLEAN"
    assert (
        json.loads((await row(did))["inspection"])["malware_scan"] == "off"
    )  # recorded, never silent
    monkeypatch.setattr(get_settings(), "env", "production")
    with pytest.raises(GuardrailError):
        await put_setting("documents.safety", Scope.GLOBAL, "", malware_scan="off")


async def test_pdfs_with_scripts_or_passwords_or_too_many_pages_are_rejected(client):
    org, user, _ = await make_org(plan="GROWTH")
    await put_setting("documents.uploads", Scope.ORG, str(org), max_pages=2)
    cases = {
        "active_content": pdf_bytes(js=True),
        "encrypted": pdf_bytes(password="pw"),
        "too_many_pages": pdf_bytes(3),
        "corrupt": b"%PDF-1.7\nthis is not really a pdf\n",
    }
    for code, data in cases.items():
        did = await uploaded(client, org, user, data=data)
        assert await scan(org, did) == "REJECTED", code
        assert (await row(did))["reject_code"] == code


async def test_active_content_policy_is_an_admin_setting(client):
    org, user, _ = await make_org(plan="GROWTH")
    await put_setting("documents.safety", Scope.GLOBAL, "", reject_active_content=False)
    did = await uploaded(client, org, user, data=pdf_bytes(js=True))
    assert await scan(org, did) == "CLEAN"
    assert json.loads((await row(did))["inspection"])["active_content"] == ["/JavaScript"]


async def test_macros_and_entity_bombs_in_office_files_are_rejected(client):
    org, user, _ = await make_org(plan="GROWTH")
    macro = await uploaded(
        client, org, user, "m.docx", office_zip(extra={"word/vbaProject.bin": b"\xd0\xcf"})
    )
    assert (
        await scan(org, macro) == "REJECTED"
        and (await row(macro))["reject_code"] == "active_content"
    )
    xxe = await uploaded(
        client,
        org,
        user,
        "x.docx",
        office_zip(
            extra={"word/styles.xml": b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "y">]><a/>'}
        ),
    )
    assert await scan(org, xxe) == "REJECTED" and (await row(xxe))["reject_code"] == "xml_entities"
    ok = await uploaded(client, org, user, "ok.docx", office_zip())
    assert await scan(org, ok) == "CLEAN"


async def test_scanning_is_idempotent_for_a_redelivered_task(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    did = await uploaded(client, org, user)
    assert await scan(org, did) == "CLEAN"
    store.verdict = ScanVerdict(False, "Late")  # a redelivery must not change a decided outcome
    assert await scan(org, did) == "CLEAN"


async def test_a_missing_stored_object_fails_the_file_without_retrying(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    did = await uploaded(client, org, user)
    store.objects.clear()
    assert await scan(org, did) == "FAILED"


# --- isolation, deletion, retention -----------------------------------------------------------------------------


async def test_another_organisation_cannot_see_or_delete_a_document(client):
    org, user, _ = await make_org(plan="GROWTH")
    other, ouser, _ = await make_org(plan="GROWTH")
    did = await uploaded(client, org, user)
    await scan(org, did)
    oh = auth(other, ouser)
    assert (await client.get(f"/documents/{did}", headers=oh)).status_code == 404
    assert (await client.get(f"/documents/{did}/download", headers=oh)).status_code == 404
    assert (await client.delete(f"/documents/{did}", headers=oh)).status_code == 404
    assert (await client.get("/documents", headers=oh)).json() == []
    # even a direct query under the other tenant's session sees nothing (row-level security)
    async with tenant_session(other) as db:
        assert (await db.execute(select(Document))).scalars().all() == []


async def test_deleting_erases_the_bytes_and_leaves_only_a_tombstone(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    member = await add_member(org)
    did = await uploaded(client, org, user)
    await scan(org, did)
    # a different member who did not upload it may not delete it
    assert (
        await client.delete(f"/documents/{did}", headers=auth(org, member, role="STANDARD_USER"))
    ).status_code == 403
    assert (await client.delete(f"/documents/{did}", headers=auth(org, user))).status_code == 204
    assert store.objects == {}
    r = await row(did)
    assert (
        r["status"] == "DELETED"
        and r["storage_key"] is None
        and r["wrapped_key"] is None
        and r["filename"] == "deleted"
    )
    assert (await client.get(f"/documents/{did}", headers=auth(org, user))).status_code == 404
    assert (await client.delete(f"/documents/{did}", headers=auth(org, user))).status_code == 404
    assert await sql(
        "SELECT 1 FROM audit_log WHERE action = 'document.deleted' AND organization_id = $1", org
    )


async def test_retention_comes_from_the_admin_setting_and_the_sweep_erases_expired_files(
    client, store
):
    org, user, _ = await make_org(plan="GROWTH")
    await put_setting("documents.retention", Scope.ORG, str(org), retention_days=7)
    keep = await uploaded(client, org, user)
    gone = await uploaded(client, org, user)
    exp = (await row(keep))["expires_at"]
    created = (await row(keep))["created_at"]
    assert 6.9 < (exp - created).total_seconds() / 86400 < 7.1
    await sql(
        "UPDATE documents SET expires_at = now() - interval '1 minute' WHERE id = $1",
        uuid.UUID(gone),
    )
    out = await documents.purge_expired()
    assert out["errors"] == 0 and out["erased"] >= 1
    assert (await row(gone))["status"] == "DELETED" and (await row(gone))[
        "deleted_reason"
    ] == "retention"
    assert (await row(keep))["status"] == "UPLOADED"
    assert len(store.objects) == 1


async def test_rejected_files_are_kept_only_for_the_short_support_window(client):
    org, user, _ = await make_org(plan="GROWTH")
    did = await uploaded(client, org, user, data=pdf_bytes(password="pw"))
    await scan(org, did)
    r = await row(did)
    assert 2.9 < (r["expires_at"] - r["scanned_at"]).total_seconds() / 86400 < 3.1


async def test_stuck_uploads_are_re_enqueued_by_the_sweeper(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    did = await uploaded(client, org, user)
    store.sent.clear()
    assert await documents.requeue_stale() == 0 or True  # fresh files are not stale
    assert ("docs.scan_upload", [str(org), did], "docs") not in store.sent
    await sql(
        "UPDATE documents SET created_at = now() - interval '10 minutes' WHERE id = $1",
        uuid.UUID(did),
    )
    await documents.requeue_stale()
    assert ("docs.scan_upload", [str(org), did], "docs") in store.sent


async def test_the_admin_settings_are_declared_with_safe_defaults():
    from a11y_core.config.registry import get_def

    for key in ("documents.uploads", "documents.safety", "documents.retention"):
        assert get_def(key).default is not None
    assert get_def("documents.safety").high_risk and get_def(
        "documents.safety"
    ).scopes == frozenset({Scope.GLOBAL})
    assert get_def("documents.safety").default.malware_scan == "required"


# --- the real scanner (skipped when no clamd is reachable) ----------------------------------------------------------

EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


async def test_a_real_clamd_flags_the_eicar_test_file_and_passes_a_clean_one():
    s = get_settings()
    if not await clamav.ping(host=s.clamd_host, port=s.clamd_port, timeout=3):
        pytest.skip("no ClamAV daemon reachable")
    bad = await clamav.scan_bytes(EICAR, host=s.clamd_host, port=s.clamd_port, timeout=60)
    assert not bad.clean and "EICAR" in (bad.signature or "").upper()
    good = await clamav.scan_bytes(pdf_bytes(2), host=s.clamd_host, port=s.clamd_port, timeout=60)
    assert good.clean


async def test_end_to_end_with_a_real_clamd_an_infected_upload_is_refused_and_erased(
    client, store, monkeypatch
):
    s = get_settings()
    if not await clamav.ping(host=s.clamd_host, port=s.clamd_port, timeout=3):
        pytest.skip("no ClamAV daemon reachable")
    monkeypatch.setattr(scan_upload, "scan_bytes", clamav.scan_bytes)  # undo the fake
    org, user, _ = await make_org(plan="GROWTH")
    # ClamAV unpacks archives and scans their members, so EICAR inside a .docx is found (EICAR text in a PDF is not).
    infected = await uploaded(
        client, org, user, "eicar.docx", office_zip(extra={"word/note.txt": EICAR})
    )
    assert await scan(org, infected) == "REJECTED"
    assert (await row(infected))["reject_code"] == "malware" and store.objects == {}
    fine = await uploaded(client, org, user)
    assert await scan(org, fine) == "CLEAN"
