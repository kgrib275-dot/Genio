"""바깥 AI가 MCP로 앱의 작업본을 만들고 고친다(키 권한 build)."""

from typing import Any

from fastapi.testclient import TestClient

from api.db import SessionLocal
from api.models import AppApiKey, AuditLog
from api.tests.conftest import Team
from api.tests.test_builder import new_session

URL = "/api/v1/service/mcp/build"


def _key(client: TestClient, team: Team, app_id: str, scopes: list[str]) -> str:
    res = client.post(
        f"/api/v1/apps/{app_id}/api-keys",
        json={"name": "bld", "scopes": scopes},
        headers=team.h("builder"),
    )
    assert res.status_code == 201, res.text
    return str(res.json()["key"])


def _rpc(client: TestClient, key: str, method: str, params: Any = None, rid: Any = 1) -> Any:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": rid}
    if params is not None:
        msg["params"] = params
    return client.post(URL, json=msg, headers={"Authorization": f"Bearer {key}"})


def _call(client: TestClient, key: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    res = _rpc(client, key, "tools/call", {"name": name, "arguments": args})
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()["result"]
    return out


def test_requires_build_scope(client: TestClient, team: Team) -> None:
    app_id, _ = new_session(client, team, "권한")
    weak = _key(client, team, app_id, ["mcp", "chat"])
    res = _rpc(client, weak, "tools/list")
    assert res.status_code == 403 and "흐름 만들기·고치기" in res.json()["detail"]["message"]
    assert client.post(URL, json={}).status_code == 401
    assert client.post(URL, json={}, headers={"Authorization": "Bearer gk-nope"}).status_code == 401


def test_external_ai_builds_the_draft(client: TestClient, team: Team) -> None:
    app_id, _ = new_session(client, team, "만들기")
    key = _key(client, team, app_id, ["build"])  # 저장된 버전이 없어도 된다
    init = _rpc(client, key, "initialize", {"protocolVersion": "2025-06-18"}).json()["result"]
    assert init["serverInfo"]["name"] == "genio-builder" and "작업본" in init["instructions"]
    tools = {t["name"] for t in _rpc(client, key, "tools/list").json()["result"]["tools"]}
    assert tools == {
        "get_graph",
        "list_available_nodes",
        "add_node",
        "update_node",
        "remove_node",
        "connect",
        "validate",
        "run_test",
        "get_run",
    }
    assert "ask_user" not in tools and "suggest_market_item" not in tools
    before = _call(client, key, "get_graph", {})
    assert before["isError"] is False
    added = _call(
        client,
        key,
        "add_node",
        {"type": "template", "data": {"label": "인사", "template": "안녕하세요"}},
    )
    assert added["isError"] is False, added
    graph = client.get(f"/api/v1/apps/{app_id}", headers=team.h("builder")).json()["draft_graph"]
    assert any(n["data"].get("label") == "인사" for n in graph["nodes"])
    bad = _call(client, key, "add_node", {"type": "nope_type"})
    assert bad["isError"] is True
    # 변경은 활동 기록에 남는다(읽기만 한 호출은 남기지 않는다)
    with SessionLocal() as db:
        rows = db.query(AuditLog).filter(AuditLog.action == "app.mcp_build").all()
        assert len(rows) == 1 and rows[0].meta["tool"] == "add_node"


def test_cannot_publish_and_unknown_tools(client: TestClient, team: Team) -> None:
    app_id, _ = new_session(client, team, "제한")
    key = _key(client, team, app_id, ["build"])
    res = _rpc(client, key, "tools/call", {"name": "deploy", "arguments": {}})
    assert res.json()["error"]["code"] == -32602
    assert _rpc(client, key, "tools/call", {"name": "ask_user", "arguments": {}}).json()["error"]


def test_key_of_demoted_creator_is_refused(client: TestClient, team: Team) -> None:
    app_id, _ = new_session(client, team, "강등")
    key = _key(client, team, app_id, ["build"])
    with SessionLocal() as db:
        k = db.query(AppApiKey).filter(AppApiKey.app_id == app_id).one()
        k.created_by = None  # 만든 사람이 사라진 키
        db.commit()
    res = _rpc(client, key, "tools/call", {"name": "get_graph", "arguments": {}})
    assert res.status_code == 403
    assert "더 이상 앱을 고칠 수 있는 멤버가 아니에요" in res.json()["detail"]["message"]


def test_batch_and_bad_json(client: TestClient, team: Team) -> None:
    app_id, _ = new_session(client, team, "배치")
    key = _key(client, team, app_id, ["build"])
    h = {"Authorization": f"Bearer {key}"}
    assert (
        client.post(
            URL, json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}], headers=h
        ).status_code
        == 400
    )
    assert client.post(URL, content=b"{", headers=h).status_code == 400
