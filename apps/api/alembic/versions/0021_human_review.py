"""Platform reviewers and human review requests (ADR 0023).

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)

# Review requests a plan may make each month. Placeholders, like the other launch limits: the owner edits them in /admin.
REVIEWS = {"TRIAL": 0, "STARTER": 2, "GROWTH": 20, "ENTERPRISE": None}
STATUSES = "'REQUESTED', 'IN_REVIEW', 'COMPLETED', 'DECLINED', 'CANCELLED'"


def upgrade() -> None:
    # Platform reviewers are users with no organisation, like Super Admins.
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_role")
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_org_role")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_role CHECK (role IN ('SUPER_ADMIN', 'REVIEWER', 'COMPANY_ADMIN', 'STANDARD_USER'))"
    )
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_org_role CHECK ((role IN ('SUPER_ADMIN', 'REVIEWER')) = (organization_id IS NULL))"
    )
    op.execute(
        "CREATE FUNCTION app_reviewer_id() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT NULLIF(current_setting('app.reviewer_id', true), '')::uuid $$"
    )
    op.create_table(
        "document_reviews",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(10), server_default="REQUESTED", nullable=False),
        sa.Column("requested_by", pg.UUID(as_uuid=True)),
        sa.Column("requested_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("consent_version", sa.String(20), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("due_at", TS, nullable=False),
        sa.Column("pages", sa.Integer, nullable=False),
        # What the queue may show before anyone claims the file: sizes and counts, never names or content.
        sa.Column("snapshot", pg.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("reviewer_id", pg.UUID(as_uuid=True)),
        sa.Column("claimed_at", TS),
        sa.Column("completed_at", TS),
        sa.Column("outcome_note", sa.Text),
        sa.Column("result_document_id", pg.UUID(as_uuid=True), sa.ForeignKey("documents.id")),
        sa.Column("reported_minutes", sa.Integer),
        sa.Column("elapsed_seconds", sa.Integer),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_document_review_status"),
    )
    op.create_index("ix_document_reviews_organization_id", "document_reviews", ["organization_id"])
    op.create_index("ix_document_reviews_doc", "document_reviews", ["document_id", "requested_at"])
    op.create_index("ix_document_reviews_queue", "document_reviews", ["status", "due_at"])
    op.execute(
        "CREATE UNIQUE INDEX uq_document_review_active ON document_reviews (document_id) "
        "WHERE status IN ('REQUESTED', 'IN_REVIEW')"
    )
    op.execute("ALTER TABLE document_reviews ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_reviews FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON document_reviews USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
    )
    # A reviewer sees the unclaimed queue and their own claims, and can change only those. Nothing else in the database.
    op.execute(
        "CREATE POLICY reviewer_read ON document_reviews FOR SELECT "
        "USING (app_reviewer_id() IS NOT NULL AND (status = 'REQUESTED' OR reviewer_id = app_reviewer_id()))"
    )
    op.execute(
        "CREATE POLICY reviewer_update ON document_reviews FOR UPDATE "
        "USING (app_reviewer_id() IS NOT NULL AND (status = 'REQUESTED' OR reviewer_id = app_reviewer_id())) "
        "WITH CHECK (app_reviewer_id() IS NOT NULL AND (reviewer_id = app_reviewer_id() OR (status = 'REQUESTED' AND reviewer_id IS NULL)))"
    )
    op.execute("REVOKE UPDATE, DELETE ON document_reviews FROM a11y_app")
    op.execute(
        "GRANT UPDATE (status, reviewer_id, claimed_at, completed_at, outcome_note, result_document_id, "
        "reported_minutes, elapsed_seconds, updated_at) ON document_reviews TO a11y_app"
    )
    ents = sa.table(
        "plan_entitlements",
        sa.column("plan_id"),
        sa.column("feature_key"),
        sa.column("enabled"),
        sa.column("limit_value"),
    )
    op.bulk_insert(
        ents,
        [
            {
                "plan_id": p,
                "feature_key": "document_reviews_monthly",
                "enabled": True,
                "limit_value": v,
            }
            for p, v in REVIEWS.items()
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM usage_reservations WHERE feature_key = 'document_reviews_monthly'")
    op.execute("DELETE FROM usage_ledger WHERE feature_key = 'document_reviews_monthly'")
    op.execute("DELETE FROM plan_entitlements WHERE feature_key = 'document_reviews_monthly'")
    op.drop_table("document_reviews")
    op.execute("DROP FUNCTION app_reviewer_id()")
    op.execute("DELETE FROM users WHERE role = 'REVIEWER'")
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_org_role")
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_role")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_role CHECK (role IN ('SUPER_ADMIN', 'COMPANY_ADMIN', 'STANDARD_USER'))"
    )
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_org_role CHECK ((role = 'SUPER_ADMIN') = (organization_id IS NULL))"
    )
