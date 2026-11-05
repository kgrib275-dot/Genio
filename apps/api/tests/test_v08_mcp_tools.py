"""v0.8 MCP 클라이언트·API 도구(OpenAPI 가져오기): 프로토콜, 연결 정보, 단계, 에이전트, 권한."""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.connectors import mcp_client
from api.connectors.mcp_client import McpClient, McpServer
from api.engine import safe_http
from api.engine.agent import build_tools, call_tool
from api.services import openapi_tools
from api.tests.conftest import ROLES, Team, install
from api.tests.test_v05_engine import make_app, start, validate
from nodes import NodeError

TOKEN = "mcp-secret-token-abcd1234"  # noqa: S105
MCP_URL = "https://mcp.example.com/mcp"


# ---------------- 가짜 MCP 서버(HTTP 층 대체) ----------------
class FakeMcp:
    def __init__(
        self,
        *,
        tools: list[dict[str, Any]] | None = None,
        version: str = "2025-06-18",
        sse: bool = False,
        session: bool = True,
        token: str | None = None,
        expire_session_once: bool = False,
        page_size: int = 1000,
    ) -> None:
        self.tools = (
            tools
            if tools is not None
            else [
                {
                    "name": "echo",
                    "description": "받은 글을 그대로 돌려줘요",
                    "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
                },
                {"name": "boom", "description": "항상 오류", "inputSchema": {"type": "object"}},
            ]
        )
        self.version = version
        self.sse = sse
        self.session = session
        self.token = token
        self.expire_session_once = expire_session_once
        self.page_size = page_size
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: Any = None,
        allowed_domains: list[str] | None = None,
        form: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = headers or {}
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        if method == "DELETE":
            return {"status": 200, "body": None, "headers": {}}
        if self.token and headers.get("Authorization") != f"Bearer {self.token}":
            return {"status": 401, "body": "unauthorized", "headers": {}}
        rpc = body or {}
        name = rpc.get("method")
        if "id" not in rpc:
            return {"status": 202, "body": None, "headers": {}}
        if (
            self.expire_session_once
            and name != "initialize"
            and headers.get("Mcp-Session-Id") == "sess-1"
        ):
            self.expire_session_once = False
            return {"status": 404, "body": "session expired", "headers": {}}
        out: dict[str, Any] = {}
        if name == "initialize":
            out = {
                "protocolVersion": self.version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "1"},
            }
        elif name == "tools/list":
            cursor = int((rpc.get("params") or {}).get("cursor") or 0)
            chunk = self.tools[cursor : cursor + self.page_size]
            out = {"tools": chunk}
            if cursor + self.page_size < len(self.tools):
                out["nextCursor"] = str(cursor + self.page_size)
        elif name == "tools/call":
            p = rpc["params"]
            if p["name"] == "echo":
                out = {
                    "content": [
                        {"type": "text", "text": "echo: " + str(p["arguments"].get("text"))}
                    ],
                    "structuredContent": {"echoed": p["arguments"].get("text")},
                }
            elif p["name"] == "boom":
                out = {
                    "content": [{"type": "text", "text": "터졌어요 " + (self.token or "")}],
                    "isError": True,
                }
            else:
                payload = {
                    "jsonrpc": "2.0",
                    "id": rpc["id"],
                    "error": {"code": -32602, "message": "Unknown tool"},
                }
                return {
                    "status": 200,
                    "body": payload,
                    "headers": {"content-type": "application/json"},
                }
        payload = {"jsonrpc": "2.0", "id": rpc["id"], "result": out}
        hdrs = {"content-type": "application/json"}
        if self.session and name == "initialize":
            hdrs["Mcp-Session-Id"] = "sess-1"
        text: Any = payload
        if self.sse:
            text = "event: message\ndata: " + json.dumps(payload) + "\n\n"
        return {"status": 200, "body": text, "headers": hdrs}


def client_for(fake: FakeMcp, token: str = "") -> McpClient:
    return McpClient(McpServer(url=MCP_URL, token=token), request=fake)


# ---------------- 프로토콜 ----------------
def test_handshake_headers_and_session() -> None:
    fake = FakeMcp(token=TOKEN)
    c = client_for(fake, TOKEN)
    tools = c.list_tools()
    assert [t["name"] for t in tools] == ["echo", "boom"]
    methods = [(x["body"] or {}).get("method") for x in fake.calls]
    assert methods == ["initialize", "notifications/initialized", "tools/list"]
    first, notified, listed = fake.calls
    assert first["headers"]["Accept"] == "application/json, text/event-stream"
    assert first["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert "MCP-Protocol-Version" not in first["headers"]
    # 협상이 끝나면 규격 버전과 세션 번호를 계속 붙인다
    for later in (notified, listed):
        assert later["headers"]["MCP-Protocol-Version"] == "2025-06-18"
        assert later["headers"]["Mcp-Session-Id"] == "sess-1"
    c.close()
    assert fake.calls[-1]["method"] == "DELETE"


def test_custom_header_name_and_sse_reply() -> None:
    fake = FakeMcp(sse=True)
    c = McpClient(McpServer(url=MCP_URL, token="k-1234", header_name="X-Api-Key"), request=fake)  # noqa: S106
    assert c.list_tools()[0]["name"] == "echo"
    assert fake.calls[0]["headers"]["X-Api-Key"] == "k-1234"
    assert "Authorization" not in fake.calls[0]["headers"]
    out = c.call_tool("echo", {"text": "안녕"})
    assert out["text"] == "echo: 안녕" and out["structured"] == {"echoed": "안녕"}


def test_protocol_version_negotiation() -> None:
    old = client_for(FakeMcp(version="2024-11-05"))
    old.list_tools()
    assert old.protocol == "2024-11-05"
    with pytest.raises(NodeError, match="규격 버전"):
        client_for(FakeMcp(version="2031-01-01")).list_tools()


def test_tool_result_and_errors() -> None:
    c = client_for(FakeMcp())
    ok = c.call_tool("echo", {"text": "hi"})
    assert ok["is_error"] is False and ok["content"] == [{"type": "text", "text": "echo: hi"}]
    bad = c.call_tool("boom", {})
    assert bad["is_error"] is True and "터졌어요" in bad["text"]
    # JSON-RPC 오류는 두 줄 한국어 오류로 바뀐다
    with pytest.raises(NodeError) as exc:
        c.call_tool("nope", {})
    assert "Unknown tool" in exc.value.message and "확인하세요" in exc.value.message


def test_auth_failure_and_not_mcp_endpoint() -> None:
    with pytest.raises(NodeError, match="인증"):
        client_for(FakeMcp(token="right"), "wrong").list_tools()  # noqa: S106

    def not_found(*a: Any, **k: Any) -> dict[str, Any]:
        return {"status": 405, "body": "", "headers": {}}

    with pytest.raises(NodeError, match="MCP 서버"):
        McpClient(McpServer(url=MCP_URL), request=not_found).list_tools()


def test_session_expired_reinitializes_once() -> None:
    fake = FakeMcp(expire_session_once=True)
    c = client_for(fake)
    assert len(c.list_tools()) == 2
    inits = [x for x in fake.calls if (x["body"] or {}).get("method") == "initialize"]
    assert len(inits) == 2


def test_timeout_and_oversize_pass_through() -> None:
    def slow(*a: Any, **k: Any) -> dict[str, Any]:
        raise NodeError("상대 서버가 제때 답하지 않았어요.", retryable=True)

    with pytest.raises(NodeError) as exc:
        McpClient(McpServer(url=MCP_URL), request=slow).list_tools()
    assert exc.value.retryable

    def big(*a: Any, **k: Any) -> dict[str, Any]:
        raise NodeError("응답이 너무 커요(최대 1024KB). 더 작은 범위를 요청해 주세요.")

    with pytest.raises(NodeError, match="너무 커요"):
        McpClient(McpServer(url=MCP_URL), request=big).list_tools()


def test_tool_list_cap_and_paging() -> None:
    many = [
        {"name": f"t{i}", "description": "x" * 900, "inputSchema": {"type": "object"}}
        for i in range(250)
    ]
    fake = FakeMcp(tools=many, page_size=60)
    tools = client_for(fake).list_tools()
    assert len(tools) == mcp_client.MAX_TOOLS
    assert all(len(t["description"]) <= 500 for t in tools)
    pages = [x for x in fake.calls if (x["body"] or {}).get("method") == "tools/list"]
    assert len(pages) == 4  # 60 + 60 + 60 + 20(여기서 200개를 채워 멈춤)


def test_result_normalization_variants() -> None:
    out = mcp_client.normalize_result(
        {
            "content": [
                {"type": "image", "mimeType": "image/png", "data": "A" * 100},
                {"type": "resource", "resource": {"uri": "file:///a", "text": "문서"}},
                {"type": "resource_link", "uri": "https://x", "name": "링크"},
            ],
            "structuredContent": {"a": 1},
        }
    )
    kinds = [i["type"] for i in out["content"]]
    assert kinds == ["image", "resource", "resource_link"]
    assert "A" * 100 not in json.dumps(out)  # 이미지 내용은 싣지 않는다
    assert out["text"] == "문서" and out["structured"] == {"a": 1}
    only_structured = mcp_client.normalize_result({"structuredContent": {"k": "v"}})
    assert only_structured["text"] == '{"k": "v"}'


# ---------------- 연결 정보(API) ----------------
def create_server(client: TestClient, team: Team, role: str = "owner") -> Any:
    return client.post(
        f"/api/v1/workspaces/{team.ws}/mcp/servers",
        json={"name": "사내 도구", "url": MCP_URL, "token": TOKEN},
        headers=team.h(role),
    )


def test_create_list_and_mask(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeMcp(token=TOKEN)
    monkeypatch.setattr(safe_http, "request", fake)
    r = create_server(client, team)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["host"] == "mcp.example.com" and TOKEN not in r.text
    # 목록에는 호스트만, 값은 마스킹
    lst = client.get(f"/api/v1/workspaces/{team.ws}/mcp/servers", headers=team.h("builder")).json()
    assert lst == [
        {
            "id": sid,
            "name": "사내 도구",
            "host": "mcp.example.com",
            "has_token": True,
            "created_at": lst[0]["created_at"],
        }
    ]
    creds = client.get(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials", headers=team.h("builder")
    )
    assert TOKEN not in creds.text and MCP_URL not in creds.text
    assert creds.json()[0]["connector_key"] == "mcp_server"
    # 연결 테스트(공통 버튼)와 도구 목록
    t = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials/{sid}/test", headers=team.h("builder")
    ).json()
    assert (
        t["ok"]
        and "도구 2개" in t["message"]
        and "echo" in t["message"]
        and TOKEN not in json.dumps(t)
    )
    tools = client.get(
        f"/api/v1/workspaces/{team.ws}/mcp/servers/{sid}/tools?refresh=1", headers=team.h("builder")
    ).json()
    assert tools["ok"] and [x["name"] for x in tools["tools"]] == ["echo", "boom"]


def test_connection_failure_message_hides_secrets(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    def leaky(*a: Any, **k: Any) -> dict[str, Any]:
        raise NodeError(f"{MCP_URL} 에 접속하지 못했어요. 토큰 {TOKEN} 확인")

    monkeypatch.setattr(safe_http, "request", leaky)
    sid = create_server(client, team).json()["id"]
    res = client.get(
        f"/api/v1/workspaces/{team.ws}/mcp/servers/{sid}/tools?refresh=1", headers=team.h("builder")
    )
    assert res.status_code == 200 and res.json()["ok"] is False
    assert TOKEN not in res.text and MCP_URL not in res.text
    test = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials/{sid}/test", headers=team.h("owner")
    ).json()
    assert test["ok"] is False and TOKEN not in json.dumps(test)


def test_invalid_url_and_limits(client: TestClient, team: Team) -> None:
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/mcp/servers",
        json={"name": "x", "url": "ftp://x.example.com/mcp"},
        headers=team.h("owner"),
    )
    assert r.status_code == 422 and r.json()["detail"]["hint"]
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/mcp/servers",
        json={"name": "x", "url": MCP_URL, "header_name": "bad header!"},
        headers=team.h("owner"),
    )
    assert r.status_code == 422


@pytest.mark.parametrize("role", ROLES)
def test_mcp_server_permissions(
    client: TestClient, team: Team, role: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(safe_http, "request", FakeMcp())
    sid = create_server(client, team).json()["id"]
    base = f"/api/v1/workspaces/{team.ws}/mcp/servers"
    manage = role in ("owner", "admin")
    use = role in ("owner", "admin", "builder")
    assert create_server(client, team, role).status_code == (201 if manage else 403)
    assert client.get(base, headers=team.h(role)).status_code == (200 if use else 403)
    assert client.get(f"{base}/{sid}/tools", headers=team.h(role)).status_code == (
        200 if use else 403
    )


# ---------------- mcp_tool 단계 ----------------
def mcp_flow(cred: str, tool: str = "echo", **extra: Any) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "q"}]}},
            {
                "id": "n2",
                "type": "mcp_tool",
                "data": {
                    "credential_id": cred,
                    "tool": tool,
                    "arguments": {"text": "{{n1.q}}"},
                    **extra,
                },
            },
            {"id": "n3", "type": "output", "data": {"template": "{{n2.text}}|{{n2.is_error}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
        ],
    }


def test_mcp_tool_node_runs(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeMcp(token=TOKEN)
    monkeypatch.setattr(safe_http, "request", fake)
    sid = create_server(client, team).json()["id"]
    app_id = make_app(client, team, mcp_flow(sid))
    assert validate(client, team, app_id)["valid"]
    d = start(client, team, app_id, {"q": "점심"})
    assert d["status"] == "succeeded", d["error"]
    assert d["output"]["text"] == "echo: 점심|False"
    step = next(s for s in d["steps"] if s["node_id"] == "n2")
    assert "외부 도구(MCP)" in step["summary"] and TOKEN not in json.dumps(d)
    # 도구가 오류를 알려 주면 값으로 받는다(기본), 실패로 처리하도록 켜면 멈춘다
    flow = mcp_flow(sid, "boom")
    flow["nodes"][1]["data"]["arguments"] = {}
    soft = start(client, team, make_app(client, team, flow), {"q": "x"})
    assert soft["status"] == "succeeded" and soft["output"]["text"].endswith("|True")
    assert TOKEN not in json.dumps(
        soft
    )  # 오류 글 안의 토큰도 지운다? 서버가 보낸 글은 그대로지만 기록엔 마스킹
    flow = mcp_flow(sid, "boom", fail_on_tool_error=True)
    flow["nodes"][1]["data"]["arguments"] = {}
    hard = start(client, team, make_app(client, team, flow), {"q": "x"})
    assert hard["status"] == "failed" and "오류를 알려 줬어요" in hard["error"]


def test_validator_rejects_wrong_credential_kind(client: TestClient, team: Team) -> None:
    install(client, team, "http_credentials")
    cred = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={
            "connector_key": "http_credentials",
            "name": "토큰",
            "secrets": {"token": "abcdefgh1234"},
        },
        headers=team.h("owner"),
    ).json()["id"]
    app_id = make_app(client, team, mcp_flow(cred))
    v = validate(client, team, app_id)
    assert not v["valid"] and any("MCP 서버 연결 정보" in e["message"] for e in v["errors"])
    gone = make_app(client, team, mcp_flow("no-such-id"))
    assert not validate(client, team, gone)["valid"]


# ---------------- 에이전트 도구 ----------------
def test_agent_uses_mcp_tools() -> None:
    fake = FakeMcp()
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def mcp_tools(*, credential_id: str) -> list[dict[str, Any]]:
        return [mcp_client.normalize_tool(t) for t in fake.tools]

    def mcp_call(*, credential_id: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append((credential_id, tool, arguments))
        return client_for(fake).call_tool(tool, arguments)

    services: Any = SimpleNamespace(mcp_tools=mcp_tools, mcp_call=mcp_call)
    defs, table = build_tools(services, [{"type": "mcp", "credential_id": "c1", "tools": ["echo"]}])
    assert len(defs) == 1 and defs[0].description == "받은 글을 그대로 돌려줘요"
    (name,) = table
    assert table[name] == {"type": "mcp", "credential_id": "c1", "tool": "echo"}
    assert call_tool(services, table[name], {"text": "A"}) == "echo: A"
    assert calls == [("c1", "echo", {"text": "A"})]
    # 이름을 비우면 서버의 도구를 모두(최대 20개) 연다
    all_defs, _ = build_tools(services, [{"type": "mcp", "credential_id": "c1"}])
    assert len(all_defs) == 2
    # 없는 도구 이름은 안내 오류
    with pytest.raises(NodeError, match="찾지 못했어요"):
        build_tools(services, [{"type": "mcp", "credential_id": "c1", "tools": ["ghost"]}])
    with pytest.raises(NodeError, match="연결 정보를 골라"):
        build_tools(services, [{"type": "mcp"}])
    # 도구 오류는 표시를 붙여 AI에게 돌려준다
    boom = call_tool(services, {"type": "mcp", "credential_id": "c1", "tool": "boom"}, {})
    assert boom.startswith("(도구가 오류를 알려 줬어요)")


# ---------------- OpenAPI 가져오기 ----------------
PETSTORE = """
openapi: 3.0.3
info: {title: 펫스토어, version: 1.2.0}
servers:
  - url: https://{host}/v1
    variables: {host: {default: petstore.example.com}}
paths:
  /pet/{petId}:
    parameters:
      - {name: petId, in: path, required: true, schema: {type: integer}}
    get:
      operationId: getPetById
      summary: 반려동물 한 마리 가져오기
      parameters:
        - {name: verbose, in: query, schema: {type: boolean, default: false}}
        - {name: X-Trace, in: header, schema: {type: string}}
        - {name: sid, in: cookie, schema: {type: string}}
    delete:
      summary: 지우기
  /pet:
    post:
      operationId: addPet
      summary: 새 반려동물 등록
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: '#/components/schemas/NewPet'}
    get:
      parameters:
        - {name: tags, in: query, schema: {type: array, items: {type: string}}}
        - {name: status, in: query, required: true, schema: {type: string, enum: [available, sold]}}
  /upload:
    post:
      requestBody: {content: {multipart/form-data: {schema: {type: object}}}}
components:
  schemas:
    Base:
      type: object
      properties: {id: {type: integer}}
    NewPet:
      allOf:
        - {$ref: '#/components/schemas/Base'}
        - type: object
          required: [name]
          properties:
            name: {type: string, description: 이름}
            owner: {$ref: '#/components/schemas/Owner'}
    Owner:
      type: object
      properties:
        pets: {type: array, items: {$ref: '#/components/schemas/NewPet'}}
        remote: {$ref: 'https://evil.example.com/x.json#/Y'}
"""


def test_parse_petstore_yaml() -> None:
    parsed = openapi_tools.parse_operations(openapi_tools.load_spec(PETSTORE))
    assert parsed["title"] == "펫스토어" and parsed["base_url"] == "https://petstore.example.com/v1"
    assert parsed["total"] == 5 and not parsed["truncated"]
    ops = {o["id"]: o for o in parsed["operations"]}
    get = ops["getPetById"]
    assert get["method"] == "GET" and get["path"] == "/pet/{petId}"
    params = {(p["in"], p["name"]): p for p in get["parameters"]}
    assert set(params) == {
        ("path", "petId"),
        ("query", "verbose"),
        ("header", "X-Trace"),
    }  # 쿠키는 뺀다
    assert params[("path", "petId")]["required"] and params[("path", "petId")]["type"] == "integer"
    assert params[("query", "verbose")]["default"] is False
    add = ops["addPet"]
    schema = add["body_schema"]
    assert add["body_required"] is True and schema["required"] == ["name"]
    assert set(schema["properties"]) == {"id", "name", "owner"}  # allOf 합치기, $ref 풀기
    owner = schema["properties"]["owner"]
    assert (
        "pets" in owner["properties"] and owner["properties"].get("remote") == {}
    )  # 바깥 참조는 비운다
    assert ops["delete_pet_petId"]["method"] == "DELETE"  # operationId가 없으면 만들어 준다
    listing = next(o for o in parsed["operations"] if o["method"] == "GET" and o["path"] == "/pet")
    assert listing["id"] == "get_pet" and any(
        p["enum"] == ["available", "sold"] for p in listing["parameters"]
    )
    assert next(o for o in parsed["operations"] if o["path"] == "/upload")["body_schema"] is None


def test_spec_limits_and_errors() -> None:
    with pytest.raises(NodeError, match="1MB"):
        openapi_tools.load_spec("a: " + "x" * 1_100_000)
    with pytest.raises(NodeError, match="OpenAPI 3"):
        openapi_tools.load_spec('{"swagger": "2.0", "paths": {"/a": {}}}')
    with pytest.raises(NodeError, match="읽지 못했어요"):
        openapi_tools.load_spec("openapi: 3.0.0\npaths: [unclosed")
    with pytest.raises(NodeError, match="비어 있어요"):
        openapi_tools.load_spec("   ")
    with pytest.raises(NodeError, match="paths"):
        openapi_tools.load_spec('{"openapi": "3.0.0", "paths": {}}')
    big = {"openapi": "3.0.0", "paths": {f"/p{i}": {"get": {"summary": "s"}} for i in range(260)}}
    parsed = openapi_tools.parse_operations(openapi_tools.load_spec(json.dumps(big)))
    assert len(parsed["operations"]) == 200 and parsed["total"] == 260 and parsed["truncated"]
    with pytest.raises(NodeError, match="하나 이상"):
        openapi_tools.pick(parsed, ["nope"])
    # 순환 참조도 끝나고 멈춘다
    loop = {
        "openapi": "3.0.0",
        "paths": {
            "/a": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/A"}}
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "A": {"type": "object", "properties": {"me": {"$ref": "#/components/schemas/A"}}}
            }
        },
    }
    out = openapi_tools.parse_operations(loop)
    assert out["operations"][0]["body_schema"]["type"] == "object"


# ---------------- API 도구(API) ----------------
def preview(client: TestClient, team: Team, role: str = "builder", **body: Any) -> Any:
    return client.post(
        f"/api/v1/workspaces/{team.ws}/api-tools/preview", json=body, headers=team.h(role)
    )


def test_preview_from_text_and_url(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = preview(client, team, text=PETSTORE)
    assert r.status_code == 200 and r.json()["total"] == 5
    seen: list[str] = []

    def fake_get(method: str, url: str, **kw: Any) -> dict[str, Any]:
        seen.append(url)
        return {"status": 200, "body": PETSTORE, "headers": {}}

    monkeypatch.setattr(safe_http, "request", fake_get)
    r = preview(client, team, url="https://example.com/openapi.yaml")
    assert r.status_code == 200 and seen == ["https://example.com/openapi.yaml"]
    # 둘 다 비었거나 둘 다 있으면 안내 오류
    for body in ({}, {"text": "a", "url": "https://x.example.com/a"}):
        bad = preview(client, team, **body)
        assert bad.status_code == 422 and bad.json()["detail"]["hint"]
    # 사설 주소는 safe_http가 막는다(여기서는 같은 오류 경로 확인)
    monkeypatch.undo()
    blocked = preview(client, team, url="http://127.0.0.1/spec.json")
    assert blocked.status_code == 422


def create_tool_set(client: TestClient, team: Team, role: str = "owner", **extra: Any) -> Any:
    return client.post(
        f"/api/v1/workspaces/{team.ws}/api-tools",
        json={"name": "펫스토어", "text": PETSTORE, **extra},
        headers=team.h(role),
    )


def test_create_list_get_tool_set(client: TestClient, team: Team) -> None:
    r = create_tool_set(client, team, selected=["getPetById", "addPet"])
    assert r.status_code == 201, r.text
    assert r.json()["tools"] == 2 and r.json()["base_url"] == "https://petstore.example.com/v1"
    sid = r.json()["id"]
    lst = client.get(f"/api/v1/workspaces/{team.ws}/api-tools", headers=team.h("builder")).json()
    assert [(x["name"], x["tools"], x["auth_type"]) for x in lst] == [("펫스토어", 2, "none")]
    detail = client.get(
        f"/api/v1/workspaces/{team.ws}/api-tools/{sid}", headers=team.h("builder")
    ).json()
    assert {o["id"] for o in detail["operations"]} == {"getPetById", "addPet"}
    # 일반 연결 정보 목록에는 큰 도구 목록이 그대로 새지 않는다(마스킹)
    creds = client.get(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials", headers=team.h("builder")
    )
    assert "getPetById" not in creds.text
    # 기본 주소를 바꾸거나 직접 넣을 수 있고, 명세에 서버가 없으면 꼭 넣어야 한다
    bare = json.dumps({"openapi": "3.0.0", "paths": {"/a": {"get": {"summary": "a"}}}})
    no_base = client.post(
        f"/api/v1/workspaces/{team.ws}/api-tools",
        json={"name": "x", "text": bare},
        headers=team.h("owner"),
    )
    assert no_base.status_code == 422 and "기본 주소" in no_base.json()["detail"]["message"]
    ok = client.post(
        f"/api/v1/workspaces/{team.ws}/api-tools",
        json={"name": "x", "text": bare, "base_url": "https://api.example.com/"},
        headers=team.h("owner"),
    )
    assert ok.status_code == 201 and ok.json()["base_url"] == "https://api.example.com"


def test_tool_set_auth_must_be_http_credentials(client: TestClient, team: Team) -> None:
    bad = create_tool_set(client, team, auth_type="bearer", auth_credential_id="missing")
    assert bad.status_code == 422 and "HTTP 인증 정보" in bad.json()["detail"]["message"]
    weird = create_tool_set(client, team, auth_type="oauth")
    assert weird.status_code == 422


@pytest.mark.parametrize("role", ROLES)
def test_api_tool_permissions(client: TestClient, team: Team, role: str) -> None:
    sid = create_tool_set(client, team).json()["id"]
    base = f"/api/v1/workspaces/{team.ws}/api-tools"
    use = role in ("owner", "admin", "builder")
    assert preview(client, team, role, text=PETSTORE).status_code == (200 if use else 403)
    assert client.get(base, headers=team.h(role)).status_code == (200 if use else 403)
    assert client.get(f"{base}/{sid}", headers=team.h(role)).status_code == (200 if use else 403)
    created = create_tool_set(client, team, role)
    assert created.status_code == (201 if role in ("owner", "admin") else 403)


def test_api_tool_node_calls_api(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(client, team, "http_credentials")
    auth = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={
            "connector_key": "http_credentials",
            "name": "펫 토큰",
            "secrets": {"token": "pet-token-9999"},
        },
        headers=team.h("owner"),
    ).json()["id"]
    sid = create_tool_set(client, team, auth_type="bearer", auth_credential_id=auth).json()["id"]
    sent: list[dict[str, Any]] = []

    def fake(
        method: str, url: str, *, headers: dict[str, str] | None = None, body: Any = None, **kw: Any
    ) -> dict[str, Any]:
        sent.append({"method": method, "url": url, "headers": headers or {}, "body": body})
        if "/pet/404" in url:
            return {"status": 404, "body": {"message": "없음"}, "headers": {}}
        return {"status": 200, "body": {"id": 7, "name": "초코"}, "headers": {}}

    monkeypatch.setattr(safe_http, "request", fake)
    graph: dict[str, Any] = {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "id"}, {"key": "trace"}]}},
            {
                "id": "n2",
                "type": "api_tool",
                "data": {
                    "tool_set": sid,
                    "operation": "getPetById",
                    "params": {"petId": "{{n1.id}}", "verbose": True, "X-Trace": "{{n1.trace}}"},
                },
            },
            {
                "id": "n3",
                "type": "output",
                "data": {"template": "{{n2.status}}/{{n2.ok}}/{{n2.body.name}}"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
        ],
    }
    app_id = make_app(client, team, graph)
    assert validate(client, team, app_id)["valid"]
    d = start(client, team, app_id, {"id": "7/../x y", "trace": "t-1"})
    assert d["status"] == "succeeded", d["error"]
    call = sent[0]
    assert call["method"] == "GET"
    # 경로 값은 주소 조각으로 안전하게 바뀌고, 검색 조건·헤더·인증이 붙는다
    assert call["url"] == "https://petstore.example.com/v1/pet/7%2F..%2Fx%20y?verbose=true"
    assert (
        call["headers"]["X-Trace"] == "t-1"
        and call["headers"]["Authorization"] == "Bearer pet-token-9999"
    )
    assert d["output"]["text"] == "200/True/초코"
    assert "pet-token-9999" not in json.dumps(d)
    assert any("API 도구 'getPetById'" in s["summary"] for s in d["steps"] if s["node_id"] == "n2")
    # 오류 응답 코드는 값으로 받는다(기본). 필수 값이 비면 안내 오류.
    missing = start(client, team, app_id, {"id": "", "trace": ""})
    assert missing["status"] == "failed" and "petId" in missing["error"]
    not_found = start(client, team, app_id, {"id": "404", "trace": "x"})
    assert not_found["output"]["text"].startswith("404/False")
    api_node: Any = graph["nodes"][1]
    api_node["data"]["fail_on_error_status"] = True
    strict = start(client, team, make_app(client, team, graph), {"id": "404", "trace": "x"})
    assert strict["status"] == "failed" and "404" in strict["error"]


def test_api_tool_body_and_validator(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = create_tool_set(client, team).json()["id"]
    sent: list[dict[str, Any]] = []

    def fake(
        method: str, url: str, *, headers: dict[str, str] | None = None, body: Any = None, **kw: Any
    ) -> dict[str, Any]:
        sent.append({"method": method, "url": url, "body": body})
        return {"status": 201, "body": {"id": 1}, "headers": {}}

    monkeypatch.setattr(safe_http, "request", fake)

    def flow(tool_set: str, body: Any) -> dict[str, Any]:
        return {
            "nodes": [
                {"id": "n1", "type": "input", "data": {"fields": [{"key": "name"}]}},
                {
                    "id": "n2",
                    "type": "api_tool",
                    "data": {
                        "tool_set": tool_set,
                        "operation": "addPet",
                        "params": {},
                        "body": body,
                    },
                },
                {"id": "n3", "type": "output", "data": {"template": "{{n2.status}}"}},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2"},
                {"id": "e2", "source": "n2", "target": "n3"},
            ],
        }

    app_id = make_app(client, team, flow(sid, {"name": "{{n1.name}}"}))
    d = start(client, team, app_id, {"name": "나비"})
    assert d["status"] == "succeeded" and sent[0]["method"] == "POST"
    assert sent[0]["body"] == {"name": "나비"}
    empty = start(client, team, make_app(client, team, flow(sid, None)), {"name": "x"})
    assert empty["status"] == "failed" and "본문" in empty["error"]
    # 도구 묶음이 아닌 연결 정보 / 없는 묶음은 검증에서 걸린다
    v = validate(client, team, make_app(client, team, flow("no-such-set", {"name": "a"})))
    assert not v["valid"]
