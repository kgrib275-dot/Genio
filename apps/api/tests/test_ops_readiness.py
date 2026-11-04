"""운영 준비: 요청 번호, 서버 오류 기록(비밀 가림·보관 기간), 시스템 상태, 활동 기록 CSV, 역할별 권한."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.config import get_settings
from api.db import SessionLocal
from api.main import app
from api.models import ErrorEvent
from api.services import error_log, limits
from api.tests.conftest import ROLES, Team

_boom = APIRouter()


@_boom.get("/api/v1/workspaces/{ws}/__boom")
def boom(ws: str) -> dict[str, Any]:
    raise RuntimeError(
        f"db failed for postgresql://genio:hunter2pass@db/genio token=abcd1234efgh {ws}"
    )


app.include_router(_boom)


def test_request_id_header(client: TestClient) -> None:
    r = client.get("/health")
    assert len(r.headers["x-request-id"]) >= 6
    r = client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert r.headers["x-request-id"] == "trace-abc-123"
    r = client.get("/health", headers={"X-Request-ID": "bad id with spaces<>"})
    assert r.headers["x-request-id"] != "bad id with spaces<>"


def test_unhandled_error_is_recorded_without_secrets(team: Team) -> None:
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get(f"/api/v1/workspaces/{team.ws}/__boom", headers=team.h("builder"))
    assert r.status_code == 500
    rid = r.headers["x-request-id"]
    detail = r.json()["detail"]
    assert detail["message"] and rid in detail["hint"]
    with SessionLocal() as db:
        ev = db.scalar(select(ErrorEvent).where(ErrorEvent.request_id == rid))
        assert ev is not None
        assert ev.source == "api" and ev.error_type == "RuntimeError"
        assert ev.where == "GET /api/v1/workspaces/{ws}/__boom"
        assert ev.user_id == team.users["builder"] and ev.workspace_id == team.ws
        assert "hunter2pass" not in ev.message and "abcd1234efgh" not in ev.message


def test_scrub_patterns() -> None:
    s = error_log.scrub(
        "Authorization: Bearer abcdefghijkl sk-proj-1234567890abc xoxb-1234567890-abc "
        "password=supersecret AIzaSyA1234567890123456789012345"
    )
    for secret in (
        "abcdefghijkl",
        "sk-proj-1234567890abc",
        "xoxb-1234567890",
        "supersecret",
        "AIzaSy",
    ):
        assert secret not in s


def test_error_retention(team: Team) -> None:
    old = datetime.now(UTC) - timedelta(days=31)
    with SessionLocal() as db:
        db.add(ErrorEvent(source="api", where="x", error_type="E", message="old", created_at=old))
        db.add(ErrorEvent(source="api", where="x", error_type="E", message="new"))
        db.commit()
        removed = limits.apply_retention(db)
        assert removed["errors"] == 1
        assert [e.message for e in db.scalars(select(ErrorEvent))] == ["new"]


def test_engine_crash_recorded(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.engine import executor
    from api.tests.test_v05_engine import make_app, start

    def explode(*a: Any, **k: Any) -> Any:
        raise ValueError("engine exploded")

    monkeypatch.setattr(executor, "_execute", explode)
    app_id = make_app(
        client,
        team,
        {
            "nodes": [
                {"id": "n1", "type": "input", "data": {"fields": []}},
                {"id": "n2", "type": "output", "data": {"template": "x"}},
            ],
            "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
        },
    )
    d = start(client, team, app_id, {})
    assert d["status"] == "failed"
    with SessionLocal() as db:
        ev = db.scalar(select(ErrorEvent).where(ErrorEvent.source == "engine"))
        assert ev is not None and ev.error_type == "ValueError" and d["id"] in ev.where


@pytest.mark.parametrize("role", ROLES)
def test_status_and_errors_instance_admin_only(client: TestClient, team: Team, role: str) -> None:
    s = client.get("/api/v1/admin/status", headers=team.h(role))
    e = client.get("/api/v1/admin/errors", headers=team.h(role))
    allowed = role == "owner"  # 시험용 팀이 첫 워크스페이스라 소유자가 인스턴스 관리자
    assert (s.status_code == 200) == allowed, (role, s.status_code)
    assert (e.status_code == 200) == allowed
    if not allowed:
        assert s.json()["detail"]["hint"]


def test_status_contents(
    client: TestClient, team: Team, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "genio_backup_dir", str(tmp_path))
    d = client.get("/api/v1/admin/status", headers=team.h("owner")).json()
    labels = {i["label"]: i for i in d["items"]}
    assert labels["DB"]["status"] == "ok"
    assert labels["자동 백업"]["status"] == "unknown"
    assert d["counts"]["users"] >= 5 and d["version"] == "개발"
    now = datetime.now(UTC).isoformat()
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "last_success": now,
                "file": "genio-1.dump",
                "size_mb": 1.2,
                "keep_days": 7,
            }
        ),
        encoding="utf-8",
    )
    d = client.get("/api/v1/admin/status", headers=team.h("owner")).json()
    backup = next(i for i in d["items"] if i["label"] == "자동 백업")
    assert backup["status"] == "ok" and "genio-1.dump" in backup["detail"]
    old = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    (tmp_path / "status.json").write_text(
        json.dumps({"status": "error", "last_success": old, "message": "pg_dump failed"}),
        encoding="utf-8",
    )
    d = client.get("/api/v1/admin/status", headers=team.h("owner")).json()
    backup = next(i for i in d["items"] if i["label"] == "자동 백업")
    assert backup["status"] == "error" and d["overall"] == "error"


@pytest.mark.parametrize("role", ROLES)
def test_audit_export(client: TestClient, team: Team, role: str) -> None:
    from api.core.audit import audit

    with SessionLocal() as db:
        audit(
            db,
            workspace_id=team.ws,
            user_id=team.users["admin"],
            action="app.create",
            target_type="app",
            target_id="a1",
            meta={"name": "상담봇", "api_key": "sk-live-abcdef123456"},
        )
        audit(
            db,
            workspace_id=team.ws,
            user_id=None,
            action="system.update",
            target_type="system",
            meta={},
        )
        db.commit()
    url = f"/api/v1/workspaces/{team.ws}/audit-logs/export"
    r = client.get(url, headers=team.h(role))
    allowed = role in ("owner", "admin")
    assert (r.status_code == 200) == allowed, (role, r.status_code)
    if not allowed:
        return
    body = r.content.decode("utf-8-sig")
    assert body.splitlines()[0].startswith("때(UTC)")
    assert "상담봇" in body and "sk-live-abcdef123456" not in body
    only = client.get(url, params={"area": "system"}, headers=team.h(role)).content.decode(
        "utf-8-sig"
    )
    assert "system.update" in only and "app.create" not in only
    who = client.get(url, params={"user": "(시스템)"}, headers=team.h(role)).content.decode(
        "utf-8-sig"
    )
    assert "system.update" in who and "app.create" not in who
    found = client.get(url, params={"q": "상담"}, headers=team.h(role)).content.decode("utf-8-sig")
    assert "app.create" in found and "system.update" not in found
