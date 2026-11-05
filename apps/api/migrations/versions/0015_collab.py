"""v0.9: canvas co-editing (draft revision + snapshots) and comments

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-05 17:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_T = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.add_column("apps", sa.Column("draft_rev", sa.Integer(), server_default="0", nullable=False))
    op.add_column(
        "apps",
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.create_table(
        "draft_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "app_id", sa.String(36), sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("rev", sa.Integer(), nullable=False),
        sa.Column("graph", JSON_T, server_default="{}", nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("app_id", "rev"),
    )
    op.create_index("ix_draft_snapshots_app_id", "draft_snapshots", ["app_id"])
    op.create_table(
        "canvas_comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "app_id", sa.String(36), sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("node_id", sa.String(64)),
        sa.Column("x", sa.Float()),
        sa.Column("y", sa.Float()),
        sa.Column(
            "parent_id",
            sa.String(36),
            sa.ForeignKey("canvas_comments.id", ondelete="CASCADE"),
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("mentions", JSON_T, server_default="[]", nullable=False),
        sa.Column("resolved", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("resolved_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_canvas_comments_app_id", "canvas_comments", ["app_id"])
    op.create_index("ix_canvas_comments_parent_id", "canvas_comments", ["parent_id"])


def downgrade() -> None:
    op.drop_index("ix_canvas_comments_parent_id", table_name="canvas_comments")
    op.drop_index("ix_canvas_comments_app_id", table_name="canvas_comments")
    op.drop_table("canvas_comments")
    op.drop_index("ix_draft_snapshots_app_id", table_name="draft_snapshots")
    op.drop_table("draft_snapshots")
    op.drop_column("apps", "updated_by")
    op.drop_column("apps", "draft_rev")
