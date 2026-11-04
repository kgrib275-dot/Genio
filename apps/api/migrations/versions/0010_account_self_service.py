"""account self-service: email verification, TOTP 2FA, sessions, one-time auth tokens

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-04 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_T = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("totp_secret_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "users", sa.Column("totp_enabled", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("users", sa.Column("recovery_codes", JSON_T, server_default="[]", nullable=False))
    op.add_column(
        "users", sa.Column("tokens_valid_after", sa.DateTime(timezone=True), nullable=True)
    )
    # 이미 있는 계정은 인증된 것으로 본다(인증 필수를 켜도 잠기지 않게)
    op.execute("UPDATE users SET email_verified_at = created_at WHERE email_verified_at IS NULL")

    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
        ),
        sa.Column("user_agent", sa.String(300), server_default="", nullable=False),
        sa.Column("ip", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("user_sessions")
    op.drop_table("auth_tokens")
    op.drop_column("users", "tokens_valid_after")
    op.drop_column("users", "recovery_codes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret_encrypted")
    op.drop_column("users", "email_verified_at")
