"""Outbound webhooks: endpoints and a durable delivery log (tenant-scoped, RLS).

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0015"
down_revision = "0014"
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
        "webhook_endpoints",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        org_col(),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("description", sa.String(120), server_default="", nullable=False),
        sa.Column("events", pg.ARRAY(sa.String(40)), nullable=False),
        sa.Column("secret_ct", sa.Text, nullable=False),
        sa.Column("secret_hint", sa.String(4), nullable=False),
        sa.Column("enabled", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("disabled_reason", sa.Text),
        sa.Column("consecutive_failures", sa.Integer, server_default="0", nullable=False),
        sa.Column("last_success_at", TS),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("cardinality(events) > 0", name="ck_webhook_events"),
    )
    op.create_index(
        "ix_webhook_endpoints_organization_id", "webhook_endpoints", ["organization_id"]
    )
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        org_col(),
        sa.Column(
            "endpoint_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("payload", pg.JSONB, nullable=False),
        sa.Column("status", sa.String(10), server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer, server_default="0", nullable=False),
        sa.Column("next_attempt_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("claimed_at", TS),
        sa.Column("response_status", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("delivered_at", TS),
        sa.UniqueConstraint("endpoint_id", "event_id", name="uq_webhook_event_once"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENDING', 'SENT', 'ABANDONED')", name="ck_webhook_status"
        ),
    )
    op.create_index(
        "ix_webhook_deliveries_organization_id", "webhook_deliveries", ["organization_id"]
    )
    op.create_index(
        "ix_webhook_deliveries_due", "webhook_deliveries", ["status", "next_attempt_at"]
    )
    op.create_index(
        "ix_webhook_deliveries_endpoint", "webhook_deliveries", ["endpoint_id", "created_at"]
    )
    for t in ("webhook_endpoints", "webhook_deliveries"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
        )
    # The URL and creator are fixed (to move an endpoint, make a new one with a new secret).
    op.execute("REVOKE UPDATE ON webhook_endpoints FROM a11y_app")
    op.execute(
        "GRANT UPDATE (description, events, secret_ct, secret_hint, enabled, disabled_reason, consecutive_failures, last_success_at) ON webhook_endpoints TO a11y_app"
    )
    # What was sent (event, payload) is fixed once recorded; only delivery progress may change.
    op.execute("REVOKE UPDATE ON webhook_deliveries FROM a11y_app")
    op.execute(
        "GRANT UPDATE (status, attempts, next_attempt_at, claimed_at, response_status, error, delivered_at) ON webhook_deliveries TO a11y_app"
    )


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_endpoints")
