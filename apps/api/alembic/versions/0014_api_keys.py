"""API keys for the public API (tenant-scoped, RLS) and the api_access entitlement.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("key_hint", sa.String(4), nullable=False),
        sa.Column("scopes", pg.ARRAY(sa.String(40)), nullable=False),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", TS),
        sa.Column("last_used_at", TS),
        sa.Column("revoked_at", TS),
        sa.CheckConstraint("cardinality(scopes) > 0", name="ck_api_key_scopes"),
    )
    op.create_index("ix_api_keys_organization_id", "api_keys", ["organization_id"])
    op.execute("ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE api_keys FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON api_keys USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
    )
    # A key's identity, hash and scopes never change (make a new key instead); only use and revocation are recorded.
    op.execute("REVOKE UPDATE ON api_keys FROM a11y_app")
    op.execute("GRANT UPDATE (last_used_at, revoked_at) ON api_keys TO a11y_app")
    # Launch placeholders, like the other launch plan limits: API access on the trial (so a design partner can try it),
    # off for Starter, on for Growth and Enterprise. Plans are data: change them in /admin without a deploy.
    for plan, enabled in (
        ("TRIAL", True),
        ("STARTER", False),
        ("GROWTH", True),
        ("ENTERPRISE", True),
    ):
        op.execute(
            f"INSERT INTO plan_entitlements (plan_id, feature_key, enabled, limit_value) "
            f"SELECT '{plan}', 'api_access', {str(enabled).lower()}, NULL WHERE EXISTS (SELECT 1 FROM plans WHERE id = '{plan}') "
            f"ON CONFLICT DO NOTHING"
        )


def downgrade() -> None:
    op.execute("DELETE FROM plan_entitlements WHERE feature_key = 'api_access'")
    op.drop_table("api_keys")
