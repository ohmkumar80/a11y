"""Guided fixes for PDFs: the structure read at audit time, the fix plans, and fixed copies as derived documents (ADR 0022).

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column(
        "document_audits",
        sa.Column("structure", pg.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.execute("GRANT UPDATE (structure) ON document_audits TO a11y_app")
    op.add_column(
        "documents",
        sa.Column("derived_from", pg.UUID(as_uuid=True), sa.ForeignKey("documents.id")),
    )
    op.create_table(
        "document_fixes",
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
        sa.Column("audit_id", pg.UUID(as_uuid=True), sa.ForeignKey("document_audits.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(10), server_default="DRAFT", nullable=False),
        sa.Column("plan", pg.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("pages", sa.Integer),
        sa.Column("result_document_id", pg.UUID(as_uuid=True), sa.ForeignKey("documents.id")),
        sa.Column("result", pg.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.Column("error_detail", sa.Text),
        sa.Column("created_by", pg.UUID(as_uuid=True)),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'QUEUED', 'RUNNING', 'READY', 'FAILED')", name="ck_document_fix_status"
        ),
    )
    op.create_index("ix_document_fixes_organization_id", "document_fixes", ["organization_id"])
    op.create_index("ix_document_fixes_doc", "document_fixes", ["document_id", "created_at"])
    # One fix in progress per document: a draft being edited, or a build that has not finished.
    op.execute(
        "CREATE UNIQUE INDEX uq_document_fix_active ON document_fixes (document_id) "
        "WHERE status IN ('DRAFT', 'QUEUED', 'RUNNING')"
    )
    op.execute("ALTER TABLE document_fixes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_fixes FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON document_fixes USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
    )
    op.execute("REVOKE UPDATE ON document_fixes FROM a11y_app")
    op.execute(
        "GRANT UPDATE (status, plan, pages, audit_id, result_document_id, result, error_code, error_detail, "
        "updated_at, started_at, finished_at) ON document_fixes TO a11y_app"
    )


def downgrade() -> None:
    op.execute("DELETE FROM usage_reservations WHERE job_id IN (SELECT id::text FROM document_fixes)")
    op.drop_table("document_fixes")
    op.drop_column("documents", "derived_from")
    op.drop_column("document_audits", "structure")
