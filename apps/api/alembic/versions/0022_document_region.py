"""Documents remember the storage region they were written to (ADR 0024).

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("region", sa.String(30), server_default="default", nullable=False)
    )
    op.create_index("ix_documents_region", "documents", ["region"])


def downgrade() -> None:
    op.drop_index("ix_documents_region", table_name="documents")
    op.drop_column("documents", "region")
