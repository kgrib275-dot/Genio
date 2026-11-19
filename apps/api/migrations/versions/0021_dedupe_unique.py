"""겹침 방지: 같은 대화 이름·같은 문서 조각 번호가 두 번 생기지 않게 유일 색인을 더한다

동시에 같은 대화(슬랙·팀즈 사용자의 연속 질문)나 같은 문서 처리가 겹치면 대화·조각이 두 개씩 생길 수
있었다. 이미 겹쳐 있는 것은 지우지 않고 이름만 구분해(대화) 또는 같은 내용의 뒤쪽 조각만 지운 뒤(조각)
유일 색인을 만든다.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-19 12:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) 같은 앱·배포·대화 이름이 겹친 대화: 뒤에 만든 것의 이름 끝에 ~번호를 붙여 구분한다(내용은 그대로)
    op.execute(
        """
        UPDATE conversations SET external_session_id = substr(external_session_id, 1, 90) || '~' || dup.rn
        FROM (
            SELECT id, row_number() OVER (
                PARTITION BY app_id, deployment_id, external_session_id ORDER BY created_at, id
            ) AS rn
            FROM conversations
            WHERE external_session_id IS NOT NULL AND deployment_id IS NOT NULL
        ) AS dup
        WHERE conversations.id = dup.id AND dup.rn > 1
        """
    )
    op.create_index(
        "uq_conversations_session",
        "conversations",
        ["app_id", "deployment_id", "external_session_id"],
        unique=True,
    )
    # 2) 같은 문서의 같은 번호 조각이 겹친 것: 뒤쪽(나중 id)만 지운다
    op.execute(
        """
        DELETE FROM chunks WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (PARTITION BY document_id, position ORDER BY id) AS rn
                FROM chunks
            ) AS t WHERE t.rn > 1
        )
        """
    )
    op.create_index("uq_chunks_doc_position", "chunks", ["document_id", "position"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_chunks_doc_position", table_name="chunks")
    op.drop_index("uq_conversations_session", table_name="conversations")
