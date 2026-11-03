"""v0.6: conversation summary memory

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-04 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations", sa.Column("summary", sa.Text(), server_default="", nullable=False)
    )
    op.add_column(
        "conversations",
        sa.Column("summary_upto", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "summary_upto")
    op.drop_column("conversations", "summary")
