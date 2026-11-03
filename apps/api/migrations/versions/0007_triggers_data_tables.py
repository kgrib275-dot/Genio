"""v0.4: app triggers (webhook, schedule), data tables, widget appearance

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-03 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_T = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "app_triggers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("app_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), server_default="", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=True),
        sa.Column("config", JSON_T, server_default="{}", nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.String(length=36), nullable=True),
        sa.Column("last_status", sa.String(length=30), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["app_id"], ["apps.id"], ondelete="CASCADE", name="app_triggers_app_id_fkey"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="app_triggers_created_by_fkey"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="app_triggers_token_key"),
    )
    op.create_index("ix_app_triggers_app_id", "app_triggers", ["app_id"])
    op.create_index("ix_app_triggers_next_run_at", "app_triggers", ["next_run_at"])

    op.create_table(
        "data_tables",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("columns", JSON_T, nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
            name="data_tables_workspace_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="SET NULL", name="data_tables_project_id_fkey"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="data_tables_created_by_fkey"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="data_tables_workspace_id_name_key"),
    )
    op.create_index("ix_data_tables_workspace_id", "data_tables", ["workspace_id"])
    op.create_index("ix_data_tables_project_id", "data_tables", ["project_id"])

    op.create_table(
        "data_rows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("table_id", sa.String(length=36), nullable=False),
        sa.Column("row_key", sa.String(length=200), nullable=True),
        sa.Column("data", JSON_T, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["table_id"], ["data_tables.id"], ondelete="CASCADE", name="data_rows_table_id_fkey"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("table_id", "row_key", name="data_rows_table_id_row_key_key"),
    )
    op.create_index("ix_data_rows_table_id", "data_rows", ["table_id"])

    op.add_column(
        "deployments", sa.Column("appearance", JSON_T, server_default="{}", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("deployments", "appearance")
    op.drop_index("ix_data_rows_table_id", table_name="data_rows")
    op.drop_table("data_rows")
    op.drop_index("ix_data_tables_project_id", table_name="data_tables")
    op.drop_index("ix_data_tables_workspace_id", table_name="data_tables")
    op.drop_table("data_tables")
    op.drop_index("ix_app_triggers_next_run_at", table_name="app_triggers")
    op.drop_index("ix_app_triggers_app_id", table_name="app_triggers")
    op.drop_table("app_triggers")
