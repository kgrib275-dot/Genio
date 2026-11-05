"""v0.9: AI 연결 하나에 키 여러 개(분산·돌려쓰기)

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-05 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_T = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.add_column(
        "llm_providers", sa.Column("extra_keys", JSON_T, server_default="[]", nullable=False)
    )
    op.add_column(
        "llm_providers",
        sa.Column("key_strategy", sa.String(20), server_default="failover", nullable=False),
    )
    op.add_column(
        "llm_providers",
        sa.Column("primary_weight", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("llm_providers", "primary_weight")
    op.drop_column("llm_providers", "key_strategy")
    op.drop_column("llm_providers", "extra_keys")
