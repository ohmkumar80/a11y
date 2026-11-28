"""Web scans: jobs, pages, findings, verified domains (all tenant-scoped with RLS).

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
STATUS = "'QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'"


def org_col():
    return sa.Column(
        "organization_id",
        pg.UUID(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "scan_jobs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        org_col(),
        sa.Column("created_by", pg.UUID(as_uuid=True)),
        sa.Column("start_url", sa.Text, nullable=False),
        sa.Column("mode", sa.String(8), server_default="single", nullable=False),
        sa.Column("max_pages", sa.Integer, server_default="1", nullable=False),
        sa.Column("standards", pg.ARRAY(sa.String), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("status", sa.String(12), server_default="QUEUED", nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.Column("error_detail", sa.Text),
        sa.Column("pages_scanned", sa.Integer, server_default="0", nullable=False),
        sa.Column("findings_count", sa.Integer, server_default="0", nullable=False),
        sa.Column(
            "engine_versions", pg.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("rules_version", sa.String(40)),
        sa.Column("config_refs", pg.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("attempts", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", TS),
        sa.Column("heartbeat_at", TS),
        sa.Column("finished_at", TS),
        sa.CheckConstraint(f"status IN ({STATUS})", name="ck_scan_status"),
        sa.CheckConstraint("mode IN ('single', 'crawl')", name="ck_scan_mode"),
    )
    op.create_index("ix_scan_jobs_organization_id", "scan_jobs", ["organization_id"])
    op.create_index("ix_scan_jobs_org_created", "scan_jobs", ["organization_id", "created_at"])
    op.create_table(
        "scan_pages",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        org_col(),
        sa.Column(
            "scan_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("scan_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("final_url", sa.Text),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.Column("error_detail", sa.Text),
        sa.Column("http_status", sa.Integer),
        sa.Column("title", sa.Text),
        sa.Column("lang", sa.String(35)),
        sa.Column("engines", pg.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("duration_ms", sa.Integer, server_default="0", nullable=False),
        sa.Column("scanned_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_scan_pages_organization_id", "scan_pages", ["organization_id"])
    op.create_index("ix_scan_pages_scan", "scan_pages", ["scan_id"])
    op.create_table(
        "scan_findings",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        org_col(),
        sa.Column(
            "scan_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("scan_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("scan_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("canonical_rule_id", sa.String(120), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("sc", pg.ARRAY(sa.String), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("kind", sa.String(14), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("confidence", sa.String(8), nullable=False),
        sa.Column("engines", pg.ARRAY(sa.String), nullable=False),
        sa.Column("covering", pg.ARRAY(sa.String), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "engine_rule_ids", pg.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("xpath", sa.Text, nullable=False),
        sa.Column("css", sa.Text, nullable=False),
        sa.Column("tag", sa.String(40), nullable=False),
        sa.Column("html", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("rect", pg.JSONB),
        sa.Column("cluster_key", sa.String(16), nullable=False),
        sa.Column("fingerprint", sa.String(16), nullable=False),
        sa.Column("help_url", sa.Text),
        sa.Column("mapped", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('violation', 'needs_review', 'best_practice')", name="ck_finding_kind"
        ),
    )
    op.create_index("ix_scan_findings_organization_id", "scan_findings", ["organization_id"])
    op.create_index("ix_scan_findings_scan_rule", "scan_findings", ["scan_id", "canonical_rule_id"])
    op.create_index("ix_scan_findings_scan_kind", "scan_findings", ["scan_id", "kind", "severity"])
    op.create_table(
        "verified_domains",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        org_col(),
        sa.Column("host", sa.String(253), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("verified_at", TS),
        sa.Column("method", sa.String(8)),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "host", name="uq_verified_domain"),
    )
    op.create_index("ix_verified_domains_organization_id", "verified_domains", ["organization_id"])

    for t in ("scan_jobs", "scan_pages", "scan_findings", "verified_domains"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} "
            "USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
        )
    # The sweeper (admin role) marks stuck scans failed; the app role never needs to rewrite findings.
    op.execute("REVOKE UPDATE ON scan_findings, scan_pages FROM a11y_app")
    op.execute("GRANT UPDATE, INSERT ON scan_jobs TO a11y_admin")


def downgrade() -> None:
    for t in ("verified_domains", "scan_findings", "scan_pages", "scan_jobs"):
        op.drop_table(t)
