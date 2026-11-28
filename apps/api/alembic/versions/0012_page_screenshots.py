"""Page screenshots (tenant-scoped, RLS). One JPEG of the top of each scanned page, in page pixels, so the UI can outline
any element from its stored rectangle without storing a picture per finding.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_screenshots",
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
            "page_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("scan_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mime", sa.String(20), server_default="image/jpeg", nullable=False),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("page_height", sa.Integer, nullable=False),
        sa.Column("truncated", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("page_id", name="uq_screenshot_page"),
        sa.CheckConstraint("size_bytes <= 2000000", name="ck_screenshot_size"),
    )
    op.create_index("ix_page_screenshots_organization_id", "page_screenshots", ["organization_id"])
    op.create_index("ix_page_screenshots_scan", "page_screenshots", ["scan_id"])
    op.execute("ALTER TABLE page_screenshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE page_screenshots FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON page_screenshots USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
    )
    # A saved screenshot is evidence of what we scanned: written once, never edited.
    op.execute("REVOKE UPDATE ON page_screenshots FROM a11y_app")


def downgrade() -> None:
    op.drop_table("page_screenshots")
