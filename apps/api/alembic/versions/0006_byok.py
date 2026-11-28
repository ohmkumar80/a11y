"""BYOK flag on AI usage; byok_ai entitlement on the ENTERPRISE plan.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_usage", sa.Column("byok", sa.Boolean, server_default=sa.text("false"), nullable=False)
    )
    # Launch default: Enterprise may bring its own keys. Admins can grant it to any plan in /admin.
    op.execute(
        "INSERT INTO plan_entitlements (plan_id, feature_key, enabled, limit_value) "
        "VALUES ('ENTERPRISE', 'byok_ai', true, NULL) ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM plan_entitlements WHERE feature_key = 'byok_ai'")
    op.drop_column("ai_usage", "byok")
