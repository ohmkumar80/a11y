"""Plans, entitlements, subscriptions, usage ledger + reservations, coupons.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

STATUSES = "'TRIALING', 'ACTIVE', 'PAST_DUE', 'LOCKED_READ_ONLY'"
RESV = "'RESERVED', 'COMMITTED', 'RELEASED'"
TS = sa.DateTime(timezone=True)

# Launch defaults only. Plans, limits and prices are data: edit them in /admin (never in code).
PLANS = [
    (
        "TRIAL",
        "Trial",
        0,
        {"seats": 3, "urls_monthly": 10, "pages_per_scan": 25, "ai_code_fixes_monthly": 20},
    ),
    (
        "STARTER",
        "Starter",
        1,
        {"seats": 3, "urls_monthly": 100, "pages_per_scan": 100, "ai_code_fixes_monthly": 200},
    ),
    (
        "GROWTH",
        "Growth",
        2,
        {"seats": 10, "urls_monthly": 500, "pages_per_scan": 500, "ai_code_fixes_monthly": 1500},
    ),
    (
        "ENTERPRISE",
        "Enterprise",
        3,
        {
            "seats": None,
            "urls_monthly": None,
            "pages_per_scan": 5000,
            "ai_code_fixes_monthly": None,
        },
    ),
]


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, server_default="", nullable=False),
        sa.Column("is_public", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer, server_default="0", nullable=False),
    )
    op.create_table(
        "plan_entitlements",
        sa.Column(
            "plan_id",
            sa.String(64),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("feature_key", sa.String(64), primary_key=True),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("limit_value", sa.BigInteger),
        sa.CheckConstraint("limit_value IS NULL OR limit_value >= 0", name="ck_ent_limit"),
    )
    op.create_table(
        "plan_prices",
        sa.Column(
            "plan_id",
            sa.String(64),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("currency", sa.String(3), primary_key=True),
        sa.Column("cycle", sa.String(10), primary_key=True),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.CheckConstraint("cycle IN ('MONTHLY', 'ANNUAL')", name="ck_price_cycle"),
        sa.CheckConstraint("amount_minor >= 0", name="ck_price_amount"),
    )
    op.create_table(
        "coupons",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("discount_type", sa.String(16), nullable=False),
        sa.Column("discount_value", sa.BigInteger, nullable=False),
        sa.Column("valid_from", TS),
        sa.Column("valid_until", TS),
        sa.Column("max_redemptions", sa.Integer),
        sa.Column("current_redemptions", sa.Integer, server_default="0", nullable=False),
        sa.Column(
            "applicable_plan_ids",
            pg.ARRAY(sa.String),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("discount_type IN ('PERCENTAGE', 'FIXED_INR')", name="ck_coupon_type"),
        sa.CheckConstraint("discount_value > 0", name="ck_coupon_value"),
        sa.CheckConstraint(
            "discount_type <> 'PERCENTAGE' OR discount_value <= 100", name="ck_coupon_pct"
        ),
        sa.CheckConstraint(
            "current_redemptions >= 0 AND (max_redemptions IS NULL OR current_redemptions <= max_redemptions)",
            name="ck_coupon_redemptions",
        ),
    )
    op.create_index("uq_coupons_code", "coupons", ["code"], unique=True)

    org_fk = lambda: sa.ForeignKey("organizations.id", ondelete="CASCADE")  # noqa: E731
    op.create_table(
        "subscriptions",
        sa.Column("organization_id", pg.UUID(as_uuid=True), org_fk(), primary_key=True),
        sa.Column("plan_id", sa.String(64), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("billing_cycle", sa.String(10), server_default="MONTHLY", nullable=False),
        sa.Column("trial_ends_at", TS),
        sa.Column("locks_at", TS),
        sa.Column("applied_coupon_id", pg.UUID(as_uuid=True), sa.ForeignKey("coupons.id")),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_sub_status"),
        sa.CheckConstraint("billing_cycle IN ('MONTHLY', 'ANNUAL')", name="ck_sub_cycle"),
    )
    op.create_table(
        "usage_ledger",
        sa.Column("organization_id", pg.UUID(as_uuid=True), org_fk(), primary_key=True),
        sa.Column("feature_key", sa.String(64), primary_key=True),
        sa.Column("period_start", sa.Date, primary_key=True),
        sa.Column("used", sa.BigInteger, server_default="0", nullable=False),
        sa.CheckConstraint("used >= 0", name="ck_ledger_used"),
    )
    op.create_table(
        "usage_reservations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", pg.UUID(as_uuid=True), org_fk(), nullable=False),
        sa.Column("feature_key", sa.String(64), nullable=False),
        sa.Column("job_id", sa.String(100), nullable=False),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("amount", sa.BigInteger, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("settled_at", TS),
        sa.CheckConstraint(f"status IN ({RESV})", name="ck_resv_status"),
        sa.CheckConstraint("amount > 0", name="ck_resv_amount"),
        sa.UniqueConstraint("organization_id", "feature_key", "job_id", name="uq_resv_job"),
    )
    op.create_index(
        "ix_usage_reservations_organization_id", "usage_reservations", ["organization_id"]
    )
    op.create_table(
        "coupon_redemptions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("coupon_id", pg.UUID(as_uuid=True), sa.ForeignKey("coupons.id"), nullable=False),
        sa.Column("organization_id", pg.UUID(as_uuid=True), org_fk(), nullable=False),
        sa.Column("terms", pg.JSONB, nullable=False),
        sa.Column("redeemed_at", TS, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("coupon_id", "organization_id", name="uq_redemption"),
    )
    op.create_index(
        "ix_coupon_redemptions_organization_id", "coupon_redemptions", ["organization_id"]
    )

    # --- Row-Level Security on every tenant table -------------------------------------------
    for t in ("subscriptions", "usage_ledger", "usage_reservations", "coupon_redemptions"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} "
            "USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
        )

    # --- Least-privilege grants ---------------------------------------------------------------
    # Catalogue tables: the app reads, only the audited admin role writes.
    for t in ("plans", "plan_entitlements", "plan_prices"):
        op.execute(f"REVOKE INSERT, UPDATE, DELETE ON {t} FROM a11y_app")
        op.execute(f"GRANT INSERT, UPDATE, DELETE ON {t} TO a11y_admin")
    # Coupons: app may only bump the redemption counter (atomic conditional UPDATE).
    op.execute("REVOKE INSERT, UPDATE, DELETE ON coupons FROM a11y_app")
    op.execute("GRANT UPDATE (current_redemptions) ON coupons TO a11y_app")
    op.execute("GRANT INSERT, UPDATE, DELETE ON coupons TO a11y_admin")
    # Subscriptions: a tenant can never change its own plan.
    op.execute("REVOKE UPDATE, DELETE ON subscriptions FROM a11y_app")
    op.execute(
        "GRANT UPDATE (status, trial_ends_at, locks_at, applied_coupon_id, updated_at) ON subscriptions TO a11y_app"
    )
    op.execute("GRANT INSERT, UPDATE ON subscriptions TO a11y_admin")
    # Redemptions and settled reservations are history.
    op.execute("REVOKE UPDATE, DELETE ON coupon_redemptions FROM a11y_app")
    op.execute("REVOKE DELETE ON usage_reservations, usage_ledger FROM a11y_app")

    # --- launch plans + backfill ---------------------------------------------------------------
    plans = sa.table(
        "plans", sa.column("id"), sa.column("name"), sa.column("sort_order"), sa.column("is_public")
    )
    ents = sa.table(
        "plan_entitlements",
        sa.column("plan_id"),
        sa.column("feature_key"),
        sa.column("enabled"),
        sa.column("limit_value"),
    )
    op.bulk_insert(
        plans,
        [{"id": i, "name": n, "sort_order": o, "is_public": i != "TRIAL"} for i, n, o, _ in PLANS],
    )
    op.bulk_insert(
        ents,
        [
            {"plan_id": i, "feature_key": k, "enabled": True, "limit_value": v}
            for i, _, _, f in PLANS
            for k, v in f.items()
        ],
    )
    # Existing organisations get a fresh 14-day trial. The owner is subject to FORCE RLS, so
    # lift it for this statement only.
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE subscriptions NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "INSERT INTO subscriptions (organization_id, plan_id, status, trial_ends_at, locks_at) "
        "SELECT id, 'TRIAL', 'TRIALING', now() + interval '14 days', now() + interval '14 days' "
        "FROM organizations"
    )
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE subscriptions FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for t in (
        "coupon_redemptions",
        "usage_reservations",
        "usage_ledger",
        "subscriptions",
        "coupons",
        "plan_prices",
        "plan_entitlements",
        "plans",
    ):
        op.drop_table(t)
