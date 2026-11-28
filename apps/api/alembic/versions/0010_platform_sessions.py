"""Super Admin refresh sessions; mfa_verified on tenant refresh tokens.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column(
        "auth_tokens",
        sa.Column("mfa_verified", sa.Boolean, server_default=sa.text("false"), nullable=False),
    )
    op.create_table(
        "platform_sessions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("family_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("mfa_verified", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("family_started_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS),
        sa.Column("revoked_at", TS),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_platform_sessions_family_id", "platform_sessions", ["family_id"])
    op.execute(
        "CREATE FUNCTION app_platform_token() RETURNS text LANGUAGE sql STABLE AS $$ SELECT NULLIF(current_setting('app.platform_token', true), '') $$"
    )
    op.execute(
        "CREATE FUNCTION app_platform_family() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT NULLIF(current_setting('app.platform_family', true), '')::uuid $$"
    )
    op.execute("ALTER TABLE platform_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform_sessions FORCE ROW LEVEL SECURITY")
    # No token presented => no rows (fails closed). A presented token sees its own row; its family becomes visible
    # only after the caller proves the token, so a replayed token can revoke every sibling. Inserts stay strict:
    # a row can only be created for the token being presented.
    op.execute(
        "CREATE POLICY ps_select ON platform_sessions FOR SELECT USING (token_hash = app_platform_token() OR family_id = app_platform_family())"
    )
    op.execute(
        "CREATE POLICY ps_insert ON platform_sessions FOR INSERT WITH CHECK (token_hash = app_platform_token())"
    )
    op.execute(
        "CREATE POLICY ps_update ON platform_sessions FOR UPDATE "
        "USING (token_hash = app_platform_token() OR family_id = app_platform_family()) "
        "WITH CHECK (token_hash = app_platform_token() OR family_id = app_platform_family())"
    )
    op.execute("REVOKE DELETE ON platform_sessions FROM a11y_app")
    op.execute("GRANT DELETE ON platform_sessions TO a11y_admin")  # the hourly purge job


def downgrade() -> None:
    op.drop_table("platform_sessions")
    op.execute("DROP FUNCTION app_platform_family()")
    op.execute("DROP FUNCTION app_platform_token()")
    op.drop_column("auth_tokens", "mfa_verified")
