"""Per-attempt AI usage metering.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_usage",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_id", sa.String(100)),
        sa.Column("task_key", sa.String(64), nullable=False),
        sa.Column("provider_id", sa.String(40), nullable=False),
        sa.Column("model_id", sa.String(60), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("error_class", sa.String(100)),
        sa.Column("tokens_in", sa.Integer, server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer, server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer, server_default="0", nullable=False),
        sa.Column("config_refs", pg.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('ok', 'error')", name="ck_ai_usage_status"),
    )
    op.create_index("ix_ai_usage_organization_id", "ai_usage", ["organization_id"])
    op.create_index("ix_ai_usage_created_at", "ai_usage", ["created_at"])
    op.execute("ALTER TABLE ai_usage ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_usage FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON ai_usage "
        "USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
    )
    op.execute("REVOKE UPDATE, DELETE ON ai_usage FROM a11y_app")  # metering is append-only


def downgrade() -> None:
    op.drop_table("ai_usage")
