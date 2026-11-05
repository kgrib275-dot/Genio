"""v0.8: snippets (reusable step groups) and deployment IP allow-list

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-05 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_T = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "snippets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("graph", JSON_T, server_default="{}", nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_snippets_workspace_id", "snippets", ["workspace_id"])
    op.add_column(
        "deployments", sa.Column("allowed_ips", JSON_T, server_default="[]", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("deployments", "allowed_ips")
    op.drop_index("ix_snippets_workspace_id", table_name="snippets")
    op.drop_table("snippets")
