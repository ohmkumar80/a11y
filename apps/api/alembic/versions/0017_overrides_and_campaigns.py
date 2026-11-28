"""Per-organisation entitlement overrides and coupon campaigns.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "entitlement_overrides",
        sa.Column(
            "organization_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("feature_key", sa.String(64), primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("limit_value", sa.BigInteger),
        sa.Column("expires_at", TS),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_by", pg.UUID(as_uuid=True)),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("limit_value IS NULL OR limit_value >= 0", name="ck_override_limit"),
    )
    op.execute("ALTER TABLE entitlement_overrides ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE entitlement_overrides FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON entitlement_overrides USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
    )
    # An organisation can read what applies to it; only a platform administrator (audit-logged) can change it.
    op.execute("REVOKE INSERT, UPDATE, DELETE ON entitlement_overrides FROM a11y_app")
    op.execute("GRANT INSERT, UPDATE, DELETE ON entitlement_overrides TO a11y_admin")
    op.add_column("coupons", sa.Column("campaign", sa.String(60)))
    op.create_index("ix_coupons_campaign", "coupons", ["campaign"])


def downgrade() -> None:
    op.drop_index("ix_coupons_campaign", table_name="coupons")
    op.drop_column("coupons", "campaign")
    op.drop_table("entitlement_overrides")
