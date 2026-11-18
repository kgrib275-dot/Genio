"""실행 기록 색인(0020): 모델과 마이그레이션이 같은 색인을 말한다."""

import importlib

from sqlalchemy import inspect

from api.db import engine


def test_runs_have_time_indexes() -> None:
    names = {ix["name"] for ix in inspect(engine).get_indexes("runs")}
    assert {"ix_runs_app_created", "ix_runs_created_at"} <= names


def test_migration_0020_follows_0019_and_is_reversible() -> None:
    mod = importlib.import_module("api.migrations.versions.0020_run_indexes")
    assert mod.revision == "0020" and mod.down_revision == "0019"
    assert callable(mod.upgrade) and callable(mod.downgrade)
