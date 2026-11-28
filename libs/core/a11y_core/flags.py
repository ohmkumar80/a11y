"""Feature flags (PROJECT_PLAN 3.11): switch a feature off, or on for some plans or organisations only, without a deploy.

A flag is one boolean field of the ``flags`` setting, so everything the settings framework gives is free: scopes
(global, plan, organisation), versions, audit, rollback, and a generated admin form. Code asks
``await enabled("name", org_id=..., plan_id=...)``. A flag that is off must refuse cleanly (``feature_disabled``), never
half-work: the places that check them are listed in ``FLAG_USES``."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from .config import get_config
from .config.registry import Scope, SettingDef, register


class FeatureFlags(BaseModel):
    public_api: bool = Field(True, description="The public API (/v1) and API key creation")
    webhooks: bool = Field(True, description="Outbound webhooks")
    vpat: bool = Field(True, description="VPAT drafting and export")
    crawl_scans: bool = Field(True, description="Scanning more than one page (crawl mode)")
    notification_center: bool = Field(True, description="The in-app notification centre")
    documents: bool = Field(True, description="Document uploads and audits (PDF, Word, PowerPoint, EPUB)")
    human_review: bool = Field(True, description="Asking a person on our team to check a document")


FLAG_USES = {
    "public_api": "a11y_api.api_auth.authenticate, routers/org_api_keys.create_key",
    "webhooks": "a11y_core.webhooks.emit_event, routers/org_webhooks",
    "vpat": "routers/reports.create_vpat, export_vpat",
    "crawl_scans": "routers/scans.create_scan",
    "notification_center": "routers/notifications",
    "documents": "routers/documents (every endpoint), a11y_core.documents.accept_upload",
    "human_review": "routers/documents (review endpoints), a11y_core.document_reviews.request_review",
}

register(
    SettingDef(
        key="flags",
        model=FeatureFlags,
        default=FeatureFlags(),
        description="Switch features off for everyone, or for one plan or organisation (use the scope selector). "
        "A feature that is off tells people so, instead of failing.",
        scopes=frozenset({Scope.GLOBAL, Scope.PLAN, Scope.ORG}),
        owner_role="PLATFORM_OWNER",
        tags=("flags",),
    )
)


async def effective_flags(
    org_id: uuid.UUID | None = None, plan_id: str | None = None
) -> FeatureFlags:
    return (await get_config().effective("flags", org_id=org_id, plan_id=plan_id)).value


async def enabled(
    name: str, *, org_id: uuid.UUID | None = None, plan_id: str | None = None
) -> bool:
    return bool(getattr(await effective_flags(org_id, plan_id), name))
