"""Notification delivery log (tenant-scoped, RLS). One row per recipient and event instance; the unique key makes
sending idempotent (a retried job or repeated schedule never sends the same email twice).

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_log",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("to_email", sa.String(320), nullable=False),
        sa.Column("status", sa.String(8), server_default="QUEUED", nullable=False),
        sa.Column("variables", pg.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("attempts", sa.Integer, server_default="0", nullable=False),
        sa.Column("subject", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("config_ref", sa.String(80)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "organization_id", "dedupe_key", "to_email", name="uq_notification_once"
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'SENT', 'FAILED', 'SKIPPED')", name="ck_notification_status"
        ),
    )
    op.create_index("ix_notification_log_organization_id", "notification_log", ["organization_id"])
    op.create_index("ix_notification_log_created", "notification_log", ["created_at"])
    op.execute("ALTER TABLE notification_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notification_log FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON notification_log USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
    )
    # Who, what and which key are fixed once recorded; only delivery progress may change.
    op.execute("REVOKE UPDATE ON notification_log FROM a11y_app")
    op.execute(
        "GRANT UPDATE (status, attempts, subject, error, config_ref, sent_at) ON notification_log TO a11y_app"
    )


def downgrade() -> None:
    op.drop_table("notification_log")
