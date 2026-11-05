"""v0.8 file storage backends: where file/document bytes live (db | disk | s3)

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-05 11:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("files", "documents"):
        op.add_column(
            table, sa.Column("storage", sa.String(20), server_default="db", nullable=False)
        )
        op.add_column(table, sa.Column("storage_key", sa.Text(), nullable=True))


def downgrade() -> None:
    for table in ("documents", "files"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("storage_key")
            batch.drop_column("storage")
