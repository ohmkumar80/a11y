"""An organisation's data policy, resolved (ADR 0024).

Three layers, strictest answer wins:
  1. the platform: which storage regions exist (`data.regions`) and the retention ceiling (`documents.retention`);
  2. the platform, per plan or organisation: which controls an organisation may use (`data.controls`);
  3. the organisation's own choices (`data.policy`), made by its administrator.

`effective()` is the ONE place that combines them. Everything that stores, keeps, shows to a person, or sends to an AI
provider a customer's file asks it. An organisation whose plan no longer allows something it once chose is quietly held to
the limit (never to a looser one), and its page says so."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text

from . import billing
from .config import GuardrailError, Scope, get_config
from .config.definitions import AIProvider, DataControls, OrgDataPolicy, StorageRegion
from .db import tenant_session
from .models import AuditLog, Document, DocumentStatus
from .storage import regions

log = logging.getLogger(__name__)


class PolicyRefused(Exception):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field, self.message = field, message


@dataclass(frozen=True)
class Effective:
    retention_days: int
    retention_ceiling: int
    region: StorageRegion
    default_region_id: str
    offered_regions: tuple[StorageRegion, ...]
    allow_human_review: bool
    ai_on_documents: bool
    ai_require_zero_retention: bool
    ai_regions: tuple[str, ...]
    controls: DataControls
    chosen: OrgDataPolicy


async def plan_of(org_id: uuid.UUID) -> str:
    async with tenant_session(org_id) as db:
        return (await billing.load_subscription(db)).plan_id


async def effective(org_id: uuid.UUID, plan_id: str | None = None) -> Effective:
    plan_id = plan_id or await plan_of(org_id)
    cfg = get_config()
    controls = (await cfg.effective("data.controls", org_id=org_id, plan_id=plan_id)).value
    chosen = (await cfg.effective("data.policy", org_id=org_id)).value
    ceiling = (
        await cfg.effective("documents.retention", org_id=org_id, plan_id=plan_id)
    ).value.retention_days
    regs, default_id = await regions()

    days = ceiling
    if controls.can_set_retention and chosen.retention_days:
        days = max(controls.min_retention_days, min(ceiling, chosen.retention_days))
    region = regs.get(default_id) or regs["default"]
    if controls.can_choose_region and chosen.storage_region:
        r = regs.get(chosen.storage_region)
        if r is not None and r.is_active:
            region = r
    return Effective(
        retention_days=days,
        retention_ceiling=ceiling,
        region=region,
        default_region_id=default_id,
        offered_regions=tuple(r for r in regs.values() if r.is_active),
        allow_human_review=chosen.allow_human_review if controls.can_block_human_review else True,
        ai_on_documents=bool(chosen.ai_on_documents and controls.can_enable_ai),
        ai_require_zero_retention=chosen.ai_require_zero_retention,
        ai_regions=tuple(chosen.ai_regions),
        controls=controls,
        chosen=chosen,
    )


def ai_provider_problem(eff: Effective, provider: AIProvider) -> str | None:
    """Why this provider may not receive the organisation's documents, or None if it may."""
    if eff.ai_require_zero_retention and not provider.data_policy.zero_retention:
        return f"{provider.display_name} does not promise to keep nothing it receives"
    if eff.ai_regions and not set(eff.ai_regions) & {
        r.lower() for r in provider.data_policy.processing_regions
    }:
        return f"{provider.display_name} does not process in {', '.join(eff.ai_regions)}"
    return None


def check_choices(new: OrgDataPolicy, eff: Effective) -> None:
    """Refuse a choice the organisation's plan does not let it make, with the reason. Raises PolicyRefused."""
    c = eff.controls
    if new.retention_days is not None:
        if not c.can_set_retention and new.retention_days != eff.chosen.retention_days:
            raise PolicyRefused(
                "retention_days", "Your plan does not let you choose how long files are kept."
            )
        if new.retention_days < c.min_retention_days:
            raise PolicyRefused(
                "retention_days",
                f"Files must be kept for at least {c.min_retention_days} day{'s' if c.min_retention_days != 1 else ''}.",
            )
        if new.retention_days > eff.retention_ceiling:
            raise PolicyRefused(
                "retention_days",
                f"Your plan keeps files for at most {eff.retention_ceiling} days. Choose a shorter time.",
            )
    if new.storage_region and new.storage_region != eff.chosen.storage_region:
        if not c.can_choose_region:
            raise PolicyRefused(
                "storage_region", "Your plan does not let you choose where files are stored."
            )
        if new.storage_region not in {r.id for r in eff.offered_regions}:
            raise PolicyRefused("storage_region", "That region is not available.")
    if new.ai_on_documents and not eff.chosen.ai_on_documents and not c.can_enable_ai:
        raise PolicyRefused(
            "ai_on_documents", "Your plan does not include using AI on your documents."
        )
    if (
        not new.allow_human_review
        and eff.chosen.allow_human_review
        and not c.can_block_human_review
    ):
        raise PolicyRefused(
            "allow_human_review", "Your plan does not let you switch off human review."
        )


async def save(org_id: uuid.UUID, user_id: uuid.UUID, new: OrgDataPolicy) -> tuple[Effective, int]:
    """Validate against what the plan allows, store the choices, and apply a shorter retention to files already stored.
    Returns the new effective policy and how many existing files now expire sooner."""
    before = await effective(org_id)
    check_choices(new, before)
    try:
        await get_config().save(
            "data.policy",
            Scope.ORG,
            str(org_id),
            new.model_dump(mode="json"),
            comment="Changed by an organisation administrator",
            actor=user_id,
        )
    except GuardrailError as e:
        raise PolicyRefused("", str(e)) from None
    after = await effective(org_id)
    shortened = 0
    if after.retention_days < before.retention_days:
        async with tenant_session(org_id) as db:
            res = await db.execute(
                text(
                    "UPDATE documents SET expires_at = LEAST(expires_at, created_at + make_interval(days => :d)) "
                    "WHERE status <> 'DELETED' AND expires_at > created_at + make_interval(days => :d)"
                ),
                {"d": after.retention_days},
            )
            shortened = res.rowcount or 0
    async with tenant_session(org_id) as db:
        db.add(
            AuditLog(
                organization_id=org_id,
                actor_user_id=user_id,
                action="data_policy.changed",
                detail={
                    "retention_days": after.retention_days,
                    "region": after.region.id,
                    "allow_human_review": after.allow_human_review,
                    "ai_on_documents": after.ai_on_documents,
                    "ai_require_zero_retention": after.ai_require_zero_retention,
                    "ai_regions": list(after.ai_regions),
                    "existing_files_shortened": shortened,
                },
            )
        )
    return after, shortened


async def delete_all_documents(org_id: uuid.UUID, user_id: uuid.UUID) -> int:
    """Erase every stored file now (the organisation's right to deletion). Returns how many."""
    from . import documents  # noqa: PLC0415

    n = 0
    while True:
        async with tenant_session(org_id) as db:
            batch = list(
                (
                    await db.execute(
                        select(Document).where(Document.status != DocumentStatus.DELETED).limit(50)
                    )
                ).scalars()
            )
            if not batch:
                break
            for d in batch:
                await documents.erase(db, d, "customer")
                n += 1
    async with tenant_session(org_id) as db:
        db.add(
            AuditLog(
                organization_id=org_id,
                actor_user_id=user_id,
                action="documents.deleted_all",
                detail={"count": n},
            )
        )
    return n
