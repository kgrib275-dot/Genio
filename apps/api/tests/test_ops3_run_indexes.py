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


def test_naive_datetimes_are_sent_as_utc() -> None:
    """시간대 표시 없는 시각(sqlite)도 +00:00을 붙여 보내 화면이 시간을 어긋나게 읽지 않는다."""
    from datetime import UTC, datetime, timedelta, timezone

    from fastapi.encoders import jsonable_encoder

    naive = datetime(2026, 11, 18, 7, 32, 0)
    assert jsonable_encoder({"t": naive})["t"] == "2026-11-18T07:32:00+00:00"
    aware = datetime(2026, 11, 18, 16, 32, tzinfo=timezone(timedelta(hours=9)))
    assert jsonable_encoder({"t": aware})["t"] == "2026-11-18T16:32:00+09:00"
    assert jsonable_encoder({"t": datetime(2026, 1, 1, tzinfo=UTC)})["t"].endswith("+00:00")
