# ruff: noqa: F811
"""The admin Documents module: health, pipeline overview, retrying files that failed on our side, retention sweep."""

import uuid

import pytest
from a11y_core.clamav import ScannerUnavailable
from a11y_documents.scan_upload import Retry

from .conftest import make_org, sql, super_admin_headers
from .test_billing import auth
from .test_documents import (  # noqa: F401  (fixtures)
    _clean_settings,
    pdf_bytes,
    row,
    scan,
    store,
    uploaded,
)


async def test_only_a_platform_administrator_can_use_the_module(client):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    assert (await client.get("/admin/documents/overview", headers=h)).status_code == 403
    assert (await client.post("/admin/documents/purge", headers=h)).status_code == 403
    assert (await client.get("/admin/documents/overview")).status_code == 401


async def test_overview_reports_health_the_pipeline_and_why_files_are_refused(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    ok = await uploaded(client, org, user)
    await scan(org, ok)
    bad = await uploaded(client, org, user, data=pdf_bytes(password="pw"))
    await scan(org, bad)
    r = await client.get("/admin/documents/overview", headers=super_admin_headers())
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["health"]["storage"] == "ok" and o["health"]["scanner"] in ("ok", "down")
    assert o["by_status"]["CLEAN"] >= 1 and o["by_status"]["REJECTED"] >= 1
    assert any(x["code"] == "encrypted" and x["count"] >= 1 for x in o["rejections_30d"])
    assert o["stored_bytes"] > 0 and "failed" in o
    assert "filename" not in str(o) and "storage_key" not in str(
        o
    )  # metadata only: never names or keys


async def test_a_file_that_failed_on_our_side_can_be_retried_and_must_pass_every_check(
    client, store
):
    org, user, _ = await make_org(plan="GROWTH")
    did = await uploaded(client, org, user)
    store.verdict = ScannerUnavailable("down")
    for _ in range(4):
        with pytest.raises(Retry):
            await scan(org, did)
    assert await scan(org, did) == "FAILED"
    sa = super_admin_headers()
    listed = (await client.get("/admin/documents/overview", headers=sa)).json()["failed"]
    assert any(f["id"] == did and "scanner" in f["why"] for f in listed)

    r = await client.post(f"/admin/documents/{did}/rescan", headers=sa)
    assert r.status_code == 200 and r.json()["status"] == "UPLOADED"
    assert ("docs.scan_upload", [str(org), did], "docs") in store.sent
    assert (await row(did))["attempts"] == 0
    # still held back until it passes
    assert (
        await client.get(f"/documents/{did}/download", headers=auth(org, user))
    ).status_code == 409
    from a11y_core.clamav import ScanVerdict

    store.verdict = ScanVerdict(True)
    assert await scan(org, did) == "CLEAN"
    # only FAILED files can be retried
    assert (await client.post(f"/admin/documents/{did}/rescan", headers=sa)).status_code == 404
    assert (
        await client.post(f"/admin/documents/{uuid.uuid4()}/rescan", headers=sa)
    ).status_code == 404


async def test_the_retention_sweep_can_be_run_now(client, store):
    org, user, _ = await make_org(plan="GROWTH")
    did = await uploaded(client, org, user)
    await sql(
        "UPDATE documents SET expires_at = now() - interval '1 hour' WHERE id = $1", uuid.UUID(did)
    )
    r = await client.post("/admin/documents/purge", headers=super_admin_headers())
    assert r.status_code == 200 and r.json()["erased"] >= 1 and r.json()["errors"] == 0
    assert (await row(did))["status"] == "DELETED" and store.objects == {}
