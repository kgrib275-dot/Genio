"""외래 키 삭제 규칙 추가: 앱 삭제 시 배포·실행·대화 메시지가 막히지 않게 한다.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (테이블, 컬럼, 참조 테이블, 새 규칙)
RULES = [
    ("deployments", "version_id", "workflow_versions", "CASCADE"),
    ("runs", "version_id", "workflow_versions", "SET NULL"),
    ("messages", "run_id", "runs", "SET NULL"),
]


def _replace(table: str, column: str, ref: str, ondelete: str | None) -> None:
    name = f"{table}_{column}_fkey"
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, ref, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    for table, column, ref, rule in RULES:
        _replace(table, column, ref, rule)


def downgrade() -> None:
    for table, column, ref, _ in RULES:
        _replace(table, column, ref, None)
