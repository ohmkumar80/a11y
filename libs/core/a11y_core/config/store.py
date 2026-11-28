"""Versioned, scoped, audited settings store with a Redis read cache.

Reads  (API + workers): ``a11y_app`` role, read-only on ``setting_versions``.
Writes (admin only)   : ``a11y_admin`` role through ``admin_session`` - every change is
                        audit-logged with who/why, serialised per setting by an advisory lock.
Cache : Redis holds the current row per (key, scope, scope_id). A write deletes the entry after
        commit and every entry has a short TTL, so API and workers see changes within seconds
        with no redeploy. Redis being down degrades to direct DB reads, never to stale config.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import admin_session, app_engine, tenant_session
from ..models import AuditLog, SettingVersion
from ..settings import get_settings
from .registry import RESOLUTION_ORDER, GuardrailError, Scope, SettingDef, get_def, redact

log = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 30


@dataclass(frozen=True)
class Effective:
    key: str
    value: BaseModel
    scope: Scope | None  # None => the code default
    scope_id: str
    version: int | None

    @property
    def source(self) -> str:
        """Human-readable origin, e.g. "plan GROWTH (v3)" - shown next to the value in /admin."""
        if self.scope is None:
            return "default"
        where = self.scope.value if not self.scope_id else f"{self.scope.value} {self.scope_id}"
        return f"{where} (v{self.version})"

    @property
    def ref(self) -> str:
        """Compact reference a job stores so the exact config it ran with is reproducible."""
        return f"{self.key}@{self.scope.value if self.scope else 'default'}:{self.scope_id}:v{self.version}"


def _paths(a: Any, b: Any, prefix: str = "") -> list[str]:
    """JSON paths that differ. Values are never included, so secrets cannot leak via audit."""
    if isinstance(a, dict) and isinstance(b, dict):
        if a.get("$secret") and b.get("$secret"):
            return [] if a.get("ct") == b.get("ct") else [prefix or "/"]
        out: list[str] = []
        for k in sorted(set(a) | set(b)):
            out += _paths(a.get(k), b.get(k), f"{prefix}/{k}")
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            out += _paths(x, y, f"{prefix}/{i}")
        return out
    return [] if a == b else [prefix or "/"]


class ConfigService:
    def __init__(self, redis: Redis | None = None) -> None:
        self._redis = redis

    # -- cache ---------------------------------------------------------------------------------
    def _r(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(get_settings().redis_url)
        return self._redis

    @staticmethod
    def _ck(key: str, scope: Scope, scope_id: str) -> str:
        return f"cfg:{key}|{scope.value}|{scope_id}"

    async def _invalidate(self, key: str, scope: Scope, scope_id: str) -> None:
        try:
            await self._r().delete(self._ck(key, scope, scope_id))
        except Exception:  # noqa: BLE001
            log.warning(
                "config cache invalidation failed; entries expire in %ss", CACHE_TTL_SECONDS
            )

    # -- reads -----------------------------------------------------------------------------------
    async def _current(
        self, key: str, scope: Scope, scope_id: str, org_id: uuid.UUID | None
    ) -> tuple[int, dict] | None:
        ck = self._ck(key, scope, scope_id)
        try:
            hit = await self._r().get(ck)
            if hit is not None:
                d = json.loads(hit)
                return None if d is None else (d["v"], d["val"])
        except Exception:  # noqa: BLE001
            log.warning("config cache read failed; falling back to the database")
        sql = text(
            "SELECT version, value FROM setting_versions "
            "WHERE key=:k AND scope=:s AND scope_id=:i AND status='published' "
            "ORDER BY published_at DESC, version DESC LIMIT 1"
        )
        params = {"k": key, "s": scope.value, "i": scope_id}
        if scope is Scope.ORG:
            assert org_id is not None
            async with tenant_session(org_id) as db:
                row = (await db.execute(sql, params)).first()
        else:
            async with app_engine().connect() as conn:
                row = (await conn.execute(sql, params)).first()
        found = (row.version, row.value) if row else None
        try:
            await self._r().set(
                ck,
                json.dumps(None if found is None else {"v": found[0], "val": found[1]}),
                ex=CACHE_TTL_SECONDS,
            )
        except Exception:  # noqa: BLE001
            log.warning("config cache write failed")
        return found

    async def effective(
        self, key: str, *, org_id: uuid.UUID | None = None, plan_id: str | None = None
    ) -> Effective:
        """Most specific published value: org -> plan -> global -> code default."""
        d = get_def(key)
        want = {Scope.ORG: str(org_id) if org_id else None, Scope.PLAN: plan_id, Scope.GLOBAL: ""}
        for scope in RESOLUTION_ORDER:
            sid = want[scope]
            if sid is None or scope not in d.scopes:
                continue
            cur = await self._current(key, scope, sid, org_id)
            if cur:
                return Effective(key, d.model.model_validate(cur[1]), scope, sid, cur[0])
        return Effective(key, d.default, None, "", None)

    # -- writes (admin) ---------------------------------------------------------------------------
    @staticmethod
    def _check_target(d: SettingDef, scope: Scope, scope_id: str) -> uuid.UUID | None:
        if scope not in d.scopes:
            allowed = ", ".join(sorted(s.value for s in d.scopes))
            raise GuardrailError(f"{d.key} can only be set at: {allowed}.")
        if scope is Scope.GLOBAL:
            if scope_id:
                raise GuardrailError("The global scope has no scope id.")
            return None
        if not scope_id:
            raise GuardrailError(f"Scope {scope.value} needs an id.")
        if scope is Scope.ORG:
            try:
                return uuid.UUID(scope_id)
            except ValueError:
                raise GuardrailError("Organization ids are UUIDs.") from None
        return None

    @staticmethod
    async def _lock(db: AsyncSession, key: str, scope: Scope, scope_id: str) -> None:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:l, 0))"),
            {"l": f"cfg|{key}|{scope.value}|{scope_id}"},
        )

    @staticmethod
    async def _latest_published(
        db: AsyncSession, key: str, scope: Scope, scope_id: str
    ) -> SettingVersion | None:
        return (
            await db.execute(
                select(SettingVersion)
                .where(
                    SettingVersion.key == key,
                    SettingVersion.scope == scope.value,
                    SettingVersion.scope_id == scope_id,
                    SettingVersion.status == "published",
                )
                .order_by(SettingVersion.published_at.desc(), SettingVersion.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _next_version(db: AsyncSession, key: str, scope: Scope, scope_id: str) -> int:
        return (
            await db.execute(
                text(
                    "SELECT coalesce(max(version), 0) + 1 FROM setting_versions "
                    "WHERE key=:k AND scope=:s AND scope_id=:i"
                ),
                {"k": key, "s": scope.value, "i": scope_id},
            )
        ).scalar_one()

    @staticmethod
    def _require_comment(comment: str) -> str:
        if not comment or not comment.strip():
            raise GuardrailError("Say why you are making this change.")
        return comment.strip()

    async def save(
        self,
        key: str,
        scope: Scope,
        scope_id: str,
        raw: Any,
        *,
        comment: str,
        actor: uuid.UUID | None,
        publish: bool = True,
    ) -> SettingVersion:
        """Validate and store a new version; ``publish=False`` leaves it as a draft."""
        d = get_def(key)
        comment = self._require_comment(comment)
        org_id = self._check_target(d, scope, scope_id)
        async with admin_session(actor_user_id=actor, reason=comment, action="setting.write") as db:
            await self._lock(db, key, scope, scope_id)
            prev = await self._latest_published(db, key, scope, scope_id)
            prev_raw = prev.value if prev else None
            stored = d.validate(raw, prev_raw)
            row = SettingVersion(
                key=key,
                scope=scope.value,
                scope_id=scope_id,
                organization_id=org_id,
                version=await self._next_version(db, key, scope, scope_id),
                value=stored,
                status="published" if publish else "draft",
                comment=comment,
                actor_user_id=actor,
                published_at=func.clock_timestamp() if publish else None,
            )
            db.add(row)
            await db.flush()
            await db.refresh(row)
            db.add(
                AuditLog(
                    organization_id=org_id,
                    actor_user_id=actor,
                    action="setting.published" if publish else "setting.drafted",
                    detail={
                        "key": key,
                        "scope": scope.value,
                        "scope_id": scope_id,
                        "version": row.version,
                        "comment": comment,
                        "changed": _paths(prev_raw, stored) if prev_raw is not None else ["/"],
                    },
                )
            )
        if publish:
            await self._invalidate(key, scope, scope_id)
        return row

    async def publish(
        self,
        key: str,
        scope: Scope,
        scope_id: str,
        version: int,
        *,
        comment: str,
        actor: uuid.UUID | None,
    ) -> SettingVersion:
        d = get_def(key)
        comment = self._require_comment(comment)
        org_id = self._check_target(d, scope, scope_id)
        async with admin_session(actor_user_id=actor, reason=comment, action="setting.write") as db:
            await self._lock(db, key, scope, scope_id)
            row = (
                await db.execute(
                    select(SettingVersion).where(
                        SettingVersion.key == key,
                        SettingVersion.scope == scope.value,
                        SettingVersion.scope_id == scope_id,
                        SettingVersion.version == version,
                    )
                )
            ).scalar_one_or_none()
            if row is None or row.status != "draft":
                raise GuardrailError("That version is not an unpublished draft.")
            prev = await self._latest_published(db, key, scope, scope_id)
            d.validate(row.value, prev.value if prev else None, trusted=True)  # guardrails again
            await db.execute(
                update(SettingVersion)
                .where(SettingVersion.id == row.id)
                .values(status="published", published_at=func.clock_timestamp())
            )
            db.add(
                AuditLog(
                    organization_id=org_id,
                    actor_user_id=actor,
                    action="setting.published",
                    detail={
                        "key": key,
                        "scope": scope.value,
                        "scope_id": scope_id,
                        "version": version,
                        "comment": comment,
                        "changed": _paths(prev.value if prev else None, row.value),
                    },
                )
            )
            await db.refresh(row)
        await self._invalidate(key, scope, scope_id)
        return row

    async def rollback(
        self,
        key: str,
        scope: Scope,
        scope_id: str,
        to_version: int,
        *,
        comment: str,
        actor: uuid.UUID | None,
    ) -> SettingVersion:
        """Publish a copy of an earlier version as a NEW version (history is never rewritten)."""
        d = get_def(key)
        comment = self._require_comment(comment)
        org_id = self._check_target(d, scope, scope_id)
        async with admin_session(actor_user_id=actor, reason=comment, action="setting.write") as db:
            await self._lock(db, key, scope, scope_id)
            old = (
                await db.execute(
                    select(SettingVersion).where(
                        SettingVersion.key == key,
                        SettingVersion.scope == scope.value,
                        SettingVersion.scope_id == scope_id,
                        SettingVersion.version == to_version,
                        SettingVersion.status == "published",
                    )
                )
            ).scalar_one_or_none()
            if old is None:
                raise GuardrailError("There is no published version with that number.")
            prev = await self._latest_published(db, key, scope, scope_id)
            stored = d.validate(old.value, prev.value if prev else None, trusted=True)
            row = SettingVersion(
                key=key,
                scope=scope.value,
                scope_id=scope_id,
                organization_id=org_id,
                version=await self._next_version(db, key, scope, scope_id),
                value=stored,
                status="published",
                comment=comment,
                actor_user_id=actor,
                restored_from=to_version,
                published_at=func.clock_timestamp(),
            )
            db.add(row)
            await db.flush()
            await db.refresh(row)
            db.add(
                AuditLog(
                    organization_id=org_id,
                    actor_user_id=actor,
                    action="setting.rolled_back",
                    detail={
                        "key": key,
                        "scope": scope.value,
                        "scope_id": scope_id,
                        "version": row.version,
                        "restored_from": to_version,
                        "comment": comment,
                    },
                )
            )
        await self._invalidate(key, scope, scope_id)
        return row

    async def history(
        self, key: str, scope: Scope, scope_id: str, *, actor: uuid.UUID | None, limit: int = 50
    ) -> list[dict]:
        d = get_def(key)
        self._check_target(d, scope, scope_id)
        async with admin_session(
            actor_user_id=actor, reason=f"read history of {key}", action="setting.read"
        ) as db:
            rows = (
                (
                    await db.execute(
                        select(SettingVersion)
                        .where(
                            SettingVersion.key == key,
                            SettingVersion.scope == scope.value,
                            SettingVersion.scope_id == scope_id,
                        )
                        .order_by(SettingVersion.version.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [
            {
                "version": r.version,
                "status": r.status,
                "comment": r.comment,
                "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
                "created_at": r.created_at.isoformat(),
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "restored_from": r.restored_from,
                "value": redact(r.value),
            }
            for r in rows
        ]


_service: ConfigService | None = None


def get_config() -> ConfigService:
    global _service
    if _service is None:
        _service = ConfigService()
    return _service
