"""open readiness: server error events

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-04 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "error_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="api"),
        sa.Column("where", sa.String(300), nullable=False, server_default=""),
        sa.Column("error_type", sa.String(120), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
    )
    op.create_index("ix_error_events_created_at", "error_events", ["created_at"])
    op.create_index("ix_error_events_request_id", "error_events", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_error_events_request_id", table_name="error_events")
    op.drop_index("ix_error_events_created_at", table_name="error_events")
    op.drop_table("error_events")
