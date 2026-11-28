"""Versioned admin settings (PROJECT_PLAN 3.11.1).

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setting_versions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(64), server_default="", nullable=False),
        sa.Column(
            "organization_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("value", pg.JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text, nullable=False),
        sa.Column("actor_user_id", pg.UUID(as_uuid=True)),
        sa.Column("restored_from", sa.Integer),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("key", "scope", "scope_id", "version", name="uq_setting_versions_ver"),
        sa.CheckConstraint("scope IN ('global', 'plan', 'org')", name="ck_setting_versions_scope"),
        sa.CheckConstraint("status IN ('draft', 'published')", name="ck_setting_versions_status"),
        sa.CheckConstraint(
            "(scope = 'org') = (organization_id IS NOT NULL)", name="ck_setting_versions_org"
        ),
    )
    op.create_index(
        "ix_setting_versions_current",
        "setting_versions",
        ["key", "scope", "scope_id", "published_at"],
    )
    op.create_index("ix_setting_versions_organization_id", "setting_versions", ["organization_id"])

    op.execute("ALTER TABLE setting_versions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE setting_versions FORCE ROW LEVEL SECURITY")
    # Global and plan settings are platform-wide and readable by API/workers; an organisation's
    # own overrides are visible only inside that organisation's session.
    op.execute(
        """
        CREATE POLICY read_scope ON setting_versions FOR SELECT
          USING (organization_id IS NULL OR organization_id = app_org_id())
        """
    )
    # The app role may only READ settings. Writes go through the audited admin role.
    op.execute("REVOKE INSERT, UPDATE, DELETE ON setting_versions FROM a11y_app")
    op.execute("GRANT INSERT ON setting_versions TO a11y_admin")
    op.execute("GRANT UPDATE (status, published_at) ON setting_versions TO a11y_admin")


def downgrade() -> None:
    op.drop_table("setting_versions")
