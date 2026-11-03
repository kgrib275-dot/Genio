"""v0.5 feature spec P0: deployment users, api key scopes, webhook signing, document toggle,
builder metrics, saved test inputs, chat handoff, human tasks

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03 17:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_T = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
ARR_T = postgresql.ARRAY(sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.add_column(
        "deployments", sa.Column("allowed_users", ARR_T, server_default="{}", nullable=False)
    )
    op.add_column(
        "app_api_keys",
        sa.Column("scopes", ARR_T, server_default="{chat,run}", nullable=False),
    )
    op.add_column("app_triggers", sa.Column("secret_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "app_triggers", sa.Column("last_payloads", JSON_T, server_default="[]", nullable=False)
    )
    op.add_column(
        "documents", sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False)
    )
    op.add_column(
        "builder_sessions", sa.Column("metrics", JSON_T, server_default="{}", nullable=False)
    )
    op.add_column("apps", sa.Column("test_inputs", JSON_T, server_default="[]", nullable=False))
    op.add_column(
        "conversations",
        sa.Column("status", sa.String(length=20), server_default="bot", nullable=False),
    )
    op.add_column("conversations", sa.Column("assigned_to", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "conversations_assigned_to_fkey", "conversations", "users", ["assigned_to"], ["id"]
    )

    op.create_table(
        "human_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("app_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("detail", sa.Text(), server_default="", nullable=False),
        sa.Column("fields", JSON_T, nullable=False),
        sa.Column("assignee_user_id", sa.String(length=36), nullable=True),
        sa.Column("assignee_role", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("response", JSON_T, nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name="human_tasks_workspace_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["app_id"], ["apps.id"], ondelete="CASCADE", name="human_tasks_app_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], ondelete="CASCADE", name="human_tasks_run_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["assignee_user_id"], ["users.id"], name="human_tasks_assignee_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["completed_by"], ["users.id"], name="human_tasks_completed_by_fkey"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="human_tasks_token_key"),
    )
    op.create_index("ix_human_tasks_workspace_id", "human_tasks", ["workspace_id"])
    op.create_index("ix_human_tasks_app_id", "human_tasks", ["app_id"])
    op.create_index("ix_human_tasks_run_id", "human_tasks", ["run_id"])
    op.create_index("ix_human_tasks_assignee_user_id", "human_tasks", ["assignee_user_id"])
    op.create_index("ix_human_tasks_status", "human_tasks", ["status"])


def downgrade() -> None:
    for ix in (
        "ix_human_tasks_status",
        "ix_human_tasks_assignee_user_id",
        "ix_human_tasks_run_id",
        "ix_human_tasks_app_id",
        "ix_human_tasks_workspace_id",
    ):
        op.drop_index(ix, table_name="human_tasks")
    op.drop_table("human_tasks")
    op.drop_constraint("conversations_assigned_to_fkey", "conversations", type_="foreignkey")
    op.drop_column("conversations", "assigned_to")
    op.drop_column("conversations", "status")
    op.drop_column("apps", "test_inputs")
    op.drop_column("builder_sessions", "metrics")
    op.drop_column("documents", "enabled")
    op.drop_column("app_triggers", "last_payloads")
    op.drop_column("app_triggers", "secret_encrypted")
    op.drop_column("app_api_keys", "scopes")
    op.drop_column("deployments", "allowed_users")
