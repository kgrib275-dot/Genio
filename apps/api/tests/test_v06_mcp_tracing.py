"""v0.6 MCP 서버 게시(Streamable HTTP, JSON-RPC)와 외부 추적(Langfuse·LangSmith)."""

import base64
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.engine import safe_http
from api.tests.conftest import ROLES, Team, add_llm
from api.tests.fakes import FakeAdapter
from api.tests.test_v04_triggers import echo_graph, make_app

MCP = "/api/v1/service/mcp"


def _key(client: TestClient, team: Team, app_id: str, scopes: list[str]) -> str:
    res = client.post(
        f"/api/v1/apps/{app_id}/api-keys",
        json={"name": "mcp", "scopes": scopes},
        headers=team.h("builder"),
    )
    assert res.status_code == 201, res.text
    return str(res.json()["key"])


def _enable(client: TestClient, team: Team, app_id: str, **extra: Any) -> None:
    res = client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={"mcp": {"enabled": True, **extra}},
        headers=team.h("builder"),
    )
    assert res.status_code == 200, res.text


def _rpc(client: TestClient, key: str, method: str, params: Any = None, rid: Any = 1) -> Any:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if rid is not None:
        msg["id"] = rid
    if params is not None:
        msg["params"] = params
    return client.post(MCP, json=msg, headers={"Authorization": f"Bearer {key}"})


def test_mcp_flow(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, echo_graph("에코"), name="Echo Bot 앱")
    key = _key(client, team, app_id, ["mcp"])
    # 게시를 켜기 전에는 막힌다
    off = _rpc(client, key, "initialize", {"protocolVersion": "2025-06-18"})
    assert off.status_code == 403 and off.json()["detail"]["hint"]
    _enable(client, team, app_id)

    init = _rpc(client, key, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    assert init.status_code == 200
    r = init.json()["result"]
    assert r["protocolVersion"] == "2025-06-18"
    assert r["capabilities"]["tools"] == {"listChanged": False}
    assert r["serverInfo"]["name"] == "genio"
    # 모르는 버전이면 지원하는 최신 버전으로 답한다
    other = _rpc(client, key, "initialize", {"protocolVersion": "1999-01-01"}).json()
    assert other["result"]["protocolVersion"] == "2025-11-25"
    # 알림은 202, 본문 없음
    note = _rpc(client, key, "notifications/initialized", rid=None)
    assert note.status_code == 202 and note.content == b""
    assert _rpc(client, key, "ping").json()["result"] == {}

    tools = _rpc(client, key, "tools/list").json()["result"]["tools"]
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == "echo_bot"
    assert tool["inputSchema"]["properties"]["message"]["type"] == "string"

    call = _rpc(client, key, "tools/call", {"name": "echo_bot", "arguments": {"message": "안녕"}})
    res = call.json()["result"]
    assert res["isError"] is False
    assert res["content"][0]["type"] == "text" and "에코: 안녕" in res["content"][0]["text"]
    assert res["structuredContent"]["run_id"]

    unknown = _rpc(client, key, "tools/call", {"name": "nope", "arguments": {}}).json()
    assert unknown["error"]["code"] == -32602
    assert _rpc(client, key, "foo/bar").json()["error"]["code"] == -32601

    # 일괄 요청(2025-03-26 형식)
    batch = client.post(
        MCP,
        json=[
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        ],
        headers={"Authorization": f"Bearer {key}"},
    )
    assert batch.status_code == 200 and len(batch.json()) == 1
    # 깨진 JSON → Parse error
    bad = client.post(
        MCP,
        content=b"{not json",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    assert bad.status_code == 400 and bad.json()["error"]["code"] == -32700
    # 지원하지 않는 버전 헤더
    hv = client.post(
        MCP,
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": f"Bearer {key}", "MCP-Protocol-Version": "1999-01-01"},
    )
    assert hv.status_code == 400
    assert client.get(MCP, headers={"Authorization": f"Bearer {key}"}).status_code == 405


def test_mcp_scope_and_auth(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, echo_graph())
    _enable(client, team, app_id, tool_name="내 도구 v2!")
    no_scope = _key(client, team, app_id, ["chat", "run"])
    res = _rpc(client, no_scope, "tools/list")
    assert res.status_code == 403 and "MCP" in res.json()["detail"]["message"]
    assert client.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
    key = _key(client, team, app_id, ["mcp"])
    tools = _rpc(client, key, "tools/list").json()["result"]["tools"]
    assert tools[0]["name"] == "v2"  # 영문·숫자·_-만 남긴다


def test_mcp_tool_error_on_missing_required(client: TestClient, team: Team) -> None:
    graph = echo_graph()
    graph["nodes"][0]["data"]["fields"][0]["required"] = True
    app_id = make_app(client, team, graph, name="req")
    _enable(client, team, app_id)
    key = _key(client, team, app_id, ["mcp"])
    tool = _rpc(client, key, "tools/list").json()["result"]["tools"][0]
    assert tool["inputSchema"]["required"] == ["message"]
    res = _rpc(client, key, "tools/call", {"name": tool["name"], "arguments": {}}).json()["result"]
    assert res["isError"] is True
    lines = res["content"][0]["text"].split("\n")
    assert len(lines) == 2 and "message" in lines[0]


# ---------------- 외부 추적 ----------------
LLM_GRAPH: dict[str, Any] = {
    "version": 1,
    "nodes": [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "message", "type": "text"}]}},
        {"id": "n2", "type": "llm", "data": {"label": "요약", "prompt": "{{n1.message}}"}},
        {"id": "n3", "type": "output", "data": {"template": "{{n2.text}}"}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ],
}

LF_SECRET = "sk-lf-supersecret-9999"  # noqa: S105
LS_KEY = "lsv2_pt_secretkey_8888"
MASKED = "****9999"


class Sink:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = 207

    def __call__(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        self.calls.append({"method": method, "url": url, **kw})
        return {"status": self.status, "body": {"successes": [], "errors": []}, "headers": {}}


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> Sink:
    s = Sink()
    monkeypatch.setattr(safe_http, "request", s)
    return s


def _tracing(client: TestClient, team: Team, body: dict[str, Any], role: str = "admin") -> Any:
    return client.put(f"/api/v1/workspaces/{team.ws}/tracing", json=body, headers=team.h(role))


def test_tracing_settings_masked_and_permissions(client: TestClient, team: Team) -> None:
    body = {
        "langfuse": {
            "enabled": True,
            "host": "https://cloud.langfuse.com",
            "public_key": "pk-lf-1",
            "secret_key": LF_SECRET,
        },
        "langsmith": {"enabled": False, "project": "demo", "api_key": LS_KEY},
    }
    for role in ROLES:
        res = _tracing(client, team, body, role)
        assert res.status_code == (200 if role in ("owner", "admin") else 403), role
        got = client.get(f"/api/v1/workspaces/{team.ws}/tracing", headers=team.h(role))
        assert got.status_code == (200 if role in ("owner", "admin") else 403), role
    out = _tracing(client, team, body).json()
    assert out["langfuse"]["secret_key"] == MASKED
    assert out["langsmith"]["api_key"] == "****8888"
    assert LF_SECRET not in str(out) and LS_KEY not in str(out)
    # 비밀 칸을 비우거나 마스킹 값으로 보내면 그대로 유지
    keep = _tracing(
        client,
        team,
        {"langfuse": {"enabled": True, "public_key": "pk-lf-1", "secret_key": MASKED}},
    ).json()
    assert keep["langfuse"]["has_secret"] and keep["langfuse"]["secret_key"] == MASKED
    # 일반 워크스페이스 조회에는 추적 설정(암호문 포함)이 나오지 않는다
    ws = client.get(f"/api/v1/workspaces/{team.ws}", headers=team.h("member")).json()
    assert "tracing" not in ws["settings"]
    bad = _tracing(client, team, {"langfuse": {"enabled": True, "host": "ftp://x"}})
    assert bad.status_code == 422 and bad.json()["detail"]["hint"]


def test_run_is_sent_to_langfuse_and_langsmith(
    client: TestClient,
    team: Team,
    fake_llm: FakeAdapter,
    sink: Sink,
    caplog: pytest.LogCaptureFixture,
) -> None:
    add_llm(client, team)
    _tracing(
        client,
        team,
        {
            "langfuse": {
                "enabled": True,
                "host": "https://lf.example.com/",
                "public_key": "pk-lf-1",
                "secret_key": LF_SECRET,
            },
            "langsmith": {"enabled": True, "project": "genio-test", "api_key": LS_KEY},
        },
    )
    app_id = make_app(client, team, LLM_GRAPH, name="요약 앱")
    caplog.set_level(logging.DEBUG)
    run = client.post(
        f"/api/v1/apps/{app_id}/runs",
        json={"input": {"message": "긴 글"}},
        headers=team.h("builder"),
    ).json()
    detail = client.get(f"/api/v1/runs/{run['id']}", headers=team.h("builder")).json()
    assert detail["status"] == "succeeded", detail["error"]
    urls = [c["url"] for c in sink.calls]
    assert "https://lf.example.com/api/public/ingestion" in urls
    assert "https://api.smith.langchain.com/runs/batch" in urls

    lf = next(c for c in sink.calls if c["url"].endswith("/ingestion"))
    auth = lf["headers"]["Authorization"]
    assert auth == "Basic " + base64.b64encode(f"pk-lf-1:{LF_SECRET}".encode()).decode()
    events = lf["body"]["batch"]
    assert events[0]["type"] == "trace-create" and events[0]["body"]["id"] == run["id"]
    gen = next(e for e in events if e["type"] == "generation-create")
    assert gen["body"]["traceId"] == run["id"] and gen["body"]["name"] == "요약"
    assert gen["body"]["usage"]["total"] > 0 and gen["body"]["model"]
    assert {e["type"] for e in events} >= {"trace-create", "span-create", "generation-create"}

    ls = next(c for c in sink.calls if c["url"].endswith("/runs/batch"))
    assert ls["headers"]["x-api-key"] == LS_KEY
    posts = ls["body"]["post"]
    root = posts[0]
    assert root["id"] == run["id"] and root["run_type"] == "chain"
    assert root["session_name"] == "genio-test"
    llm = next(p for p in posts if p["run_type"] == "llm")
    assert llm["parent_run_id"] == run["id"]
    assert llm["dotted_order"].startswith(root["dotted_order"] + ".")
    assert llm["outputs"]["usage_metadata"]["total_tokens"] > 0
    # 비밀값은 기록(로그)에 남지 않는다
    assert LF_SECRET not in caplog.text and LS_KEY not in caplog.text


def test_tracing_failure_does_not_break_run(
    client: TestClient, team: Team, sink: Sink, caplog: pytest.LogCaptureFixture
) -> None:
    sink.status = 401
    _tracing(
        client,
        team,
        {"langsmith": {"enabled": True, "api_key": LS_KEY}},
    )
    app_id = make_app(client, team, echo_graph())
    caplog.set_level(logging.DEBUG)
    run = client.post(
        f"/api/v1/apps/{app_id}/runs", json={"input": {"message": "x"}}, headers=team.h("builder")
    ).json()
    d = client.get(f"/api/v1/runs/{run['id']}", headers=team.h("builder")).json()
    assert d["status"] == "succeeded"
    assert len(sink.calls) == 1
    assert "인증 실패" in caplog.text and LS_KEY not in caplog.text
    # 연결 시험
    t = client.post(
        f"/api/v1/workspaces/{team.ws}/tracing/test",
        json={"target": "langsmith"},
        headers=team.h("owner"),
    ).json()
    assert t["ok"] is False and "인증" in t["message"]
    sink.status = 200
    t = client.post(
        f"/api/v1/workspaces/{team.ws}/tracing/test",
        json={"target": "langsmith"},
        headers=team.h("owner"),
    ).json()
    assert t["ok"] is True
    t = client.post(
        f"/api/v1/workspaces/{team.ws}/tracing/test",
        json={"target": "langfuse"},
        headers=team.h("owner"),
    ).json()
    assert t["ok"] is False and "키" in t["message"]
    deny = client.post(
        f"/api/v1/workspaces/{team.ws}/tracing/test",
        json={"target": "langfuse"},
        headers=team.h("builder"),
    )
    assert deny.status_code == 403


def test_no_tracing_by_default(client: TestClient, team: Team, sink: Sink) -> None:
    app_id = make_app(client, team, echo_graph())
    client.post(
        f"/api/v1/apps/{app_id}/runs", json={"input": {"message": "x"}}, headers=team.h("builder")
    )
    assert sink.calls == []
