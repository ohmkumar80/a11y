# ruff: noqa: F811
"""The public API for documents: /v1/documents. Same safety pipeline, quota and isolation as the web app."""

import uuid

import pytest
from a11y_documents import audit_task

from .conftest import make_org
from .test_billing import used
from .test_document_audits import FEATURE, clean_pdf, needs_verapdf  # noqa: F401
from .test_documents import _clean_settings, pdf_bytes, scan, store  # noqa: F401  (fixtures)
from .test_public_api import _clean, bearer, new_key, org_with_key  # noqa: F401  (_clean: clears rate-limit and idempotency keys)


async def put(client, h, name, data, **kw):
    return await client.post(
        "/v1/documents",
        params={"filename": name},
        content=data,
        headers={**h, "content-type": "application/octet-stream", **kw},
    )


async def test_upload_scan_audit_read_download_delete_with_an_api_key(client, store):
    org, user, k, h = await org_with_key(client, ["documents:read", "documents:write"])
    data = pdf_bytes(2)
    r = await put(client, h, "board.pdf", data)
    assert r.status_code == 202, r.text
    d = r.json()
    assert d["status"] == "UPLOADED" and d["ready"] is False and d["latest_audit"] is None
    # held until checked, over the API too
    assert (await client.get(f"/v1/documents/{d['id']}/download", headers=h)).status_code == 409
    assert (await client.post(f"/v1/documents/{d['id']}/audits", headers=h)).status_code == 409

    assert await scan(org, d["id"]) == "CLEAN"
    got = (await client.get(f"/v1/documents/{d['id']}", headers=h)).json()
    assert got["ready"] and got["page_count"] == 2
    assert (await client.get(f"/v1/documents/{d['id']}/download", headers=h)).content == data
    assert [x["id"] for x in (await client.get("/v1/documents", headers=h)).json()] == [d["id"]]

    a = await client.post(f"/v1/documents/{d['id']}/audits", headers=h)
    assert a.status_code == 202 and a.json()["pages"] == 2 and await used(org, FEATURE) == 2
    assert await audit_task.run_audit(org, uuid.UUID(a.json()["id"])) == "SUCCEEDED"
    detail = (
        await client.get(f"/v1/documents/{d['id']}/audits/{a.json()['id']}", headers=h)
    ).json()
    assert detail["status"] == "SUCCEEDED" and detail["document"]["filename"] == "board.pdf"
    assert detail["summary"]["caveat"] and all(
        {"title", "explanation", "how_to_fix", "severity"} <= set(f) for f in detail["findings"]
    )
    assert len((await client.get(f"/v1/documents/{d['id']}/audits", headers=h)).json()) == 1

    assert (await client.delete(f"/v1/documents/{d['id']}", headers=h)).status_code == 204
    assert (await client.get(f"/v1/documents/{d['id']}", headers=h)).status_code == 404
    assert store.objects == {}


async def test_scopes_are_enforced_per_operation(client):
    org, user, k, ro = await org_with_key(client, ["documents:read"])
    _, _, _, wo = await org_with_key(client, ["documents:write"])
    _, _, _, other_scope = await org_with_key(client, ["scans:read"])
    assert (await put(client, ro, "a.pdf", pdf_bytes())).json()["code"] == "scope_missing"
    assert (await client.get("/v1/documents", headers=wo)).json()["code"] == "scope_missing"
    assert (await client.get("/v1/documents", headers=other_scope)).status_code == 403
    assert (await client.delete(f"/v1/documents/{uuid.uuid4()}", headers=ro)).json()[
        "code"
    ] == "scope_missing"
    assert (
        await client.post(f"/v1/documents/{uuid.uuid4()}/audits", headers=ro)
    ).status_code == 403
    assert (await client.get("/v1/documents")).status_code == 401


async def test_a_retried_upload_with_the_same_idempotency_key_makes_one_document(client, store):
    org, user, k, h = await org_with_key(client, ["documents:read", "documents:write"])
    first = await put(client, h, "a.pdf", pdf_bytes(), **{"Idempotency-Key": "up-1"})
    again = await put(client, h, "a.pdf", pdf_bytes(), **{"Idempotency-Key": "up-1"})
    assert first.status_code == again.status_code == 202
    assert again.headers["idempotent-replay"] == "true" and again.json()["id"] == first.json()["id"]
    assert (
        len((await client.get("/v1/documents", headers=h)).json()) == 1 and len(store.objects) == 1
    )


async def test_refusals_use_the_same_error_shape(client, store):
    org, user, k, h = await org_with_key(client, ["documents:read", "documents:write"])
    r = await put(client, h, "notes.exe", b"MZ")
    assert r.status_code == 415 and r.json()["code"] == "unsupported_type" and r.json()["detail"]
    r = await put(client, h, "fake.pdf", b"not a pdf at all")
    assert r.status_code == 422 and r.json()["code"] == "type_mismatch"
    assert store.objects == {}


async def test_one_organisations_key_cannot_reach_anothers_documents(client, store):
    org, user, k, h = await org_with_key(client, ["documents:read", "documents:write"])
    _, _, _, other = await org_with_key(client, ["documents:read", "documents:write"])
    d = (await put(client, h, "a.pdf", pdf_bytes())).json()
    await scan(org, d["id"])
    for call in (
        client.get(f"/v1/documents/{d['id']}", headers=other),
        client.get(f"/v1/documents/{d['id']}/download", headers=other),
        client.post(f"/v1/documents/{d['id']}/audits", headers=other),
        client.delete(f"/v1/documents/{d['id']}", headers=other),
    ):
        assert (await call).status_code == 404
    assert (await client.get("/v1/documents", headers=other)).json() == []


@needs_verapdf
async def test_a_plan_limit_is_reported_with_the_usual_code(client, store):
    from .conftest import sql

    org, user, k, h = await org_with_key(client, ["documents:read", "documents:write"])
    d = (await put(client, h, "a.pdf", pdf_bytes(3))).json()
    await scan(org, d["id"])
    await sql(
        "INSERT INTO entitlement_overrides (organization_id, feature_key, enabled, limit_value, reason) VALUES ($1, $2, true, 1, 'test-limit')",
        org,
        FEATURE,
    )
    r = await client.post(f"/v1/documents/{d['id']}/audits", headers=h)
    assert r.json()["code"] == "quota_exceeded" and await used(org, FEATURE) == 0
    assert (
        pytest and clean_pdf and new_key and bearer and make_org
    )  # (shared helpers imported for the suite)
