"""PDF audits and their findings; the document-pages quota (ADR 0021).

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)

# Pages of documents a plan may audit each month. Placeholders like the launch plan limits: the owner edits them in /admin.
PAGES = {"TRIAL": 50, "STARTER": 500, "GROWTH": 3000, "ENTERPRISE": None}


def org_col():
    return sa.Column(
        "organization_id",
        pg.UUID(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "document_audits",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        org_col(),
        sa.Column(
            "document_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("standard", sa.String(20), server_default="PDF_UA_1", nullable=False),
        sa.Column("status", sa.String(10), server_default="QUEUED", nullable=False),
        sa.Column("pages", sa.Integer, nullable=False),
        sa.Column("summary", pg.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("tool_version", sa.String(40)),
        sa.Column("error_code", sa.String(40)),
        sa.Column("error_detail", sa.Text),
        sa.Column("created_by", pg.UUID(as_uuid=True)),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')", name="ck_document_audit_status"
        ),
    )
    op.create_index("ix_document_audits_organization_id", "document_audits", ["organization_id"])
    op.create_index("ix_document_audits_doc", "document_audits", ["document_id", "created_at"])
    op.create_table(
        "document_findings",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        org_col(),
        sa.Column(
            "audit_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("document_audits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("rule_id", sa.String(60), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("how_to_fix", sa.Text, nullable=False),
        sa.Column("wcag", pg.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("needs_human", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("count", sa.Integer, server_default="1", nullable=False),
        sa.Column("pages", pg.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("pages_total", sa.Integer, server_default="0", nullable=False),
        sa.Column("examples", pg.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("explained", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint(
            "severity IN ('critical', 'serious', 'moderate', 'minor')", name="ck_document_finding_severity"
        ),
    )
    op.create_index("ix_document_findings_organization_id", "document_findings", ["organization_id"])
    op.create_index("ix_document_findings_audit", "document_findings", ["audit_id", "ordinal"])
    for t in ("document_audits", "document_findings"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
        )
    # A finished audit is a record: findings are written once and never edited.
    op.execute("REVOKE UPDATE ON document_findings FROM a11y_app")
    op.execute("REVOKE UPDATE ON document_audits FROM a11y_app")
    op.execute(
        "GRANT UPDATE (status, summary, tool_version, error_code, error_detail, started_at, finished_at) ON document_audits TO a11y_app"
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
            {"plan_id": p, "feature_key": "document_pages_monthly", "enabled": True, "limit_value": v}
            for p, v in PAGES.items()
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM usage_reservations WHERE feature_key = 'document_pages_monthly'")
    op.execute("DELETE FROM usage_ledger WHERE feature_key = 'document_pages_monthly'")
    op.execute("DELETE FROM plan_entitlements WHERE feature_key = 'document_pages_monthly'")
    op.drop_table("document_findings")
    op.drop_table("document_audits")
