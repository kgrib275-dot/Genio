"""v0.5 커넥터: DB 커넥터, 연결 테스트, 허용할 내부 주소, HTTP 인증·시험 호출, 외부에서 받기 서명."""

import json
import socket
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.connectors import database, http_auth
from api.db import SessionLocal
from api.engine import safe_http
from api.tests.conftest import ROLES, Team, install
from api.tests.test_v04_triggers import echo_graph, make_app
from nodes import NodeError


def cred(client: TestClient, team: Team, key: str, name: str, secrets: dict[str, str]) -> str:
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={"connector_key": key, "name": name, "secrets": secrets},
        headers=team.h("owner"),
    )
    assert res.status_code == 200, res.text
    cid: str = res.json()["id"]
    return cid


PG = {
    "engine": "postgresql",
    "host": "db.example.com",
    "port": "5432",
    "database": "shop",
    "user": "reader",
    "password": "db-secret-pass-9876",
}


# ---------------- SQL 검사 ----------------
@pytest.mark.parametrize(
    ("sql", "mode"),
    [
        ("DROP TABLE users", "query"),
        ("SELECT 1; DELETE FROM users", "query"),
        ("WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x", "query"),
        ("CREATE TABLE t (id int)", "execute"),
        ("SELECT * FROM t", "execute"),
        ("   ", "query"),
    ],
)
def test_sql_rules_reject(sql: str, mode: str) -> None:
    with pytest.raises(NodeError):
        database.check_sql(sql, mode)


def test_sql_rules_accept() -> None:
    assert database.check_sql("select id, updated_at from t where id = %(id)s;", "query")
    assert database.check_sql("-- 주석\nUPDATE t SET name = %(n)s WHERE id = %(id)s", "execute")


def test_db_host_private_blocked_unless_allowed() -> None:
    with pytest.raises(NodeError, match="내부"):
        database.check_host("10.0.0.5", 5432, [])
    database.check_host("10.0.0.5", 5432, ["10.0.0.5"])  # 관리자가 허용
    with pytest.raises(NodeError):
        database.check_host("db.example.com", 99999, [])


# ---------------- DB 커넥터 + 연결 테스트 ----------------
def test_database_connector_and_credential_test(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(client, team, "database")
    cid = cred(client, team, "database", "주문 DB", PG)
    calls: list[dict[str, Any]] = []

    def fake_run_sql(**kw: Any) -> dict[str, Any]:
        calls.append(kw)
        return {"rows": [{"ok": 1}], "count": 1, "truncated": False}

    monkeypatch.setattr(database, "run_sql", fake_run_sql)
    url = f"/api/v1/workspaces/{team.ws}/connectors/credentials/{cid}/test"
    res = client.post(url, headers=team.h("builder"))
    assert res.status_code == 200 and res.json()["ok"] is True, res.text
    assert calls[0]["sql"].startswith("SELECT 1") and calls[0]["mode"] == "query"
    assert "db-secret-pass-9876" not in res.text
    for role in ROLES:
        code = client.post(url, headers=team.h(role)).status_code
        assert code == (200 if role in ("owner", "admin", "builder") else 403), role

    # 실제 드라이버 대신 접속 함수만 바꿔 끼워, 사설 주소 차단·허용 흐름을 확인한다
    monkeypatch.undo()
    pg_calls: list[tuple[Any, ...]] = []

    def fake_pg(*args: Any) -> dict[str, Any]:
        pg_calls.append(args)
        return {"rows": [], "count": 0, "truncated": False}

    monkeypatch.setattr(database, "_pg", fake_pg)
    priv = cred(client, team, "database", "사내 DB", {**PG, "host": "10.1.2.3"})
    purl = f"/api/v1/workspaces/{team.ws}/connectors/credentials/{priv}/test"
    blocked = client.post(purl, headers=team.h("builder")).json()
    assert blocked["ok"] is False and "허용할 내부 주소" in blocked["message"]
    assert not pg_calls

    hosts_url = f"/api/v1/workspaces/{team.ws}/connectors/private-hosts"
    for role in ROLES:
        code = client.put(hosts_url, json={"hosts": ["10.1.2.3"]}, headers=team.h(role)).status_code
        assert code == (200 if role in ("owner", "admin") else 403), role
    assert client.get(hosts_url, headers=team.h("admin")).json() == {"hosts": ["10.1.2.3"]}
    bad = client.put(hosts_url, json={"hosts": ["localhost"]}, headers=team.h("owner"))
    assert bad.status_code == 422
    ok = client.post(purl, headers=team.h("builder")).json()
    assert ok["ok"] is True and pg_calls


def test_credential_test_reports_failure_without_secret(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(client, team, "slack")
    cid = cred(client, team, "slack", "팀 슬랙", {"bot_token": "xoxb-very-secret-token-1234"})

    def fake_request(method: str, url: str, **kw: Any) -> dict[str, Any]:
        assert url.endswith("auth.test")
        return {"status": 200, "body": {"ok": False, "error": "invalid_auth"}, "headers": {}}

    monkeypatch.setattr(safe_http, "request", fake_request)
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials/{cid}/test",
        headers=team.h("owner"),
    ).json()
    assert res["ok"] is False and "토큰" in res["message"]
    assert "xoxb-very-secret-token-1234" not in json.dumps(res, ensure_ascii=False)


# ---------------- HTTP 인증·시험 호출 ----------------
def test_http_auth_headers(client: TestClient, team: Team) -> None:
    install(client, team, "http_credentials")
    install(client, team, "slack")
    cid = cred(
        client,
        team,
        "http_credentials",
        "사내 API",
        {
            "token": "tok-123",
            "username": "kim",
            "password": "pw!",
            "header_name": "X-API-Key",
            "header_value": "key-9",
        },
    )
    slack = cred(client, team, "slack", "슬랙", {"bot_token": "xoxb-1"})
    with SessionLocal() as db:
        assert http_auth.auth_headers(db, team.ws, None) == {}
        assert http_auth.auth_headers(db, team.ws, {"type": "bearer", "credential_id": cid}) == {
            "Authorization": "Bearer tok-123"
        }
        basic = http_auth.auth_headers(db, team.ws, {"type": "basic", "credential_id": cid})
        assert basic["Authorization"].startswith("Basic ")
        assert http_auth.auth_headers(db, team.ws, {"type": "header", "credential_id": cid}) == {
            "X-API-Key": "key-9"
        }
        with pytest.raises(NodeError, match="HTTP 인증 정보"):
            http_auth.auth_headers(db, team.ws, {"type": "bearer", "credential_id": slack})
        with pytest.raises(NodeError):
            http_auth.auth_headers(db, "other-ws", {"type": "bearer", "credential_id": cid})


def test_http_preview(client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    install(client, team, "http_credentials")
    cid = cred(client, team, "http_credentials", "API", {"token": "tok-abc"})
    seen: dict[str, Any] = {}

    def fake_request(method: str, url: str, **kw: Any) -> dict[str, Any]:
        safe_http.check_url(url)  # 사설망 차단은 그대로
        seen.update(method=method, url=url, headers=kw.get("headers"))
        return {
            "status": 200,
            "body": {"items": [1, 2]},
            "headers": {"content-type": "application/json"},
        }

    monkeypatch.setattr(safe_http, "request", fake_request)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 0))]
    )
    url = f"/api/v1/workspaces/{team.ws}/http/preview"
    body = {
        "method": "GET",
        "url": "https://api.example.com/items",
        "auth": {"type": "bearer", "credential_id": cid},
    }
    res = client.post(url, json=body, headers=team.h("builder"))
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["status"] == 200 and out["body"] == {"items": [1, 2]} and "elapsed_ms" in out
    assert seen["headers"]["Authorization"] == "Bearer tok-abc"
    for role in ROLES:
        code = client.post(url, json=body, headers=team.h(role)).status_code
        assert code == (200 if role in ("owner", "admin", "builder") else 403), role
    monkeypatch.undo()
    priv = client.post(url, json={"url": "http://127.0.0.1:8000/health"}, headers=team.h("builder"))
    assert priv.status_code == 422 and "localhost" not in priv.json()["detail"]["hint"]


# ---------------- 외부에서 받기: 서명 ----------------
def test_webhook_signature_and_payloads(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, echo_graph())
    res = client.post(
        f"/api/v1/apps/{app_id}/triggers",
        json={"kind": "webhook", "config": {"mode": "async", "require_signature": True}},
        headers=team.h("builder"),
    )
    assert res.status_code == 201, res.text
    t = res.json()
    secret = t["secret"]
    assert secret.startswith("whsec_") and t["has_secret"] is True
    path = "/api/v1/hooks/" + t["url"].split("/hooks/")[1]
    raw = json.dumps({"message": "서명 시험"}).encode()

    no_sig = client.post(path, content=raw, headers={"content-type": "application/json"})
    assert no_sig.status_code == 401 and "서명" in no_sig.json()["detail"]["message"]
    ts = str(int(time.time()))
    bad = client.post(
        path,
        content=raw,
        headers={
            "content-type": "application/json",
            "x-genio-timestamp": ts,
            "x-genio-signature": "sha256=00",
        },
    )
    assert bad.status_code == 401
    old_ts = str(int(time.time()) - 3600)
    from api.services.triggers import sign

    stale = client.post(
        path,
        content=raw,
        headers={
            "content-type": "application/json",
            "x-genio-timestamp": old_ts,
            "x-genio-signature": sign(secret, old_ts, raw),
        },
    )
    assert stale.status_code == 401 and "5분" in stale.json()["detail"]["message"]
    good = client.post(
        path,
        content=raw,
        headers={
            "content-type": "application/json",
            "x-genio-timestamp": ts,
            "x-genio-signature": sign(secret, ts, raw),
            "authorization": "Bearer should-not-be-stored",
        },
    )
    assert good.status_code == 202, good.text

    pay = client.get(f"/api/v1/triggers/{t['id']}/payloads", headers=team.h("builder")).json()
    assert (
        len(pay) == 4 and pay[0]["accepted"] is True and pay[0]["body"] == {"message": "서명 시험"}
    )
    assert pay[0]["run_id"] == good.json()["run_id"]
    dumped = json.dumps(pay, ensure_ascii=False)
    assert "should-not-be-stored" not in dumped and "x-genio-signature" not in dumped
    assert all(p["accepted"] is False for p in pay[1:])
    assert (
        client.get(f"/api/v1/triggers/{t['id']}/payloads", headers=team.h("operator")).status_code
        == 403
    )

    # 비밀값 다시 만들기: 예전 서명은 더 이상 안 됨, 활동 기록에 원문 없음
    new = client.post(f"/api/v1/triggers/{t['id']}/secret", headers=team.h("builder")).json()[
        "secret"
    ]
    assert new != secret
    ts2 = str(int(time.time()))
    assert (
        client.post(
            path,
            content=raw,
            headers={"x-genio-timestamp": ts2, "x-genio-signature": sign(secret, ts2, raw)},
        ).status_code
        == 401
    )
    assert (
        client.post(
            path,
            content=raw,
            headers={"x-genio-timestamp": ts2, "x-genio-signature": sign(new, ts2, raw)},
        ).status_code
        == 202
    )
    logs = client.get(f"/api/v1/workspaces/{team.ws}/audit-logs", headers=team.h("owner")).text
    assert secret not in logs and new not in logs
    listed = client.get(f"/api/v1/apps/{app_id}/triggers", headers=team.h("builder")).text
    assert new not in listed


def test_webhook_without_signature_still_records(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, echo_graph())
    t = client.post(
        f"/api/v1/apps/{app_id}/triggers",
        json={"kind": "webhook", "config": {}},
        headers=team.h("builder"),
    ).json()
    assert "secret" not in t and t["config"]["require_signature"] is False
    path = "/api/v1/hooks/" + t["url"].split("/hooks/")[1]
    assert client.post(path, json={"message": "그냥"}).status_code == 202
    pay = client.get(f"/api/v1/triggers/{t['id']}/payloads", headers=team.h("admin")).json()
    assert pay[0]["accepted"] is True
    # 나중에 서명을 켜면 비밀값이 그때 만들어진다
    upd = client.patch(
        f"/api/v1/triggers/{t['id']}",
        json={"config": {"require_signature": True}},
        headers=team.h("builder"),
    ).json()
    assert upd["secret"].startswith("whsec_")
    assert client.post(path, json={"message": "그냥"}).status_code == 401
