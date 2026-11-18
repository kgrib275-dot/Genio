"""운영 준비 1차(B1·F18): 새로고침 토큰 회전·재사용 감지

로그인한 기기(user_sessions)마다 지금 쓸 수 있는 새로고침 토큰 번호(jti)를 적어 둔다.
이미 바꾼 옛 토큰이 다시 오면(도난 의심) 그 기기의 로그인을 끊는다. 여러 탭이 동시에 새로고침하는
경우를 위해 바로 앞 토큰은 잠깐(30초) 받아 준다.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-18 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_sessions", sa.Column("refresh_jti", sa.String(40), nullable=True))
    op.add_column("user_sessions", sa.Column("prev_refresh_jti", sa.String(40), nullable=True))
    op.add_column(
        "user_sessions",
        sa.Column("refresh_rotated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_sessions", "refresh_rotated_at")
    op.drop_column("user_sessions", "prev_refresh_jti")
    op.drop_column("user_sessions", "refresh_jti")
