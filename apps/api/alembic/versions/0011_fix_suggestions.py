"""AI code-fix suggestions (tenant-scoped, RLS).

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "fix_suggestions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scan_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("scan_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "finding_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("scan_findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule", sa.String(120), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), server_default="PENDING", nullable=False),
        sa.Column("rung", sa.String(10)),
        sa.Column("original_html", sa.Text, nullable=False),
        sa.Column("fixed_html", sa.Text),
        sa.Column("explanation", sa.Text, server_default="", nullable=False),
        sa.Column("notes", pg.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("checks", pg.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("reason", sa.String(30)),
        sa.Column("model_id", sa.String(80)),
        sa.Column("attempts", sa.Integer, server_default="0", nullable=False),
        sa.Column("from_cache", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("error_detail", sa.Text),
        sa.Column("created_by", pg.UUID(as_uuid=True)),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", TS),
        sa.UniqueConstraint("finding_id", name="uq_fix_finding"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'READY', 'NEEDS_REVIEW', 'FAILED')",
            name="ck_fix_status",
        ),
        # Only a validated fix may carry code: the table itself refuses an unvalidated one.
        sa.CheckConstraint(
            "fixed_html IS NULL OR status = 'READY' OR status = 'PENDING'",
            name="ck_fix_only_if_ready",
        ),
    )
    op.create_index("ix_fix_suggestions_organization_id", "fix_suggestions", ["organization_id"])
    op.create_index(
        "ix_fix_suggestions_cache", "fix_suggestions", ["organization_id", "rule", "input_hash"]
    )
    op.execute("ALTER TABLE fix_suggestions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fix_suggestions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON fix_suggestions USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
    )
    # What was asked about (the element, the rule) is fixed; only the worker's result columns may change.
    op.execute("REVOKE UPDATE ON fix_suggestions FROM a11y_app")
    op.execute(
        "GRANT UPDATE (status, rung, fixed_html, explanation, notes, checks, reason, model_id, attempts, from_cache, error_detail, finished_at) ON fix_suggestions TO a11y_app"
    )


def downgrade() -> None:
    op.drop_table("fix_suggestions")
