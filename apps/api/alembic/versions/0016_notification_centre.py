"""In-app notifications and per-user notification preferences (tenant-scoped, RLS).

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "user_notifications",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("link", sa.Text),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("read_at", TS),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_user_notification_once"),
    )
    op.create_index(
        "ix_user_notifications_organization_id", "user_notifications", ["organization_id"]
    )
    op.create_index("ix_user_notifications_user", "user_notifications", ["user_id", "created_at"])
    op.create_table(
        "user_preferences",
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "organization_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email_scan", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_preferences_organization_id", "user_preferences", ["organization_id"])
    for t in ("user_notifications", "user_preferences"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
        )
    # What a notification says is fixed; a person can only mark it read.
    op.execute("REVOKE UPDATE ON user_notifications FROM a11y_app")
    op.execute("GRANT UPDATE (read_at) ON user_notifications TO a11y_app")


def downgrade() -> None:
    op.drop_table("user_preferences")
    op.drop_table("user_notifications")
