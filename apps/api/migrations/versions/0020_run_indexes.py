"""속도: 실행 기록 목록·집계용 색인

실행 기록은 앱별·기간별로 '최근 것부터' 보거나 합산하는 일이 많은데, 시각(created_at)에 색인이 없어
기록이 쌓일수록 느려졌다. 색인만 더한다(데이터·열은 그대로).

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-18 18:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_runs_app_created", "runs", ["app_id", "created_at"])
    op.create_index("ix_runs_created_at", "runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_runs_created_at", table_name="runs")
    op.drop_index("ix_runs_app_created", table_name="runs")
