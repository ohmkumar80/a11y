"""Organizations, users, auth tokens, audit log - with Row-Level Security.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ROLES = "'SUPER_ADMIN', 'COMPANY_ADMIN', 'STANDARD_USER'"
KINDS = "'REFRESH', 'EMAIL_VERIFY', 'PASSWORD_RESET', 'INVITE'"


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "users",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"role IN ({ROLES})", name="ck_users_role"),
        sa.CheckConstraint(
            "(role = 'SUPER_ADMIN') = (organization_id IS NULL)", name="ck_users_org_role"
        ),
    )
    op.create_index("uq_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    op.create_table(
        "auth_tokens",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("family_id", pg.UUID(as_uuid=True)),
        sa.Column("invited_email", sa.String(320)),
        sa.Column("invited_role", sa.String(32)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"kind IN ({KINDS})", name="ck_auth_tokens_kind"),
    )
    op.create_index("ix_auth_tokens_organization_id", "auth_tokens", ["organization_id"])
    op.create_index("ix_auth_tokens_user_kind", "auth_tokens", ["user_id", "kind"])
    op.create_table(
        "audit_log",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
        ),
        sa.Column("actor_user_id", pg.UUID(as_uuid=True)),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("detail", pg.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_log_organization_id", "audit_log", ["organization_id"])

    # --- Row-Level Security ------------------------------------------------
    # Missing setting -> NULL -> no rows. Fails closed.
    op.execute(
        """
        CREATE FUNCTION app_org_id() RETURNS uuid LANGUAGE sql STABLE AS
        $$ SELECT NULLIF(current_setting('app.org_id', true), '')::uuid $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION app_auth_email() RETURNS text LANGUAGE sql STABLE AS
        $$ SELECT NULLIF(current_setting('app.auth_email', true), '') $$
        """
    )
    for table in ("organizations", "users", "auth_tokens", "audit_log"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE: the owner is subject to policies too (only BYPASSRLS roles skip them).
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(
        "CREATE POLICY tenant_isolation ON organizations USING (id = app_org_id()) WITH CHECK (id = app_org_id())"
    )
    # users: own tenant, OR the single row matching the pre-login email lookup.
    op.execute(
        """
        CREATE POLICY tenant_isolation ON users
          USING (organization_id = app_org_id() OR email = app_auth_email())
          WITH CHECK (organization_id = app_org_id() OR email = app_auth_email())
        """
    )
    op.execute(
        "CREATE POLICY tenant_isolation ON auth_tokens USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
    )
    op.execute(
        "CREATE POLICY tenant_isolation ON audit_log USING (organization_id = app_org_id()) WITH CHECK (organization_id = app_org_id())"
    )

    # Audit log is append-only for the app role.
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM a11y_app")
    # Super Admin cross-tenant access writes its own audit row (see a11y_core.db.admin_session).
    op.execute("GRANT INSERT ON audit_log TO a11y_admin")


def downgrade() -> None:
    for t in ("audit_log", "auth_tokens", "users", "organizations"):
        op.drop_table(t)
    op.execute("DROP FUNCTION app_auth_email()")
    op.execute("DROP FUNCTION app_org_id()")
