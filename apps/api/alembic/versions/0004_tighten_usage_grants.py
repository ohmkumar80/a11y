"""A tenant may settle its reservations (status) but never rewrite amounts or periods, and may
only move ledger counters, not re-key them.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("REVOKE UPDATE ON usage_reservations FROM a11y_app")
    op.execute("GRANT UPDATE (status, settled_at) ON usage_reservations TO a11y_app")
    op.execute("REVOKE UPDATE ON usage_ledger FROM a11y_app")
    op.execute("GRANT UPDATE (used) ON usage_ledger TO a11y_app")


def downgrade() -> None:
    op.execute("GRANT UPDATE ON usage_reservations, usage_ledger TO a11y_app")
