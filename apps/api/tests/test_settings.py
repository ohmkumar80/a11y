"""Settings framework: scopes, secrets, versioning, rollback, guardrails, permissions, cache."""

import asyncio
import json
import uuid

import pytest
from a11y_core.config import ConfigService, GuardrailError, Scope, get_config
from a11y_core.config.store import _paths
from a11y_core.db import app_engine, tenant_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .conftest import make_org, sql

KEY = "billing.trial"
PROVIDERS = "ai.providers"


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


def trial(days: int, **kw) -> dict:
    return {"length_days": days, **kw}


async def test_default_when_nothing_published():
    e = await get_config().effective(KEY)
    assert (e.value.length_days, e.scope, e.source) == (14, None, "default")


async def test_publish_changes_effective_value_immediately_and_records_version():
    cfg = get_config()
    await cfg.effective(KEY)  # warm the (negative) cache: a write must still win
    await cfg.save(KEY, Scope.GLOBAL, "", trial(21), comment="test-1", actor=None)
    e = await cfg.effective(KEY)
    assert (e.value.length_days, e.scope, e.version) == (21, Scope.GLOBAL, 1)
    assert e.ref == f"{KEY}@global::v1"


async def test_scope_resolution_org_over_global():
    cfg = get_config()
    org, *_ = await make_org()
    other, *_ = await make_org()
    await cfg.save(KEY, Scope.GLOBAL, "", trial(14), comment="test-g", actor=None)
    await cfg.save(KEY, Scope.ORG, str(org), trial(60), comment="test-o", actor=None)
    assert (await cfg.effective(KEY, org_id=org)).value.length_days == 60
    assert (await cfg.effective(KEY, org_id=org)).source.startswith(f"org {org}")
    assert (await cfg.effective(KEY, org_id=other)).value.length_days == 14
    assert (await cfg.effective(KEY)).value.length_days == 14


async def test_org_override_is_invisible_to_other_tenants_in_sql():
    cfg = get_config()
    a, *_ = await make_org()
    b, *_ = await make_org()
    await cfg.save(KEY, Scope.ORG, str(a), trial(60), comment="test-o", actor=None)
    q = text("SELECT count(*) FROM setting_versions WHERE scope='org'")
    async with tenant_session(b) as db:
        assert (await db.execute(q)).scalar_one() == 0
    async with tenant_session(a) as db:
        assert (await db.execute(q)).scalar_one() == 1
    async with app_engine().connect() as c:  # no tenant at all
        assert (await c.execute(q)).scalar_one() == 0


async def test_unsupported_scope_and_bad_values_are_rejected():
    cfg = get_config()
    with pytest.raises(GuardrailError):
        await cfg.save(KEY, Scope.PLAN, "GROWTH", trial(14), comment="test-x", actor=None)
    with pytest.raises(GuardrailError):
        await cfg.save(KEY, Scope.GLOBAL, "", trial(0), comment="test-x", actor=None)
    with pytest.raises(GuardrailError):  # a reason is mandatory
        await cfg.save(KEY, Scope.GLOBAL, "", trial(14), comment="  ", actor=None)
    with pytest.raises(GuardrailError):
        await cfg.save(KEY, Scope.ORG, "not-a-uuid", trial(14), comment="test-x", actor=None)


async def test_draft_is_not_effective_until_published():
    cfg = get_config()
    await cfg.save(KEY, Scope.GLOBAL, "", trial(30), comment="test-d", actor=None, publish=False)
    assert (await cfg.effective(KEY)).value.length_days == 14
    await cfg.publish(KEY, Scope.GLOBAL, "", 1, comment="test-p", actor=None)
    assert (await cfg.effective(KEY)).value.length_days == 30
    with pytest.raises(GuardrailError):  # already published
        await cfg.publish(KEY, Scope.GLOBAL, "", 1, comment="test-p", actor=None)


async def test_rollback_publishes_a_new_version_and_keeps_history():
    cfg = get_config()
    for days in (10, 20, 30):
        await cfg.save(KEY, Scope.GLOBAL, "", trial(days), comment=f"test-{days}", actor=None)
    row = await cfg.rollback(KEY, Scope.GLOBAL, "", 1, comment="test-undo", actor=None)
    assert (row.version, row.restored_from) == (4, 1)
    assert (await cfg.effective(KEY)).value.length_days == 10
    hist = await cfg.history(KEY, Scope.GLOBAL, "", actor=None)
    assert [h["version"] for h in hist] == [4, 3, 2, 1]
    assert hist[0]["restored_from"] == 1
    with pytest.raises(GuardrailError):
        await cfg.rollback(KEY, Scope.GLOBAL, "", 99, comment="test-x", actor=None)


async def test_concurrent_writes_get_distinct_versions_and_last_publish_wins():
    cfg = get_config()
    rows = await asyncio.gather(
        *[
            cfg.save(KEY, Scope.GLOBAL, "", trial(d), comment=f"test-c{d}", actor=None)
            for d in range(10, 20)
        ]
    )
    assert sorted(r.version for r in rows) == list(range(1, 11))
    newest = max(rows, key=lambda r: r.published_at)
    assert (await cfg.effective(KEY)).version == newest.version


async def test_changes_are_audited_with_paths_but_not_values():
    cfg = get_config()
    uid = uuid.uuid4()
    await cfg.save(KEY, Scope.GLOBAL, "", trial(21), comment="test-a1", actor=uid)
    await cfg.save(KEY, Scope.GLOBAL, "", trial(22, grace_days=3), comment="test-a2", actor=uid)
    rows = await sql(
        "SELECT detail FROM audit_log WHERE actor_user_id=$1 AND action='setting.published' "
        "ORDER BY created_at",
        uid,
    )
    await sql("DELETE FROM audit_log WHERE actor_user_id=$1", uid)
    d = [json.loads(r["detail"]) for r in rows]
    assert d[1]["changed"] == ["/grace_days", "/length_days"] and d[1]["comment"] == "test-a2"


# --- secrets ----------------------------------------------------------------------------------


def provider(pid="p1", key: dict | None = None, **kw) -> dict:
    return {
        "id": pid,
        "type": "openai",
        "display_name": pid,
        "api_key": key or {"$secret": True},
        **kw,
    }


async def test_secret_is_encrypted_at_rest_write_only_and_decryptable_internally():
    cfg = get_config()
    key = "sk-test-0123456789abcdef-WXYZ"
    await cfg.save(
        PROVIDERS,
        Scope.GLOBAL,
        "",
        {"items": [provider(key={"$secret": True, "plaintext": key})]},
        comment="test-s",
        actor=None,
    )
    # at rest
    async with app_engine().connect() as c:
        raw = (
            await c.execute(
                text("SELECT value::text FROM setting_versions WHERE key=:k"), {"k": PROVIDERS}
            )
        ).scalar_one()
    assert key not in raw and 'plaintext": null' in raw.replace(": ", ": ")
    # the API view
    from a11y_core.config import redact

    e = await cfg.effective(PROVIDERS)
    red = redact(e.value.model_dump(mode="json", by_alias=True))
    assert red["items"][0]["api_key"] == {"$secret": True, "set": True, "hint": "••••WXYZ"}
    assert "ct" not in json.dumps(red) and key not in json.dumps(red)
    # internal use
    assert e.value.items[0].api_key.value() == key


async def test_resubmitting_without_plaintext_keeps_the_secret_and_new_plaintext_replaces_it():
    cfg = get_config()
    k1, k2 = "sk-aaaaaaaaaaaaaaaa-1111", "sk-bbbbbbbbbbbbbbbb-2222"
    await cfg.save(
        PROVIDERS,
        Scope.GLOBAL,
        "",
        {"items": [provider(key={"$secret": True, "plaintext": k1})]},
        comment="test-s1",
        actor=None,
    )
    await cfg.save(
        PROVIDERS,
        Scope.GLOBAL,
        "",
        {"items": [provider(display_name="renamed")]},
        comment="test-s2",
        actor=None,
    )
    assert (await cfg.effective(PROVIDERS)).value.items[0].api_key.value() == k1
    await cfg.save(
        PROVIDERS,
        Scope.GLOBAL,
        "",
        {"items": [provider(key={"$secret": True, "plaintext": k2})]},
        comment="test-s3",
        actor=None,
    )
    assert (await cfg.effective(PROVIDERS)).value.items[0].api_key.value() == k2
    # rolling back restores the old secret too
    await cfg.rollback(PROVIDERS, Scope.GLOBAL, "", 1, comment="test-s4", actor=None)
    assert (await cfg.effective(PROVIDERS)).value.items[0].api_key.value() == k1


async def test_secret_matched_by_item_id_when_list_is_reordered():
    cfg = get_config()
    ka, kb = "sk-aaaaaaaaaaaaaaaa-AAAA", "sk-bbbbbbbbbbbbbbbb-BBBB"
    await cfg.save(
        PROVIDERS,
        Scope.GLOBAL,
        "",
        {
            "items": [
                provider("a", {"$secret": True, "plaintext": ka}),
                provider("b", {"$secret": True, "plaintext": kb}),
            ]
        },
        comment="test-r1",
        actor=None,
    )
    await cfg.save(
        PROVIDERS,
        Scope.GLOBAL,
        "",
        {"items": [provider("b"), provider("a")]},
        comment="test-r2",
        actor=None,
    )
    got = {p.id: p.api_key.value() for p in (await cfg.effective(PROVIDERS)).value.items}
    assert got == {"a": ka, "b": kb}


async def test_client_cannot_inject_ciphertext():
    cfg = get_config()
    await cfg.save(
        PROVIDERS,
        Scope.GLOBAL,
        "",
        {"items": [provider(key={"$secret": True, "ct": "gAAAAA-forged", "hint": "hack"})]},
        comment="test-i",
        actor=None,
    )
    sec = (await cfg.effective(PROVIDERS)).value.items[0].api_key
    assert not sec.is_set and sec.hint is None


async def test_duplicate_provider_ids_rejected():
    with pytest.raises(GuardrailError):
        await get_config().save(
            PROVIDERS,
            Scope.GLOBAL,
            "",
            {"items": [provider("x"), provider("x")]},
            comment="test-u",
            actor=None,
        )


# --- permissions ------------------------------------------------------------------------------


async def test_app_role_cannot_write_settings():
    a, *_ = await make_org()
    for stmt in (
        "INSERT INTO setting_versions (id,key,scope,scope_id,version,value,status,comment) "
        "VALUES (gen_random_uuid(),'billing.trial','global','',1,'{}','published','test-hack')",
        "UPDATE setting_versions SET status='draft'",
        "DELETE FROM setting_versions",
    ):
        with pytest.raises(DBAPIError):
            async with tenant_session(a) as db:
                await db.execute(text(stmt))


async def test_audit_paths_helper_never_returns_values():
    sec_a = {"$secret": True, "ct": "x", "hint": "1"}
    sec_b = {"$secret": True, "ct": "y", "hint": "1"}
    assert _paths({"k": sec_a, "n": 1}, {"k": sec_b, "n": 1}) == ["/k"]
    assert _paths({"k": sec_a}, {"k": dict(sec_a)}) == []


async def test_cache_outage_falls_back_to_database():
    svc = ConfigService(redis=_BrokenRedis())  # type: ignore[arg-type]
    await get_config().save(KEY, Scope.GLOBAL, "", trial(45), comment="test-b", actor=None)
    assert (await svc.effective(KEY)).value.length_days == 45


class _BrokenRedis:
    async def get(self, *_):
        raise ConnectionError

    set = delete = get
