"""운영 준비 1차 A9: 워크스페이스 동시 실행·분당 실행·파일 용량 한도."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.db import SessionLocal
from api.engine import executor
from api.models import App, Run
from api.services import limits, queue
from api.tests.conftest import ROLES, Team


def _app(team: Team, name: str = "앱") -> str:
    with SessionLocal() as db:
        a = App(
            workspace_id=team.ws,
            name=name,
            slug=name,
            type="workflow",
            draft_graph={},
            created_by=team.users["builder"],
        )
        db.add(a)
        db.commit()
        return a.id


def _run(app_id: str, status: str = "running", started_ago: float | None = 1.0) -> str:
    with SessionLocal() as db:
        started = (
            datetime.now(UTC) - timedelta(seconds=started_ago) if started_ago is not None else None
        )
        r = Run(app_id=app_id, status=status, trigger="manual", input={}, started_at=started)
        db.add(r)
        db.commit()
        return r.id


def _set(client: TestClient, team: Team, **kw: Any) -> dict[str, Any]:
    r = client.patch(f"/api/v1/workspaces/{team.ws}/limits", json=kw, headers=team.h("owner"))
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def _reason(app_id: str) -> str | None:
    with SessionLocal() as db:
        app = db.get(App, app_id)
        assert app is not None
        return limits.capacity_wait_reason(db, app)


def test_settings_validate_and_permissions(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/limits"
    for role in ROLES:
        code = client.patch(url, json={"max_concurrent_runs": 3}, headers=team.h(role)).status_code
        assert code == (200 if role in ("owner", "admin") else 403), role
    for bad in (
        {"max_concurrent_runs": 0},
        {"max_runs_per_minute": -1},
        {"max_file_storage_mb": "x"},
    ):
        r = client.patch(url, json=bad, headers=team.h("owner"))
        assert r.status_code == 422, bad
    got = _set(client, team, max_concurrent_runs=3, max_file_storage_mb=10)
    assert got["max_concurrent_runs"] == 3 and got["max_file_storage_mb"] == 10
    assert got["usage"] == {"running_now": 0, "started_last_minute": 0, "file_storage_mb": 0.0}
    got = _set(client, team, max_concurrent_runs=None)
    assert got["max_concurrent_runs"] is None and got["max_file_storage_mb"] == 10


def test_concurrency_reasons(client: TestClient, team: Team) -> None:
    a, b = _app(team, "a"), _app(team, "b")
    assert _reason(a) is None
    _set(client, team, max_concurrent_runs=2, max_concurrent_runs_per_app=1)
    _run(a)
    assert "앱 하나당" in (_reason(a) or "")
    assert _reason(b) is None
    _run(b)
    assert "워크스페이스 동시 실행" in (_reason(b) or "")
    # 오래 '실행 중'으로 남은(멈춘) 기록과 끝난 실행은 세지 않는다
    with SessionLocal() as db:
        for r in db.query(Run).all():
            r.started_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
    assert _reason(b) is None


def test_rate_per_minute(client: TestClient, team: Team) -> None:
    a = _app(team)
    _set(client, team, max_runs_per_minute=2)
    _run(a, status="succeeded", started_ago=10)
    assert _reason(a) is None
    _run(a, status="succeeded", started_ago=20)
    assert "분당" in (_reason(a) or "")
    _set(client, team, max_runs_per_minute=None)
    assert _reason(a) is None


class FakeCelery:
    def __init__(self) -> None:
        self.sent: list[tuple[str, list[str], dict[str, Any]]] = []

    def send_task(self, name: str, args: list[str], **kw: Any) -> None:
        self.sent.append((name, args, kw))


def test_gate_defers_then_times_out(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeCelery()
    monkeypatch.setattr(queue, "_client", lambda: fake)
    monkeypatch.setattr(get_settings(), "genio_run_inline", False)
    a = _app(team)
    _set(client, team, max_concurrent_runs=1)
    _run(a)
    waiting = _run(a, status="queued", started_ago=None)
    with SessionLocal() as db:
        app, run = db.get(App, a), db.get(Run, waiting)
        assert app is not None and run is not None
        assert executor._capacity_gate(db, app, run) == executor.DEFERRED
        assert run.status == "queued"
        info = (run.context or {})["capacity_wait"]
        assert "동시 실행" in info["reason"]
        assert fake.sent == [("genio.execute_run", [waiting], {"countdown": 5.0})]
        # 처음 기다리기 시작한 시각은 그대로 둔다
        first = info["since"]
        assert executor._capacity_gate(db, app, run) == executor.DEFERRED
        assert (run.context or {})["capacity_wait"]["since"] == first
        # 30분 넘게 기다리면 두 줄 문장으로 실패
        old = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
        run.context = {"capacity_wait": {"since": old, "reason": "x"}}
        db.commit()
        msg = executor._capacity_gate(db, app, run)
        assert msg and msg != executor.DEFERRED and "\n" in msg and "한도" in msg


def test_gate_off_in_inline_mode(client: TestClient, team: Team) -> None:
    a = _app(team)
    _set(client, team, max_concurrent_runs=1)
    _run(a)
    waiting = _run(a, status="queued", started_ago=None)
    with SessionLocal() as db:
        app, run = db.get(App, a), db.get(Run, waiting)
        assert app is not None and run is not None
        assert executor._capacity_gate(db, app, run) is None


def test_file_storage_quota(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/files"
    body = b"x" * (600 * 1024)
    r = client.post(url, files={"file": ("a.txt", body, "text/plain")}, headers=team.h("builder"))
    assert r.status_code == 200, r.text
    _set(client, team, max_file_storage_mb=1)
    r = client.post(url, files={"file": ("b.txt", body, "text/plain")}, headers=team.h("builder"))
    assert r.status_code == 413
    assert "용량 한도" in r.text
    usage = _set(client, team, max_file_storage_mb=2)["usage"]
    assert usage["file_storage_mb"] == 0.6
    r = client.post(url, files={"file": ("b.txt", body, "text/plain")}, headers=team.h("builder"))
    assert r.status_code == 200
