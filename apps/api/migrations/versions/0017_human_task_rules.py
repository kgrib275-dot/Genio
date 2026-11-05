"""v0.9: human task timeout rules and forwarding history

Revision ID: 0017
Revises: 0015
Create Date: 2026-11-05 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_T = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    # 시간 초과 처리 규칙({on_timeout, escalate_to, default, remind_before_hours, notify, ...})
    op.add_column("human_tasks", sa.Column("rules", JSON_T, server_default="{}", nullable=False))
    # 전달·올리기 이력([{at, by, to, comment, via}])
    op.add_column("human_tasks", sa.Column("history", JSON_T, server_default="[]", nullable=False))


def downgrade() -> None:
    op.drop_column("human_tasks", "history")
    op.drop_column("human_tasks", "rules")
