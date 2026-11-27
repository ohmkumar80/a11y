"""Generated reports and VPAT drafts (tenant-scoped, RLS).

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)


def org_col():
    return sa.Column(
        "organization_id",
        pg.UUID(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        org_col(),
        sa.Column(
            "scan_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("scan_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vpat_id", pg.UUID(as_uuid=True)),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("standard", sa.String(40), nullable=False),
        sa.Column("status", sa.String(8), server_default="QUEUED", nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.Column("error_detail", sa.Text),
        sa.Column("template_version", sa.String(80)),
        sa.Column("validation", pg.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("size_bytes", sa.Integer),
        sa.Column("sha256", sa.String(64)),
        sa.Column("content", sa.LargeBinary),
        sa.Column("created_by", pg.UUID(as_uuid=True)),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", TS),
        sa.CheckConstraint(
            "kind IN ('audit_pdf', 'audit_docx', 'audit_csv', 'vpat_pdf', 'vpat_docx')",
            name="ck_report_kind",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'READY', 'FAILED')", name="ck_report_status"
        ),
    )
    op.create_index("ix_reports_organization_id", "reports", ["organization_id"])
    op.create_index("ix_reports_scan", "reports", ["scan_id", "created_at"])
    op.create_table(
        "vpat_reports",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        org_col(),
        sa.Column(
            "scan_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("scan_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("standard", sa.String(40), nullable=False),
        sa.Column("edition", sa.String(4), nullable=False),
        sa.Column("status", sa.String(10), server_default="DRAFT", nullable=False),
        sa.Column("product", pg.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("criteria", pg.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("mapping_review", sa.String(10), server_default="draft", nullable=False),
        sa.Column("signoff", pg.JSONB),
        sa.Column("created_by", pg.UUID(as_uuid=True)),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("scan_id", "standard", "edition", name="uq_vpat_scan_std_edition"),
        sa.CheckConstraint("status IN ('DRAFT', 'SIGNED_OFF')", name="ck_vpat_status"),
        sa.CheckConstraint("edition IN ('WCAG', '508', 'EU', 'INT')", name="ck_vpat_edition"),
    )
    op.create_index("ix_vpat_reports_organization_id", "vpat_reports", ["organization_id"])
    for t in ("reports", "vpat_reports"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
        )
    # A finished report file is never rewritten: only the worker's status/content columns may change.
    op.execute("REVOKE UPDATE ON reports FROM a11y_app")
    op.execute(
        "GRANT UPDATE (status, error_code, error_detail, template_version, validation, size_bytes, sha256, content, finished_at) ON reports TO a11y_app"
    )


def downgrade() -> None:
    op.drop_table("vpat_reports")
    op.drop_table("reports")
