"""PostgreSQL 동시 호출 시험(기본 시험에서는 건너뛴다).

SQLite는 쓰기를 한 줄로 세우고 FOR UPDATE를 무시해서 경합이 보이지 않는다. 진짜 PostgreSQL에서
같은 일을 여러 스레드가 동시에 하는 상황을 만들어, 선점·잠금이 한 번만 통과시키는지 확인한다.

실행(시험용 DB만 쓴다. 안의 표를 모두 지우므로 실제 DB 주소를 넣지 말 것):
  docker run -d --name genio-pgtest -e POSTGRES_PASSWORD=pgtest-only -e POSTGRES_DB=genio_test \\
      -p 127.0.0.1:55999:5432 pgvector/pgvector:pg16
  GENIO_TEST_PG_URL=postgresql+psycopg://postgres:pgtest-only@127.0.0.1:55999/genio_test \\
      pytest apps/api/tests/test_pg_concurrency.py
"""

from __future__ import annotations

# ruff: noqa: S106, S608  (시험용 토큰·시험 DB 질의)
import os
import threading
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import db as db_module
from api.core.errors import AppError
from api.db import Base, SessionLocal, configure_engine
from api.main import app
from api.models import App, Document, HumanTask, KnowledgeBase, Run, WorkflowVersion
from api.tests.conftest import Team

PG_URL = os.environ.get("GENIO_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="GENIO_TEST_PG_URL이 없으면 건너뛴다")


@pytest.fixture(scope="module", autouse=True)
def pg_engine() -> Iterator[None]:
    assert "genio_test" in PG_URL or "pgtest" in PG_URL, "시험용 DB 주소가 아니에요"
    original = db_module.engine
    eng = configure_engine(PG_URL)
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    yield
    configure_engine(str(original.url))


@pytest.fixture(autouse=True)
def clean_pg() -> Iterator[None]:
    Base.metadata.drop_all(db_module.engine)
    Base.metadata.create_all(db_module.engine)
    yield


def race(n: int, fn: Callable[[int], Any]) -> list[Any]:
    """n개 스레드가 동시에 시작하도록 맞춰서 fn을 부른다. 결과(또는 예외)를 모아 돌려준다."""
    barrier = threading.Barrier(n)
    out: list[Any] = [None] * n

    def run(i: int) -> None:
        barrier.wait()
        try:
            out[i] = fn(i)
        except Exception as exc:  # 어떤 오류가 났는지 보려고 그대로 모은다
            out[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return out


def _app(team: Team) -> str:
    with SessionLocal() as db:
        a = App(
            workspace_id=team.ws,
            name="동시",
            slug="pg-race",
            type="chat",
            draft_graph={
                "version": 1,
                "nodes": [
                    {
                        "id": "n1",
                        "type": "input",
                        "position": {"x": 0, "y": 0},
                        "data": {"fields": [{"key": "message", "type": "text"}]},
                    },
                    {
                        "id": "n2",
                        "type": "output",
                        "position": {"x": 300, "y": 0},
                        "data": {"template": "{{n1.message}}"},
                    },
                ],
                "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
                "variables": {},
            },
            created_by=team.users["builder"],
        )
        db.add(a)
        db.commit()
        return a.id


def test_only_one_worker_claims_a_run(team: Team) -> None:
    from api.engine.executor import _claim

    app_id = _app(team)
    with SessionLocal() as db:
        run = Run(app_id=app_id, trigger="api", status="queued", input={})
        db.add(run)
        db.commit()
        run_id = run.id

    def claim(_: int) -> bool:
        with SessionLocal() as db:
            r = db.get(Run, run_id)
            assert r is not None
            return _claim(db, r, "queued", started=True)

    results = race(8, claim)
    assert results.count(True) == 1 and results.count(False) == 7, results


def test_only_one_decision_is_recorded_for_a_task(team: Team) -> None:
    from api.models import User
    from api.services import tasks as tasks_svc

    app_id = _app(team)
    with SessionLocal() as db:
        t = HumanTask(
            workspace_id=team.ws,
            app_id=app_id,
            kind="approval",
            title="승인",
            detail="",
            fields=[],
            status="open",
            token="pg-race-token",
        )
        db.add(t)
        db.commit()
        tid = t.id

    def decide(i: int) -> str:
        with SessionLocal() as db:
            task = db.get(HumanTask, tid)
            user = db.get(User, team.users["admin"])
            assert task is not None
            tasks_svc.complete(
                db, task, approved=(i % 2 == 0), values={}, comment="", user=user, via="app"
            )
            return "ok"

    results = race(6, decide)
    oks = [r for r in results if r == "ok"]
    conflicts = [r for r in results if isinstance(r, AppError) and r.status == 409]
    assert len(oks) == 1 and len(conflicts) == 5, results


def test_concurrent_version_saves_get_distinct_numbers(team: Team) -> None:
    from api.services import apps as app_svc

    app_id = _app(team)

    def save(i: int) -> int:
        with SessionLocal() as db:
            a = db.get(App, app_id)
            assert a is not None
            v = app_svc.save_version(db, a, a.draft_graph or {}, f"동시 {i}", team.users["builder"])
            db.commit()
            return v.version

    results = race(6, save)
    assert all(isinstance(r, int) for r in results), results  # IntegrityError 없이 모두 저장
    assert sorted(results) == [1, 2, 3, 4, 5, 6]


def test_concurrent_first_deploys_do_not_500(team: Team) -> None:
    app_id = _app(team)

    with TestClient(app) as c:

        def deploy(_: int) -> int:
            r = c.post(
                f"/api/v1/apps/{app_id}/deployments",
                json={"channel": "share_link", "access": "workspace"},
                headers=team.h("admin"),
            )
            return r.status_code

        results = race(4, deploy)
    assert all(r == 201 for r in results), results
    with SessionLocal() as db:
        from sqlalchemy import select

        versions = [
            v.version
            for v in db.scalars(select(WorkflowVersion).where(WorkflowVersion.app_id == app_id))
        ]
    assert sorted(versions) == list(range(1, len(versions) + 1))  # 번호가 겹치거나 비지 않는다


def test_alert_state_claim_is_exclusive(team: Team) -> None:
    from api.services import limits

    def claim(_: int) -> Any:
        return limits._claim_state(team.ws, "budget_warned_month", "2026-12")

    results = race(8, claim)
    assert sum(1 for r in results if r is not None) == 1, results


def test_document_is_processed_by_one_worker_only(
    team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.services import kb_pipeline, knowledge

    calls: list[int] = []

    def slow_pipeline(*a: object, **k: object) -> Any:
        calls.append(1)
        import time

        time.sleep(0.5)
        raise kb_pipeline.PipelineError("시험용으로 여기서 멈춘다", "시험")

    monkeypatch.setattr(kb_pipeline, "run_pipeline", slow_pipeline)
    with SessionLocal() as db:
        kb = KnowledgeBase(workspace_id=team.ws, name="동시", embedding_model="m")
        db.add(kb)
        db.flush()
        d = Document(
            kb_id=kb.id,
            filename="a.txt",
            mime="text/plain",
            size=3,
            status="uploaded",
            content=b"abc",
        )
        db.add(d)
        db.commit()
        doc_id = d.id

    def process(_: int) -> None:
        with SessionLocal() as db:
            knowledge.process_document(db, doc_id)

    race(6, process)
    assert len(calls) == 1, calls


def test_concurrent_chat_starts_share_one_conversation(team: Team) -> None:
    from sqlalchemy import func, select

    from api.models import Conversation, Deployment
    from api.services.chat import ChatRequest, start_chat

    app_id = _app(team)
    with SessionLocal() as db:
        a = db.get(App, app_id)
        assert a is not None
        from api.services import apps as app_svc

        v = app_svc.save_version(db, a, a.draft_graph or {}, "v", team.users["builder"])
        db.flush()
        dep = Deployment(
            app_id=app_id,
            version_id=v.id,
            channel="share_link",
            public_token="pg-chat-token",
            access="public",
        )
        db.add(dep)
        db.commit()
        dep_id, ver_id = dep.id, v.id

    def start(i: int) -> str:
        with SessionLocal() as db:
            a = db.get(App, app_id)
            d = db.get(Deployment, dep_id)
            ver = db.get(WorkflowVersion, ver_id)
            assert a is not None and d is not None
            conv, _ = start_chat(
                db,
                ChatRequest(
                    app=a,
                    version=ver,
                    deployment=d,
                    user_id=None,
                    message=f"질문{i}",
                    session_id="slack:abc",
                ),
            )
            return conv.id

    results = race(6, start)
    assert all(isinstance(r, str) for r in results), results
    assert len(set(results)) == 1  # 모두 같은 대화를 쓴다
    with SessionLocal() as db:
        n = db.scalar(
            select(func.count()).select_from(Conversation).where(Conversation.app_id == app_id)
        )
    assert n == 1


def test_migration_0021_cleans_existing_duplicates() -> None:
    """겹쳐 있던 대화·조각이 있어도 0021이 데이터를 잃지 않고 유일 색인을 만든다(업·다운·다시 업)."""
    import subprocess
    import sys
    from pathlib import Path

    api_dir = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": PG_URL}

    def alembic(*args: str) -> None:
        res = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", *args],
            cwd=api_dir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, res.stderr[-800:]

    eng = db_module.engine
    Base.metadata.drop_all(eng)
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    alembic("upgrade", "0020")
    from datetime import UTC, datetime, timedelta

    from api.models import Chunk, Conversation, Deployment, Organization, Workspace

    base = datetime(2026, 11, 1, tzinfo=UTC)
    with SessionLocal() as db:  # 0021 이전 모양(유일 색인 없음)에 겹친 데이터를 넣는다
        org = Organization(name="o", slug="o-s")
        db.add(org)
        db.flush()
        ws = Workspace(org_id=org.id, name="w", slug="w-s", settings={})
        db.add(ws)
        db.flush()
        a1 = App(workspace_id=ws.id, name="a", slug="a-s", type="chat", draft_graph={})
        db.add(a1)
        db.flush()
        ver = WorkflowVersion(app_id=a1.id, version=1, graph={})
        db.add(ver)
        db.flush()
        dep = Deployment(
            app_id=a1.id,
            version_id=ver.id,
            channel="share_link",
            public_token="t-mig",
            access="public",
        )
        kb = KnowledgeBase(workspace_id=ws.id, name="k", embedding_model="m")
        db.add_all([dep, kb])
        db.flush()
        doc = Document(kb_id=kb.id, filename="a.txt", mime="text/plain", size=1, status="ready")
        db.add(doc)
        db.flush()
        for i in range(3):
            db.add(
                Conversation(
                    app_id=a1.id,
                    deployment_id=dep.id,
                    external_session_id="dup-session",
                    created_at=base + timedelta(seconds=i),
                )
            )
            db.add(Chunk(document_id=doc.id, kb_id=kb.id, content=f"조각{i}", position=0))
        db.commit()
        doc_id = doc.id
    alembic("upgrade", "head")
    with eng.connect() as conn:
        ids = [
            r[0]
            for r in conn.exec_driver_sql(
                "SELECT external_session_id FROM conversations ORDER BY created_at"
            ).all()
        ]
    assert (
        ids[0] == "dup-session" and ids[1].startswith("dup-session~") and len(set(ids)) == 3
    )  # 지우지 않고 구분만
    with eng.connect() as conn:
        idx = {
            r[0]
            for r in conn.exec_driver_sql(
                "SELECT indexname FROM pg_indexes WHERE tablename IN ('conversations','chunks')"
            ).all()
        }
    assert {"uq_conversations_session", "uq_chunks_doc_position"} <= idx
    with eng.connect() as conn:
        n_chunks = conn.exec_driver_sql(
            f"SELECT count(*) FROM chunks WHERE document_id = '{doc_id}'"
        ).scalar()
    assert n_chunks == 1  # 같은 번호로 겹친 조각은 앞쪽 하나만 남긴다
    alembic("downgrade", "0020")
    alembic("upgrade", "head")
