"""Two-step verification columns on users.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mfa_secret_ct", sa.Text))
    op.add_column("users", sa.Column("mfa_pending_ct", sa.Text))
    op.add_column("users", sa.Column("mfa_enabled_at", sa.DateTime(timezone=True)))
    op.add_column(
        "users", sa.Column("mfa_last_step", sa.BigInteger, server_default="0", nullable=False)
    )
    op.add_column(
        "users",
        sa.Column("mfa_recovery", pg.JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column("users", sa.Column("mfa_failed", sa.Integer, server_default="0", nullable=False))
    op.add_column("users", sa.Column("mfa_locked_until", sa.DateTime(timezone=True)))


def downgrade() -> None:
    for c in (
        "mfa_locked_until",
        "mfa_failed",
        "mfa_recovery",
        "mfa_last_step",
        "mfa_enabled_at",
        "mfa_pending_ct",
        "mfa_secret_ct",
    ):
        op.drop_column("users", c)
