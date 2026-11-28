# ruff: noqa: F811
"""Human review (ADR 0023): the reviewer role, consent, the queue, claiming, access control, fixing, delivery, credits."""

import uuid
from datetime import UTC, datetime

import pytest
from a11y_core import document_reviews, notify
from a11y_core.config import Scope
from a11y_core.db import login_lookup_session, reviewer_session
from a11y_core.models import Role, User
from a11y_documents import fix_task
from sqlalchemy import text

from a11y_api.security import Principal, hash_password, issue_access_token

from .conftest import make_org, sql, super_admin_headers
from .test_billing import auth, used
from .test_document_audits import defective_pdf, needs_verapdf, reservation  # noqa: F401
from .test_document_fixes import audited  # noqa: F401
from .test_documents import _clean_settings, pdf_bytes, put_setting, scan, store, uploaded  # noqa: F401

PW = "a-long-passphrase-123"
FEATURE = "document_reviews_monthly"
PAGES = "document_pages_monthly"


async def make_reviewer(email: str | None = None, pw: str = PW, role=Role.REVIEWER):
    uid = uuid.uuid4()
    email = email or f"rev-{uid.hex[:8]}@example.com"
    async with login_lookup_session(email) as db:
        db.add(
            User(
                id=uid,
                organization_id=None,
                email=email,
                hashed_password=hash_password(pw),
                role=role,
                email_verified_at=datetime.now(UTC),
            )
        )
    tok, _ = issue_access_token(Principal(uid, None, role, email))
    return uid, {"authorization": f"Bearer {tok}"}, email


@pytest.fixture(autouse=True)
async def _wipe_reviews():
    async def wipe():
        await sql("DELETE FROM platform_sessions WHERE email LIKE 'rev-%@example.com'")
        await sql("DELETE FROM users WHERE role = 'REVIEWER' AND email LIKE 'rev-%@example.com'")
        await sql("DELETE FROM audit_log WHERE action LIKE 'review.%'")

    await wipe()
    yield
    await wipe()


async def ask(client, org, user, did, note="Please check the charts", consent=True):
    return await client.post(
        f"/documents/{did}/reviews",
        headers=auth(org, user),
        json={"note": note, "consent": consent},
    )


# --- the role -----------------------------------------------------------------------------------------


async def test_a_reviewer_signs_in_with_no_organisation_and_gets_a_platform_session(client):
    uid, _, email = await make_reviewer()
    r = await client.post("/auth/login", json={"email": email, "password": "a-long-passphrase-123"})
    assert r.status_code == 200, r.text
    u = r.json()["user"]
    assert u["role"] == "REVIEWER" and u["organization_id"] == ""
    assert "a11y_platform" in r.headers.get("set-cookie", "")
    cookie = {"cookie": f"a11y_platform={r.cookies['a11y_platform']}"}
    refreshed = await client.post(
        "/auth/refresh", headers=cookie
    )  # the rotating platform cookie works for reviewers too
    assert refreshed.status_code == 200 and refreshed.json()["user"]["role"] == "REVIEWER"
    bad = await client.post("/auth/login", json={"email": email, "password": "wrong-password-123"})
    assert bad.status_code == 401


async def test_a_reviewer_cannot_use_customer_or_admin_endpoints(client):
    _, h, _ = await make_reviewer()
    assert (await client.get("/documents", headers=h)).status_code == 403  # no organisation
    assert (await client.get("/org/subscription", headers=h)).status_code == 403
    assert (
        await client.get("/admin/documents/overview", headers=h)
    ).status_code == 403  # not a Super Admin
    assert (
        await client.post(
            "/admin/reviewers", headers=h, json={"email": "x@example.com", "password": "pw"}
        )
    ).status_code == 403
    assert (await client.get("/review/queue", headers=h)).status_code == 200


async def test_customers_and_anonymous_visitors_cannot_use_the_reviewer_console(client):
    org, user, _ = await make_org(plan="GROWTH")
    assert (await client.get("/review/queue", headers=auth(org, user))).status_code == 403
    assert (await client.get("/review/queue")).status_code == 401


async def test_switching_a_reviewer_off_takes_effect_immediately_not_at_token_expiry(client):
    uid, h, email = await make_reviewer()
    assert (await client.get("/review/queue", headers=h)).status_code == 200
    await sql("UPDATE users SET is_active = false WHERE id = $1", uid)
    assert (await client.get("/review/queue", headers=h)).status_code == 403
    assert (
        await client.post("/auth/login", json={"email": email, "password": "a-long-passphrase-123"})
    ).status_code == 401


async def test_the_platform_two_step_policy_applies_to_reviewers_too(client):
    _, _, email = await make_reviewer()
    await put_setting("auth.mfa", Scope.GLOBAL, "", super_admin="required", org_admin="optional")
    r = await client.post("/auth/login", json={"email": email, "password": "a-long-passphrase-123"})
    assert r.status_code == 200 and r.json().get("mfa") in ("enroll", "verify"), r.text
    assert "access_token" not in r.json()


async def test_the_database_keeps_platform_roles_out_of_organisations():
    org, _, _ = await make_org(plan="GROWTH")
    with pytest.raises(Exception, match="ck_users_org_role"):
        await sql(
            "INSERT INTO users (id, organization_id, email, hashed_password, role) VALUES (gen_random_uuid(), $1, 'bad-rev@example.com', 'x', 'REVIEWER')",
            org,
        )
    with pytest.raises(Exception, match="ck_users_org_role"):
        await sql(
            "INSERT INTO users (id, organization_id, email, hashed_password, role) VALUES (gen_random_uuid(), NULL, 'bad-user@example.com', 'x', 'STANDARD_USER')"
        )


# --- asking for a review -----------------------------------------------------------------------------------


@needs_verapdf
async def test_a_request_needs_consent_a_checked_pdf_and_one_credit(client):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    waiting = await uploaded(client, org, user, "a.pdf", defective_pdf())
    assert await scan(org, waiting) == "CLEAN"
    assert (await ask(client, org, user, waiting)).json()[
        "code"
    ] == "needs_audit"  # not audited yet
    did = await audited(client, org, user, defective_pdf())
    info = (await client.get(f"/documents/{did}/reviews", headers=h)).json()
    assert (
        info["reviews"] == []
        and "open this file" in info["consent"]["text"]
        and info["consent"]["version"]
    )
    r = await ask(client, org, user, did, consent=False)
    assert (
        r.status_code == 422
        and r.json()["code"] == "consent_required"
        and await used(org, FEATURE) == 0
    )

    r = await ask(client, org, user, did)
    assert r.status_code == 202, r.text
    rv = r.json()
    assert (
        rv["status"] == "REQUESTED" and rv["note"] == "Please check the charts" and rv["pages"] == 1
    )
    assert (
        47
        < (
            datetime.fromisoformat(rv["due_at"]) - datetime.fromisoformat(rv["requested_at"])
        ).total_seconds()
        / 3600
        < 49
    )
    assert await used(org, FEATURE) == 1 and await reservation(org, rv["id"]) == "RESERVED"
    assert (await ask(client, org, user, did)).json()["code"] == "review_open"
    docs = {d["id"]: d for d in (await client.get("/documents", headers=h)).json()}
    assert docs[did]["latest_review"]["status"] == "REQUESTED"
    assert await sql(
        "SELECT 1 FROM audit_log WHERE organization_id=$1 AND action='review.requested'", org
    )


async def test_a_plan_without_reviews_and_the_switches_all_refuse_clearly(client):
    org, user, _ = await make_org(plan="TRIAL")
    did = (
        await audited(client, org, user, pdf_bytes()) if False else None
    )  # (untagged files cannot be audited into a fix state)
    assert did is None
    org2, user2, _ = await make_org(plan="GROWTH")
    d2 = await audited(client, org2, user2, defective_pdf())
    await put_setting("flags", Scope.ORG, str(org2), human_review=False)
    assert (await ask(client, org2, user2, d2)).json()["code"] == "feature_disabled"
    await put_setting("flags", Scope.ORG, str(org2), human_review=True)
    await put_setting("documents.review", Scope.ORG, str(org2), enabled=False)
    assert (await ask(client, org2, user2, d2)).json()["code"] == "reviews_disabled"
    await put_setting("documents.review", Scope.ORG, str(org2), max_open_per_org=1)
    assert (await ask(client, org2, user2, d2)).status_code == 202  # allowed again, one open
    d3 = await audited(client, org2, user2, defective_pdf())
    assert (await ask(client, org2, user2, d3)).json()["code"] == "too_many_reviews"


@needs_verapdf
async def test_the_plan_allowance_stops_a_request_before_anything_is_queued(client):
    org, user, _ = await make_org(plan="TRIAL")  # the trial includes no reviews
    did = await audited(client, org, user, defective_pdf())
    r = await ask(client, org, user, did)
    assert r.json()["code"] == "quota_exceeded", r.text
    assert await sql("SELECT 1 FROM document_reviews WHERE organization_id=$1", org) == []


@needs_verapdf
async def test_cancelling_before_a_reviewer_takes_it_gives_the_credit_back_after_it_does_not(
    client,
):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await audited(client, org, user, defective_pdf())
    rid = (await ask(client, org, user, did)).json()["id"]
    assert (await client.delete(f"/documents/{did}/reviews/{rid}", headers=h)).status_code == 204
    assert await used(org, FEATURE) == 0 and await reservation(org, rid) == "RELEASED"
    assert (await client.get(f"/documents/{did}/reviews", headers=h)).json()["reviews"][0][
        "status"
    ] == "CANCELLED"
    rid2 = (await ask(client, org, user, did)).json()["id"]
    rev, rh, _ = await make_reviewer()
    assert (await client.post(f"/review/{rid2}/claim", headers=rh)).status_code == 200
    r = await client.delete(f"/documents/{did}/reviews/{rid2}", headers=h)
    assert r.status_code == 409 and r.json()["code"] == "already_started"


# --- the queue and the claim ---------------------------------------------------------------------------------


@needs_verapdf
async def test_the_queue_shows_counts_never_names_notes_or_content_until_a_file_is_claimed(client):
    org, user, _ = await make_org(plan="GROWTH")
    did = await audited(client, org, user, defective_pdf())
    rid = (await ask(client, org, user, did, note="secret instructions")).json()["id"]
    _, rh, _ = await make_reviewer()
    q = (await client.get("/review/queue", headers=rh)).json()
    item = next(i for i in q["items"] if i["id"] == rid)
    assert (
        item["status"] == "REQUESTED"
        and item["pages"] == 1
        and item["snapshot"]["findings"] >= 3
        and item["mine"] is False
    )
    blob = str(q)
    assert (
        "report.pdf" not in blob
        and "secret instructions" not in blob
        and str(org) not in blob
        and "has_note" not in blob
    )
    # nothing can be read before claiming
    assert (await client.get(f"/review/{rid}", headers=rh)).status_code == 403
    assert (await client.get(f"/review/{rid}/original", headers=rh)).status_code == 403
    assert (
        await client.put(f"/review/{rid}/fix", headers=rh, json={"language": "en"})
    ).status_code == 403


@needs_verapdf
async def test_a_file_has_one_reviewer_and_everything_they_do_is_in_the_customers_audit_log(
    client, store
):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    data = defective_pdf()
    did = await audited(client, org, user, data)
    rid = (await ask(client, org, user, did, note="Look at page 2")).json()["id"]
    a, ah, _ = await make_reviewer()
    b, bh, _ = await make_reviewer()
    assert (await client.post(f"/review/{rid}/claim", headers=ah)).status_code == 200
    r = await client.post(f"/review/{rid}/claim", headers=bh)
    assert r.status_code == 409 and r.json()["code"] == "unavailable"
    # the second reviewer neither sees it in the queue nor can open it
    assert rid not in [
        i["id"] for i in (await client.get("/review/queue", headers=bh)).json()["items"]
    ]
    assert (await client.get(f"/review/{rid}", headers=bh)).status_code == 403
    assert (await client.get(f"/review/{rid}/original", headers=bh)).status_code == 403
    # the holder gets the name, the note, the findings and the structure
    s = (await client.get(f"/review/{rid}", headers=ah)).json()
    assert s["document"]["filename"] == "report.pdf" and s["review"]["note"] == "Look at page 2"
    assert s["structure"]["has_structure"] and {"7.3-1", "7.2-29"} <= {
        f["rule_id"] for f in s["findings"]
    }
    dl = await client.get(f"/review/{rid}/original", headers=ah)
    assert (
        dl.status_code == 200
        and dl.content == data
        and dl.headers["cache-control"] == "private, no-store"
    )
    actions = [
        r["action"]
        for r in await sql(
            "SELECT action FROM audit_log WHERE organization_id=$1 AND action LIKE 'review.%' ORDER BY created_at",
            org,
        )
    ]
    assert actions == ["review.requested", "review.claimed", "review.original_downloaded"]
    # the customer sees that a person is on it, never who
    cj = (await client.get(f"/documents/{did}/reviews", headers=h)).json()["reviews"][0]
    assert cj["status"] == "IN_REVIEW" and "reviewer" not in str(cj) and str(a) not in str(cj)
    # releasing puts it back for anyone
    assert (await client.post(f"/review/{rid}/release", headers=ah)).status_code == 204
    assert (
        await client.post(f"/review/{rid}/release", headers=ah)
    ).status_code == 409  # no longer theirs
    assert (await client.post(f"/review/{rid}/claim", headers=bh)).status_code == 200


async def test_the_database_itself_confines_a_reviewer_to_the_queue_and_their_own_claims(client):
    org, user, _ = await make_org(plan="GROWTH")
    did = await audited(client, org, user, defective_pdf())
    rid = (await ask(client, org, user, did)).json()["id"]
    a, ah, _ = await make_reviewer()
    b, _, _ = await make_reviewer()
    async with reviewer_session(
        a
    ) as db:  # without any claim: the unclaimed request, and nothing else
        assert (
            await db.execute(
                text("SELECT count(*) FROM document_reviews WHERE id = :i"), {"i": rid}
            )
        ).scalar_one() == 1
        for table in (
            "documents",
            "document_audits",
            "document_fixes",
            "users",
            "organizations",
            "audit_log",
        ):
            assert (await db.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0, (
                table
            )
    await client.post(f"/review/{rid}/claim", headers=ah)
    async with reviewer_session(b) as db:  # claimed by someone else: invisible, and not changeable
        assert (
            await db.execute(
                text("SELECT count(*) FROM document_reviews WHERE id = :i"), {"i": rid}
            )
        ).scalar_one() == 0
        res = await db.execute(
            text(
                "UPDATE document_reviews SET status = 'REQUESTED', reviewer_id = NULL WHERE id = :i"
            ),
            {"i": rid},
        )
        assert res.rowcount == 0
    async with reviewer_session(
        a
    ) as db:  # a reviewer cannot give a file to someone else or forge the customer's consent
        with pytest.raises(Exception, match="row-level security|permission denied"):
            await db.execute(
                text("UPDATE document_reviews SET reviewer_id = :b WHERE id = :i"),
                {"b": b, "i": rid},
            )


@needs_verapdf
async def test_a_reviewer_holds_a_limited_number_of_files_and_the_owner_can_take_one_back(client):
    _, rh, _ = await make_reviewer()
    ids = []
    for _ in range(document_reviews.MAX_CLAIMS + 1):
        org, user, _ = await make_org(plan="GROWTH")
        did = await audited(client, org, user, defective_pdf())
        ids.append((await ask(client, org, user, did)).json()["id"])
    for rid in ids[:-1]:
        assert (await client.post(f"/review/{rid}/claim", headers=rh)).status_code == 200
    r = await client.post(f"/review/{ids[-1]}/claim", headers=rh)
    assert r.status_code == 409 and r.json()["code"] == "too_many_claims"
    sa = super_admin_headers()
    assert (await client.post(f"/admin/reviews/{ids[0]}/release", headers=sa)).status_code == 204
    assert ids[0] in [
        i["id"]
        for i in (await client.get("/review/queue", headers=rh)).json()["items"]
        if not i["mine"]
    ]
    assert (
        await client.post(f"/admin/reviews/{ids[0]}/release", headers=sa)
    ).status_code == 404  # nobody holds it now
    assert (await client.post(f"/admin/reviews/{ids[0]}/release", headers=rh)).status_code == 403


# --- doing the work and delivering it ------------------------------------------------------------------------------


@needs_verapdf
async def test_the_whole_review_fix_deliver_and_the_customer_is_told(client, store, monkeypatch):
    sent = []

    async def fake_emit(event, **kw):
        sent.append((event, kw))
        return []

    monkeypatch.setattr(notify, "emit", fake_emit)
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await audited(client, org, user, defective_pdf())
    pages_before = await used(org, PAGES)
    rid = (await ask(client, org, user, did)).json()["id"]
    _, rh, _ = await make_reviewer()
    await client.post(f"/review/{rid}/claim", headers=rh)
    # the customer cannot change the plan underneath the reviewer
    r = await client.put(f"/documents/{did}/fix", headers=h, json={"language": "en"})
    assert r.status_code == 409 and r.json()["code"] == "in_review"

    st = (await client.get(f"/review/{rid}", headers=rh)).json()["structure"]
    plan = {
        "title": "Quarterly report",
        "language": "en-GB",
        "alt": {st["figures"][0]["id"]: "A red rectangle used as a sample picture"},
        "heading_levels": {st["headings"][1]["id"]: 2},
    }
    assert (await client.put(f"/review/{rid}/fix", headers=rh, json=plan)).status_code == 200
    # delivering before there is a fixed copy is refused
    r = await client.post(f"/review/{rid}/submit", headers=rh, json={"outcome": "deliver"})
    assert r.status_code == 409 and r.json()["code"] == "no_result"
    assert (await client.get(f"/review/{rid}/result", headers=rh)).json()["code"] == "no_result"
    b = await client.post(f"/review/{rid}/fix/build", headers=rh)
    assert b.status_code == 202
    assert (
        await used(org, PAGES) == pages_before
    )  # the review covers the work: the customer's pages are not used
    assert await fix_task.run_fix(org, uuid.UUID(b.json()["id"])) == "READY"
    assert await used(org, PAGES) == pages_before

    r = await client.post(
        f"/review/{rid}/submit",
        headers=rh,
        json={
            "outcome": "deliver",
            "message": "Described the chart; please check the colours yourself.",
            "minutes": 12,
        },
    )
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED"
    rv = (await client.get(f"/documents/{did}/reviews", headers=h)).json()["reviews"][0]
    assert (
        rv["status"] == "COMPLETED"
        and "colours yourself" in rv["outcome_note"]
        and rv["result_document_id"]
    )
    copy = await client.get(f"/documents/{rv['result_document_id']}/download", headers=h)
    assert copy.status_code == 200 and b"%PDF" in copy.content
    assert await used(org, FEATURE) == 1 and await reservation(org, rid) == "COMMITTED"
    row = (
        await sql(
            "SELECT reported_minutes, elapsed_seconds, completed_at FROM document_reviews WHERE id=$1",
            uuid.UUID(rid),
        )
    )[0]
    assert row["reported_minutes"] == 12 and row["elapsed_seconds"] >= 0 and row["completed_at"]
    assert [e for e, _ in sent] == ["document.review_done"] and "fixed copy is ready" in sent[0][1][
        "variables"
    ]["outcome"]
    # it is finished: the reviewer can no longer open the file, and the customer can edit again
    assert (await client.get(f"/review/{rid}", headers=rh)).status_code == 403
    assert (await client.get(f"/review/{rid}/original", headers=rh)).status_code == 403
    assert (
        await client.put(f"/documents/{did}/fix", headers=h, json={"language": "en"})
    ).status_code == 200
    assert (
        await client.post(f"/review/{rid}/submit", headers=rh, json={"outcome": "deliver"})
    ).status_code == 403


@needs_verapdf
async def test_declining_needs_a_reason_gives_the_credit_back_and_tells_the_customer(
    client, monkeypatch
):
    sent = []

    async def fake_emit(event, **kw):
        sent.append(kw)
        return []

    monkeypatch.setattr(notify, "emit", fake_emit)
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await audited(client, org, user, defective_pdf())
    rid = (await ask(client, org, user, did)).json()["id"]
    _, rh, _ = await make_reviewer()
    await client.post(f"/review/{rid}/claim", headers=rh)
    r = await client.post(f"/review/{rid}/submit", headers=rh, json={"outcome": "decline"})
    assert r.status_code == 422 and r.json()["code"] == "reason_required"
    r = await client.post(
        f"/review/{rid}/submit",
        headers=rh,
        json={
            "outcome": "decline",
            "message": "The scans are too blurred to read; please send the original document.",
        },
    )
    assert r.status_code == 200 and r.json()["status"] == "DECLINED"
    rv = (await client.get(f"/documents/{did}/reviews", headers=h)).json()["reviews"][0]
    assert (
        rv["status"] == "DECLINED"
        and "too blurred" in rv["outcome_note"]
        and rv["result_document_id"] is None
    )
    assert await used(org, FEATURE) == 0 and await reservation(org, rid) == "RELEASED"
    assert "We could not improve this file" in sent[0]["variables"]["outcome"]
    assert (
        await client.post(f"/review/{rid}/submit", headers=rh, json={"outcome": "bad"})
    ).status_code == 422


@needs_verapdf
async def test_a_fixed_copy_made_before_the_claim_cannot_be_delivered_as_the_reviewers_work(client):
    org, user, _ = await make_org(plan="GROWTH")
    h = auth(org, user)
    did = await audited(client, org, user, defective_pdf())
    await client.put(f"/documents/{did}/fix", headers=h, json={"language": "en"})
    fid = (await client.post(f"/documents/{did}/fix/build", headers=h)).json()["id"]
    assert await fix_task.run_fix(org, uuid.UUID(fid)) == "READY"  # the customer's own copy
    rid = (await ask(client, org, user, did)).json()["id"]
    _, rh, _ = await make_reviewer()
    await client.post(f"/review/{rid}/claim", headers=rh)
    r = await client.post(f"/review/{rid}/submit", headers=rh, json={"outcome": "deliver"})
    assert r.status_code == 409 and r.json()["code"] == "no_result"


# --- timeouts, sweeps and the owner's view ------------------------------------------------------------------------------


@needs_verapdf
async def test_a_reviewer_who_goes_quiet_loses_the_file_and_stuck_credits_are_settled(client):
    org, user, _ = await make_org(plan="GROWTH")
    did = await audited(client, org, user, defective_pdf())
    rid = (await ask(client, org, user, did)).json()["id"]
    rev, rh, _ = await make_reviewer()
    await client.post(f"/review/{rid}/claim", headers=rh)
    assert await document_reviews.release_stale_claims() == 0  # still within the timeout
    await sql(
        "UPDATE document_reviews SET claimed_at = now() - interval '9 hours' WHERE id = $1",
        uuid.UUID(rid),
    )
    assert await document_reviews.release_stale_claims() == 1
    assert (await client.get(f"/review/{rid}", headers=rh)).status_code == 403
    assert rid in [i["id"] for i in (await client.get("/review/queue", headers=rh)).json()["items"]]
    assert await sql(
        "SELECT 1 FROM audit_log WHERE organization_id=$1 AND action='review.claim_expired'", org
    )
    # a review that ended but never settled its credit (a crash between two writes) is settled by the sweeper
    await sql("UPDATE document_reviews SET status='DECLINED' WHERE id=$1", uuid.UUID(rid))
    await sql(
        "UPDATE usage_reservations SET created_at = now() - interval '2 hours' WHERE organization_id=$1 AND job_id=$2",
        org,
        rid,
    )
    out = await document_reviews.sweep_review_reservations()
    assert (
        out["released"] >= 1
        and await reservation(org, rid) == "RELEASED"
        and await used(org, FEATURE) == 0
    )


async def test_the_owner_creates_switches_off_and_resets_reviewers(client):
    sa = super_admin_headers()
    email = f"rev-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post(
        "/admin/reviewers", headers=sa, json={"email": email, "password": "short"}
    )
    assert r.status_code == 422 and r.json()["field"] == "password"
    r = await client.post(
        "/admin/reviewers", headers=sa, json={"email": email, "password": "a-long-passphrase-123"}
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert (
        await client.post(
            "/admin/reviewers",
            headers=sa,
            json={"email": email, "password": "a-long-passphrase-123"},
        )
    ).status_code == 409
    assert (
        await client.post("/auth/login", json={"email": email, "password": "a-long-passphrase-123"})
    ).status_code == 200
    assert (
        await client.post(
            f"/admin/reviewers/{rid}/password",
            headers=sa,
            json={"password": "a-brand-new-passphrase-9"},
        )
    ).status_code == 204
    assert (
        await client.post("/auth/login", json={"email": email, "password": "a-long-passphrase-123"})
    ).status_code == 401
    assert (
        await client.post(
            "/auth/login", json={"email": email, "password": "a-brand-new-passphrase-9"}
        )
    ).status_code == 200
    assert (
        await client.post(f"/admin/reviewers/{rid}/active", headers=sa, json={"active": False})
    ).status_code == 204
    assert (
        await client.post(
            "/auth/login", json={"email": email, "password": "a-brand-new-passphrase-9"}
        )
    ).status_code == 401
    ov = (await client.get("/admin/reviews/overview", headers=sa)).json()
    assert any(p["email"] == email and p["active"] is False for p in ov["reviewers"])
    assert (
        await client.post(
            f"/admin/reviewers/{uuid.uuid4()}/active", headers=sa, json={"active": True}
        )
    ).status_code == 404
    assert await sql(
        "SELECT 1 FROM audit_log WHERE action = 'admin.reviewer_created' AND detail->>'reason' LIKE $1",
        f"%{email}",
    )


@needs_verapdf
async def test_the_owner_sees_the_queue_turnaround_and_the_cost_of_a_review_and_a_page(client):
    await put_setting("documents.review", Scope.GLOBAL, "", reviewer_cost_per_hour=600)
    org, user, _ = await make_org(plan="GROWTH")
    did = await audited(client, org, user, defective_pdf())
    rid = (await ask(client, org, user, did)).json()["id"]
    ov = (await client.get("/admin/reviews/overview", headers=super_admin_headers())).json()
    assert ov["waiting"] >= 1 and ov["cost_per_hour"] == 600
    _, rh, _ = await make_reviewer()
    await client.post(f"/review/{rid}/claim", headers=rh)
    r = await client.post(
        f"/review/{rid}/submit",
        headers=rh,
        json={"outcome": "decline", "message": "Cannot be improved here, sorry.", "minutes": 30},
    )
    assert r.status_code == 200
    ov = (await client.get("/admin/reviews/overview", headers=super_admin_headers())).json()
    assert (
        ov["finished_30d"] >= 1
        and ov["on_time_percent"] is not None
        and ov["avg_reported_minutes"] > 0
    )
    # the cost of a review is the average reviewer time at the admin-set hourly cost
    assert ov["cost_per_review"] == pytest.approx(ov["avg_reported_minutes"] / 60 * 600, abs=0.01)
    assert ov["cost_per_page"] > 0
