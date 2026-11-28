"""Phase 0 tables. Plans, coupons, ledgers etc. arrive in Phase 1.

Every table that carries ``organization_id`` MUST have RLS enabled and forced, and a
policy; ``tests/test_rls_isolation.py`` fails the build if one is missing.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID  # noqa: I001
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Role(enum.StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    COMPANY_ADMIN = "COMPANY_ADMIN"
    STANDARD_USER = "STANDARD_USER"


class TokenKind(enum.StrEnum):
    REFRESH = "REFRESH"
    EMAIL_VERIFY = "EMAIL_VERIFY"
    PASSWORD_RESET = "PASSWORD_RESET"  # noqa: S105
    INVITE = "INVITE"


def _values(e: type[enum.StrEnum]) -> str:
    return ", ".join(f"'{m.value}'" for m in e)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN ({_values(Role)})", name="ck_users_role"),
        CheckConstraint(
            "(role = 'SUPER_ADMIN') = (organization_id IS NULL)", name="ck_users_org_role"
        ),
        # Email is globally unique (one login identity), stored lower-cased by the app.
        Index("uq_users_email", "email", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Two-step verification (a11y_core.mfa). The secret is encrypted at rest; recovery codes are stored hashed.
    mfa_secret_ct: Mapped[str | None] = mapped_column(Text)
    mfa_pending_ct: Mapped[str | None] = mapped_column(
        Text
    )  # secret shown during enrolment, not yet confirmed
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_last_step: Mapped[int] = mapped_column(BigInteger, server_default="0")
    mfa_recovery: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    mfa_failed: Mapped[int] = mapped_column(Integer, server_default="0")
    mfa_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthToken(Base):
    """Refresh tokens and one-time email tokens. Only the SHA-256 hash is stored."""

    __tablename__ = "auth_tokens"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_values(TokenKind)})", name="ck_auth_tokens_kind"),
        Index("ix_auth_tokens_user_kind", "user_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Refresh-token rotation: all tokens from one login share a family; reuse revokes the family.
    family_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Did this session pass two-step verification? Lets a refresh be refused if policy later requires MFA.
    mfa_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # Invites only:
    invited_email: Mapped[str | None] = mapped_column(String(320))
    invited_role: Mapped[str | None] = mapped_column(String(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Append-only (UPDATE/DELETE revoked from the app role in the migration)."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SettingVersion(Base):
    """Append-only history of admin-configurable settings (PROJECT_PLAN 3.11.1).

    Written ONLY by the ``a11y_admin`` role (the app role is read-only here); the effective
    value is the most recently *published* row for (key, scope, scope_id). Rollback publishes a
    copy of an older value as a new version, so history is never rewritten. Secret fields are
    stored as ciphertext. ``organization_id`` is set only for scope='org' so RLS can keep one
    tenant's overrides invisible to others.
    """

    __tablename__ = "setting_versions"
    __table_args__ = (
        UniqueConstraint("key", "scope", "scope_id", "version", name="uq_setting_versions_ver"),
        CheckConstraint("scope IN ('global', 'plan', 'org')", name="ck_setting_versions_scope"),
        CheckConstraint("status IN ('draft', 'published')", name="ck_setting_versions_status"),
        CheckConstraint(
            "(scope = 'org') = (organization_id IS NOT NULL)", name="ck_setting_versions_org"
        ),
        Index("ix_setting_versions_current", "key", "scope", "scope_id", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[str] = mapped_column(String(64), server_default="")
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    value: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    restored_from: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Plans, subscriptions, quotas, coupons (Phase 1 SaaS core) ---------------------------------


class SubscriptionStatus(enum.StrEnum):
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    LOCKED_READ_ONLY = "LOCKED_READ_ONLY"


class ReservationStatus(enum.StrEnum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class Plan(Base):
    """Platform-wide (no tenant). Editable only by the admin role."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # TRIAL, STARTER, ...
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, server_default="")
    is_public: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")


class PlanEntitlement(Base):
    """One row per (plan, feature). ``limit_value`` NULL = unlimited. New quotas/features are
    new rows, never schema changes."""

    __tablename__ = "plan_entitlements"
    __table_args__ = (
        CheckConstraint("limit_value IS NULL OR limit_value >= 0", name="ck_ent_limit"),
    )

    plan_id: Mapped[str] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True
    )
    feature_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    limit_value: Mapped[int | None] = mapped_column(BigInteger)


class PlanPrice(Base):
    __tablename__ = "plan_prices"
    __table_args__ = (
        CheckConstraint("cycle IN ('MONTHLY', 'ANNUAL')", name="ck_price_cycle"),
        CheckConstraint("amount_minor >= 0", name="ck_price_amount"),
    )

    plan_id: Mapped[str] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True
    )
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    cycle: Mapped[str] = mapped_column(String(10), primary_key=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)  # paise / cents


class Coupon(Base):
    """Platform-wide. The app role may only increment ``current_redemptions`` (column grant)."""

    __tablename__ = "coupons"
    __table_args__ = (
        CheckConstraint("discount_type IN ('PERCENTAGE', 'FIXED_INR')", name="ck_coupon_type"),
        CheckConstraint("discount_value > 0", name="ck_coupon_value"),
        CheckConstraint(
            "discount_type <> 'PERCENTAGE' OR discount_value <= 100", name="ck_coupon_pct"
        ),
        CheckConstraint(
            "current_redemptions >= 0 AND (max_redemptions IS NULL OR current_redemptions <= max_redemptions)",
            name="ck_coupon_redemptions",
        ),
        Index("uq_coupons_code", "code", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64))  # stored upper-case
    discount_type: Mapped[str] = mapped_column(String(16))
    discount_value: Mapped[int] = mapped_column(BigInteger)  # percent, or paise for FIXED_INR
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    current_redemptions: Mapped[int] = mapped_column(Integer, server_default="0")
    applicable_plan_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String), server_default=text("'{}'")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    campaign: Mapped[str | None] = mapped_column(
        String(60), index=True
    )  # a batch of codes made together
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Subscription(Base):
    """One per organisation. Plan changes are admin-only (column grants); the app may touch
    status / trial dates / applied coupon."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(f"status IN ({_values(SubscriptionStatus)})", name="ck_sub_status"),
        CheckConstraint("billing_cycle IN ('MONTHLY', 'ANNUAL')", name="ck_sub_cycle"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"))
    status: Mapped[str] = mapped_column(String(24))
    billing_cycle: Mapped[str] = mapped_column(String(10), server_default="MONTHLY")
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # trial_ends_at + grace. The request guard locks at this instant even if no cron has run.
    locks_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_coupon_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("coupons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageLedger(Base):
    """Credits consumed per organisation, feature and calendar month (UTC). Reservations and
    commits both count toward ``used``; releases give it back."""

    __tablename__ = "usage_ledger"
    __table_args__ = (CheckConstraint("used >= 0", name="ck_ledger_used"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    feature_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    period_start: Mapped[datetime] = mapped_column(Date, primary_key=True)
    used: Mapped[int] = mapped_column(BigInteger, server_default="0")


class UsageReservation(Base):
    __tablename__ = "usage_reservations"
    __table_args__ = (
        CheckConstraint(f"status IN ({_values(ReservationStatus)})", name="ck_resv_status"),
        CheckConstraint("amount > 0", name="ck_resv_amount"),
        # job_id makes reserve/commit/release idempotent: a retried job never double-charges.
        UniqueConstraint("organization_id", "feature_key", "job_id", name="uq_resv_job"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    feature_key: Mapped[str] = mapped_column(String(64))
    job_id: Mapped[str] = mapped_column(String(100))
    period_start: Mapped[datetime] = mapped_column(Date)
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CouponRedemption(Base):
    __tablename__ = "coupon_redemptions"
    # One redemption per (coupon, organisation) - enforced by the database, not by a check.
    __table_args__ = (UniqueConstraint("coupon_id", "organization_id", name="uq_redemption"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    coupon_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("coupons.id"))
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    terms: Mapped[dict] = mapped_column(JSONB)  # snapshot of the discount at redemption time
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AIUsage(Base):
    """One row per provider ATTEMPT (failures included, so fallback/error rates are measurable).
    Append-only for the app role. Feeds per-tenant budgets and the FinOps view."""

    __tablename__ = "ai_usage"
    __table_args__ = (CheckConstraint("status IN ('ok', 'error')", name="ck_ai_usage_status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str | None] = mapped_column(String(100))
    task_key: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(8))
    # True when the call used the organisation's own account (not billed to / budgeted by us).
    byok: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    error_class: Mapped[str | None] = mapped_column(String(100))
    tokens_in: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, server_default="0")
    # e.g. ["ai.route.code_fix@global::v3", "ai.models@global::v2", ...] - reproducibility.
    config_refs: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


# --- Web scans ------------------------------------------------------------------------------------


class ScanStatus(enum.StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ScanJob(Base):
    __tablename__ = "scan_jobs"
    __table_args__ = (
        CheckConstraint(f"status IN ({_values(ScanStatus)})", name="ck_scan_status"),
        CheckConstraint("mode IN ('single', 'crawl')", name="ck_scan_mode"),
        Index("ix_scan_jobs_org_created", "organization_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    start_url: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(8), server_default="single")
    max_pages: Mapped[int] = mapped_column(Integer, server_default="1")
    standards: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'"))
    status: Mapped[str] = mapped_column(String(12), server_default="QUEUED")
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_detail: Mapped[str | None] = mapped_column(Text)
    pages_scanned: Mapped[int] = mapped_column(Integer, server_default="0")
    findings_count: Mapped[int] = mapped_column(Integer, server_default="0")
    # Reproducibility: exact engine versions, rule-registry version and config the scan ran with.
    engine_versions: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    rules_version: Mapped[str | None] = mapped_column(String(40))
    config_refs: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScanPage(Base):
    __tablename__ = "scan_pages"
    __table_args__ = (Index("ix_scan_pages_scan", "scan_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10))  # OK | FAILED | BLOCKED
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_detail: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(String(35))
    engines: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    duration_ms: Mapped[int] = mapped_column(Integer, server_default="0")
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PageScreenshot(Base):
    """JPEG of the top of a scanned page, in page pixels. Element positions are the findings' ``rect``s; the UI outlines
    them on this one image instead of us storing a picture per finding. Written once, never edited."""

    __tablename__ = "page_screenshots"
    __table_args__ = (
        UniqueConstraint("page_id", name="uq_screenshot_page"),
        CheckConstraint("size_bytes <= 2000000", name="ck_screenshot_size"),
        Index("ix_page_screenshots_scan", "scan_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_pages.id", ondelete="CASCADE"))
    mime: Mapped[str] = mapped_column(String(20), server_default="image/jpeg")
    content: Mapped[bytes] = mapped_column(deferred=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    page_height: Mapped[int] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScanFinding(Base):
    __tablename__ = "scan_findings"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('violation', 'needs_review', 'best_practice')", name="ck_finding_kind"
        ),
        Index("ix_scan_findings_scan_rule", "scan_id", "canonical_rule_id"),
        Index("ix_scan_findings_scan_kind", "scan_id", "kind", "severity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_pages.id", ondelete="CASCADE"))
    canonical_rule_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(Text)
    sc: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'"))
    kind: Mapped[str] = mapped_column(String(14))
    severity: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[str] = mapped_column(String(8))
    engines: Mapped[list[str]] = mapped_column(ARRAY(String))
    covering: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'"))
    engine_rule_ids: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    xpath: Mapped[str] = mapped_column(Text)
    css: Mapped[str] = mapped_column(Text)
    tag: Mapped[str] = mapped_column(String(40))
    html: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    rect: Mapped[dict | None] = mapped_column(JSONB)
    cluster_key: Mapped[str] = mapped_column(String(16))
    fingerprint: Mapped[str] = mapped_column(String(16))
    help_url: Mapped[str | None] = mapped_column(Text)
    mapped: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class VerifiedDomain(Base):
    """Proof that the organisation controls a site, required before large crawls."""

    __tablename__ = "verified_domains"
    __table_args__ = (UniqueConstraint("organization_id", "host", name="uq_verified_domain"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    host: Mapped[str] = mapped_column(String(253))
    token: Mapped[str] = mapped_column(String(64))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    method: Mapped[str | None] = mapped_column(String(8))  # file | meta
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Reports ----------------------------------------------------------------------------------------


class Report(Base):
    """A generated file. Rendered by the docs worker, gated (veraPDF / DOCX check / CSV schema) BEFORE it can be
    downloaded: a file that fails its gate is never offered. Content lives in Postgres for now (bytea, size-capped);
    object storage replaces it when the cloud target is chosen (ADR 0002)."""

    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('audit_pdf', 'audit_docx', 'audit_csv', 'vpat_pdf', 'vpat_docx')",
            name="ck_report_kind",
        ),
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'READY', 'FAILED')", name="ck_report_status"
        ),
        Index("ix_reports_scan", "scan_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    vpat_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(16))
    standard: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(8), server_default="QUEUED")
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_detail: Mapped[str | None] = mapped_column(Text)
    template_version: Mapped[str | None] = mapped_column(String(80))
    validation: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[bytes | None] = mapped_column(deferred=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VpatReport(Base):
    """A VPAT/ACR draft. Conformance levels default to automated evidence or 'Not Evaluated'; a human edits them
    and signs off before the document can be exported (PROJECT_PLAN 1.7)."""

    __tablename__ = "vpat_reports"
    __table_args__ = (
        UniqueConstraint("scan_id", "standard", "edition", name="uq_vpat_scan_std_edition"),
        CheckConstraint("status IN ('DRAFT', 'SIGNED_OFF')", name="ck_vpat_status"),
        CheckConstraint("edition IN ('WCAG', '508', 'EU', 'INT')", name="ck_vpat_edition"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    standard: Mapped[str] = mapped_column(String(40))
    edition: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(10), server_default="DRAFT")
    product: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    criteria: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    mapping_review: Mapped[str] = mapped_column(String(10), server_default="draft")
    signoff: Mapped[dict | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformSession(Base):
    """Refresh tokens for Super Admins, who have no tenant. No organization_id, so it is not a tenant table: rows are
    reachable only by presenting the token (row policy on app.platform_token / app.platform_family)."""

    __tablename__ = "platform_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    email: Mapped[str] = mapped_column(String(320))
    mfa_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    family_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FixSuggestion(Base):
    """One validated (or honestly absent) code fix for one finding. ``fixed_html`` exists only when the fix passed
    our checks and the re-scan oracle; the table constraint ``ck_fix_only_if_ready`` enforces it."""

    __tablename__ = "fix_suggestions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'READY', 'NEEDS_REVIEW', 'FAILED')",
            name="ck_fix_status",
        ),
        CheckConstraint(
            "fixed_html IS NULL OR status = 'READY' OR status = 'PENDING'",
            name="ck_fix_only_if_ready",
        ),
        UniqueConstraint("finding_id", name="uq_fix_finding"),
        Index("ix_fix_suggestions_cache", "organization_id", "rule", "input_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scan_findings.id", ondelete="CASCADE")
    )
    rule: Mapped[str] = mapped_column(String(120))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), server_default="PENDING")
    rung: Mapped[str | None] = mapped_column(String(10))
    original_html: Mapped[str] = mapped_column(Text)
    fixed_html: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, server_default="")
    notes: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    checks: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    reason: Mapped[str | None] = mapped_column(String(30))
    model_id: Mapped[str | None] = mapped_column(String(80))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    from_cache: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationLog(Base):
    """One email to one recipient. ``dedupe_key`` + recipient is unique, so sending is idempotent; only delivery
    progress (status, attempts, error) can change after the row is written."""

    __tablename__ = "notification_log"
    __table_args__ = (
        UniqueConstraint("organization_id", "dedupe_key", "to_email", name="uq_notification_once"),
        CheckConstraint(
            "status IN ('QUEUED', 'SENT', 'FAILED', 'SKIPPED')", name="ck_notification_status"
        ),
        Index("ix_notification_log_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(40))
    to_email: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(8), server_default="QUEUED")
    variables: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    dedupe_key: Mapped[str] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    subject: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    config_ref: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiKey(Base):
    """A key for the public API. Only a hash is stored; identity, hash and scopes are immutable (the table grants UPDATE
    only on ``last_used_at`` and ``revoked_at``), so changing what a key can do means issuing a new one."""

    __tablename__ = "api_keys"
    __table_args__ = (CheckConstraint("cardinality(scopes) > 0", name="ck_api_key_scopes"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_hint: Mapped[str] = mapped_column(String(4))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(40)))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEndpoint(Base):
    """Where an organisation wants events sent. The signing secret is stored encrypted and shown once; the URL cannot be
    edited (the table grants no UPDATE on it): to move an endpoint, create a new one with a new secret."""

    __tablename__ = "webhook_endpoints"
    __table_args__ = (CheckConstraint("cardinality(events) > 0", name="ck_webhook_events"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(String(120), server_default="")
    events: Mapped[list[str]] = mapped_column(ARRAY(String(40)))
    secret_ct: Mapped[str] = mapped_column(Text)
    secret_hint: Mapped[str] = mapped_column(String(4))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    disabled_reason: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default="0")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebhookDelivery(Base):
    """One event for one endpoint. ``(endpoint, event)`` is unique, so emitting twice never sends twice; only delivery
    progress can change after the row is written."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("endpoint_id", "event_id", name="uq_webhook_event_once"),
        CheckConstraint(
            "status IN ('PENDING', 'SENDING', 'SENT', 'ABANDONED')", name="ck_webhook_status"
        ),
        Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),
        Index("ix_webhook_deliveries_endpoint", "endpoint_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE")
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10), server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserNotification(Base):
    """An in-app notification for one member. The text is fixed once written; the person can only mark it read."""

    __tablename__ = "user_notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_user_notification_once"),
        Index("ix_user_notifications_user", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    email_scan: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EntitlementOverride(Base):
    """A negotiated exception for ONE organisation: replaces what its plan says for a feature, optionally until a date.
    Read by the organisation (row-level security); written only by a platform administrator, with a reason."""

    __tablename__ = "entitlement_overrides"
    __table_args__ = (
        CheckConstraint("limit_value IS NULL OR limit_value >= 0", name="ck_override_limit"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    feature_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    limit_value: Mapped[int | None] = mapped_column(BigInteger)  # NULL = unlimited
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Documents and eBooks (Phase 3; ADR 0020) ----------------------------------------------------------


class DocumentStatus(enum.StrEnum):
    UPLOADED = "UPLOADED"  # stored (encrypted) but nobody has looked at it yet
    SCANNING = "SCANNING"  # a worker holds it for the virus scan and structural inspection
    CLEAN = "CLEAN"  # passed every check; the only status from which anything may read the file
    REJECTED = "REJECTED"  # the customer's file failed a check (infected, encrypted, too long...)
    FAILED = "FAILED"  # OUR fault (scanner or store down past its retries); the file stays unreadable
    DELETED = "DELETED"  # bytes erased (retention or the customer's request); the row remains as a tombstone


class Document(Base):
    """A customer file. Bytes live in object storage, encrypted by us; the wrapped data key lives here. Nothing may
    read the bytes unless ``status = 'CLEAN'`` (enforced in ``a11y_core.documents.load_clean``)."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('UPLOADED', 'SCANNING', 'CLEAN', 'REJECTED', 'FAILED', 'DELETED')",
            name="ck_document_status",
        ),
        CheckConstraint("kind IN ('pdf', 'docx', 'pptx', 'epub')", name="ck_document_kind"),
        Index("ix_documents_org_created", "organization_id", "created_at"),
        Index("ix_documents_expiry", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(8))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(300))
    wrapped_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default="UPLOADED")
    reject_code: Mapped[str | None] = mapped_column(String(40))
    reject_detail: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    inspection: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_reason: Mapped[str | None] = mapped_column(String(20))


class DocumentAudit(Base):
    """One run of the PDF accessibility checks on a document (ADR 0021). Charged in document pages."""

    __tablename__ = "document_audits"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')", name="ck_document_audit_status"
        ),
        Index("ix_document_audits_doc", "document_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    standard: Mapped[str] = mapped_column(String(20), server_default="PDF_UA_1")
    status: Mapped[str] = mapped_column(String(10), server_default="QUEUED")
    pages: Mapped[int] = mapped_column(Integer)
    summary: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    tool_version: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentFinding(Base):
    __tablename__ = "document_findings"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('critical', 'serious', 'moderate', 'minor')",
            name="ck_document_finding_severity",
        ),
        Index("ix_document_findings_audit", "audit_id", "ordinal"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_audits.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    rule_id: Mapped[str] = mapped_column(String(60))
    source: Mapped[str] = mapped_column(String(10))
    severity: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    how_to_fix: Mapped[str] = mapped_column(Text)
    wcag: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    needs_human: Mapped[bool] = mapped_column(server_default=text("false"))
    count: Mapped[int] = mapped_column(Integer, server_default="1")
    pages: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    pages_total: Mapped[int] = mapped_column(Integer, server_default="0")
    examples: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    explained: Mapped[bool] = mapped_column(server_default=text("true"))
