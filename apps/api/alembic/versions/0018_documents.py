"""Customer documents: encrypted files in object storage, held until scanned (ADR 0020).

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(300)),
        sa.Column("wrapped_key", sa.Text),
        sa.Column("status", sa.String(10), server_default="UPLOADED", nullable=False),
        sa.Column("reject_code", sa.String(40)),
        sa.Column("reject_detail", sa.Text),
        sa.Column("page_count", sa.Integer),
        sa.Column("inspection", pg.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("attempts", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_by", pg.UUID(as_uuid=True)),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("scanned_at", TS),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("deleted_at", TS),
        sa.Column("deleted_reason", sa.String(20)),
        sa.CheckConstraint(
            "status IN ('UPLOADED', 'SCANNING', 'CLEAN', 'REJECTED', 'FAILED', 'DELETED')",
            name="ck_document_status",
        ),
        sa.CheckConstraint("kind IN ('pdf', 'docx', 'pptx', 'epub')", name="ck_document_kind"),
    )
    op.create_index("ix_documents_organization_id", "documents", ["organization_id"])
    op.create_index("ix_documents_org_created", "documents", ["organization_id", "created_at"])
    op.create_index("ix_documents_expiry", "documents", ["expires_at"])
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE documents FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON documents USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
    )
    # What identifies the file and who owns it never changes; only the processing columns do. Rows are never
    # hard-deleted by the application: erasing a file leaves a tombstone (status DELETED, keys removed).
    op.execute("REVOKE UPDATE, DELETE ON documents FROM a11y_app")
    op.execute(
        "GRANT UPDATE (status, reject_code, reject_detail, page_count, inspection, attempts, scanned_at, "
        "expires_at, storage_key, wrapped_key, filename, deleted_at, deleted_reason) ON documents TO a11y_app"
    )


def downgrade() -> None:
    op.drop_table("documents")
