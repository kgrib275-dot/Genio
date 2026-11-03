"""run_steps.seq 추가: 같은 시각에 시작한 단계도 실행 순서대로 보여 준다.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("run_steps", sa.Column("seq", sa.Integer(), server_default="0", nullable=False))
    # 기존 기록은 시작 시각 순으로 번호를 매긴다
    op.execute(
        """
        UPDATE run_steps AS s SET seq = o.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY run_id ORDER BY started_at, id) AS rn
            FROM run_steps
        ) AS o
        WHERE s.id = o.id
        """
    )


def downgrade() -> None:
    op.drop_column("run_steps", "seq")
