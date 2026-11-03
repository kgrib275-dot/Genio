"""v0.2 단계 10종 + 단계 재시도·실패 처리 + 환경 값 실행 테스트."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.engine import safe_http
from api.tests.conftest import Team, add_llm
from api.tests.fakes import FakeAdapter, text_turn, tool_turn
from nodes import NodeError


def inp(*fields: str, file: str | None = None) -> dict[str, Any]:
    fs: list[dict[str, Any]] = [{"key": f, "required": False} for f in fields]
    if file:
        fs.append({"key": file, "type": "file", "required": False})
    return {"id": "n1", "type": "input", "data": {"fields": fs}}


def chain(*nodes: dict[str, Any], edges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if edges is None:
        edges = [
            {"id": f"e{i}", "source": nodes[i]["id"], "target": nodes[i + 1]["id"]}
            for i in range(len(nodes) - 1)
        ]
    return {"version": 1, "nodes": list(nodes), "edges": edges, "variables": {}}


def out(template: str, nid: str = "n9") -> dict[str, Any]:
    return {"id": nid, "type": "output", "data": {"template": template}}


def run_graph(
    client: TestClient, team: Team, graph: dict[str, Any], inputs: dict[str, Any]
) -> dict[str, Any]:
    app_id = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "v02"}, headers=team.h("builder")
    ).json()["id"]
    assert (
        client.put(
            f"/api/v1/apps/{app_id}/draft", json={"graph": graph}, headers=team.h("builder")
        ).status_code
        == 200
    )
    v = client.post(f"/api/v1/apps/{app_id}/validate", json={}, headers=team.h("builder")).json()
    assert v["valid"], v["errors"]
    run = client.post(
        f"/api/v1/apps/{app_id}/runs", json={"input": inputs}, headers=team.h("builder")
    ).json()
    detail: dict[str, Any] = client.get(
        f"/api/v1/runs/{run['id']}", headers=team.h("builder")
    ).json()
    detail["app_id"] = app_id
    return detail


def test_question_classifier_routes_by_class(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    g = chain(
        inp("message"),
        {
            "id": "n2",
            "type": "question_classifier",
            "data": {
                "query": "{{n1.message}}",
                "classes": [
                    {"id": "billing", "name": "결제"},
                    {"id": "tech", "name": "기술"},
                    {"id": "other"},
                ],
            },
        },
        out("결제팀: {{n2.class_name}}", "n3"),
        out("기술팀", "n4"),
        out("기타", "n5"),
        edges=[
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "sourceHandle": "billing", "target": "n3"},
            {"id": "e3", "source": "n2", "sourceHandle": "tech", "target": "n4"},
            {"id": "e4", "source": "n2", "sourceHandle": "other", "target": "n5"},
        ],
    )
    # FakeAdapter는 enum 스키마의 class_id에 billing/tech/other 규칙으로 답한다
    fake_llm_classify = run_graph(client, team, g, {"message": "환불해 주세요"})
    assert fake_llm_classify["output"]["text"] == "결제팀: 결제"
    tech = run_graph(client, team, g, {"message": "로그인 오류"})
    assert tech["output"]["text"] == "기술팀"


def test_parameter_extractor_and_template(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    g = chain(
        inp("message"),
        {
            "id": "n2",
            "type": "parameter_extractor",
            "data": {
                "query": "{{n1.message}}",
                "parameters": [
                    {"name": "who", "type": "string", "required": True},
                    {"name": "when", "type": "string"},
                ],
            },
        },
        {
            "id": "n3",
            "type": "template",
            "data": {"template": "{% if n2.__is_success %}OK:{{ n2.who }}{% else %}NO{% endif %}"},
        },
        out("{{n3.output}}"),
    )
    d = run_graph(client, team, g, {"message": "김철수 내일 방문"})
    assert d["status"] == "succeeded", d["error"]
    assert d["output"]["text"].startswith("OK:who: 김철수")


def test_aggregator_list_iteration_loop(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    g = chain(
        inp("csv"),
        {
            "id": "n2",
            "type": "code",
            "data": {
                "inputs": {"s": "{{n1.csv}}"},
                "code": "result = {'items': [x.strip() for x in inputs['s'].split(',')]}",
            },
        },
        {
            "id": "n3",
            "type": "list_operator",
            "data": {
                "input": "{{n2.items}}",
                "filter": {"operator": "not_contains", "value": "x"},
                "sort": {"enabled": True, "order": "desc"},
                "limit": 3,
            },
        },
        {
            "id": "n4",
            "type": "iteration",
            "data": {
                "items": "{{n3.result}}",
                "operation": {"type": "template", "data": {"template": "{{index}}-{{item}}"}},
                "output_key": "output",
            },
        },
        {
            "id": "n5",
            "type": "loop",
            "data": {
                "initial": "a",
                "operation": {"type": "template", "data": {"template": "{{loop.last}}a"}},
                "output_key": "output",
                "break_when": "len({{loop.last}}) >= 4",
                "max_iterations": 10,
            },
        },
        {
            "id": "n6",
            "type": "variable_aggregator",
            "data": {"variables": ["{{n9x.missing}}", "{{n5.last}}"]},
        },
        out("{{n4.results}} | {{n3.count}} | {{n6.output}} | {{n5.iterations}}"),
    )
    g["nodes"][5]["data"]["variables"] = ["", "{{n5.last}}"]
    d = run_graph(client, team, g, {"csv": "b, x1, d, a, c"})
    assert d["status"] == "succeeded", d["error"]
    assert d["output"]["text"] == '["0-d", "1-c", "2-b"] | 3 | aaaa | 3'


def test_document_extractor_reads_uploaded_file(client: TestClient, team: Team) -> None:
    up = client.post(
        f"/api/v1/workspaces/{team.ws}/files",
        files={"file": ("메모.txt", "회의는 금요일 3시".encode(), "text/plain")},
        headers=team.h("builder"),
    )
    assert up.status_code == 200, up.text
    g = chain(
        inp(file="doc"),
        {"id": "n2", "type": "document_extractor", "data": {"file": "{{n1.doc}}"}},
        out("{{n2.filenames}}: {{n2.text}}"),
    )
    d = run_graph(client, team, g, {"doc": up.json()["id"]})
    assert d["output"]["text"] == '["메모.txt"]: 회의는 금요일 3시'
    bad = client.post(
        f"/api/v1/workspaces/{team.ws}/files",
        files={"file": ("a.exe", b"MZ", "x")},
        headers=team.h("builder"),
    )
    assert bad.status_code == 415


def test_variable_assigner_and_env_vars(client: TestClient, team: Team) -> None:
    g = chain(
        inp("name"),
        {
            "id": "n2",
            "type": "variable_assigner",
            "data": {
                "assignments": [
                    {"variable": "who", "value": "{{n1.name}}"},
                    {"variable": "seen", "value": "{{n1.name}}", "mode": "append"},
                ]
            },
        },
        out("{{env.GREETING}}, {{conv.who}} ({{conv.seen}}) / {{env.TOKEN}}"),
    )
    d = run_graph(client, team, g, {"name": "민수"})
    app_id = d["app_id"]
    res = client.put(
        f"/api/v1/apps/{app_id}/env-vars",
        json={
            "env_vars": [
                {"key": "GREETING", "value": "안녕"},
                {"key": "TOKEN", "value": "sec-12345678", "secret": True},
            ]
        },
        headers=team.h("builder"),
    ).json()
    assert {v["key"]: v["value"] for v in res["env_vars"]} == {
        "GREETING": "안녕",
        "TOKEN": "****5678",
    }
    # 마스킹 값을 그대로 다시 보내도 비밀 값은 유지된다
    client.put(
        f"/api/v1/apps/{app_id}/env-vars",
        json={
            "env_vars": [
                {"key": "GREETING", "value": "안녕"},
                {"key": "TOKEN", "value": "****5678", "secret": True},
            ]
        },
        headers=team.h("builder"),
    )
    run = client.post(
        f"/api/v1/apps/{app_id}/runs", json={"input": {"name": "민수"}}, headers=team.h("builder")
    ).json()
    detail = client.get(f"/api/v1/runs/{run['id']}", headers=team.h("builder")).json()
    assert detail["output"]["text"] == '안녕, 민수 (["민수"]) / sec-12345678'
    assert detail["output"]["conv"] == {"who": "민수", "seen": ["민수"]}
    exported = client.get(f"/api/v1/apps/{app_id}/export", headers=team.h("builder")).text
    assert "sec-12345678" not in exported


def test_on_error_default_and_branch_and_retry(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def failing(method: str, url: str, **kw: Any) -> dict[str, Any]:
        calls.append(url)
        raise NodeError("상대 서버가 응답하지 않아요")

    monkeypatch.setattr(safe_http, "request", failing)
    http = {
        "id": "n2",
        "type": "http",
        "data": {
            "url": "https://api.example.com/x",
            "_retry": {"max_retries": 2, "interval_ms": 100},
            "_on_error": "default",
            "_default": {"status": 0, "body": "기본값"},
        },
    }
    d = run_graph(
        client, team, chain(inp("q"), http, out("{{n2.body}} / {{n2.error}}")), {"q": "1"}
    )
    assert d["status"] == "succeeded"
    assert d["output"]["text"] == "기본값 / 상대 서버가 응답하지 않아요"
    assert len(calls) == 3  # 처음 + 재시도 2회
    assert d["steps"][1]["status"] == "failed"

    branch = {**http, "data": {"url": "https://api.example.com/x", "_on_error": "branch"}}
    g = chain(
        inp("q"),
        branch,
        out("정상", "n3"),
        out("실패 길: {{n2.error}}", "n4"),
        edges=[
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
            {"id": "e3", "source": "n2", "sourceHandle": "fail", "target": "n4"},
        ],
    )
    d = run_graph(client, team, g, {"q": "1"})
    assert d["output"]["text"] == "실패 길: 상대 서버가 응답하지 않아요"


def test_fail_handle_requires_branch_setting(client: TestClient, team: Team) -> None:
    g = chain(
        inp("q"),
        {"id": "n2", "type": "template", "data": {"template": "x"}},
        out("a", "n3"),
        out("b", "n4"),
        edges=[
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
            {"id": "e3", "source": "n2", "sourceHandle": "fail", "target": "n4"},
        ],
    )
    app_id = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "x"}, headers=team.h("builder")
    ).json()["id"]
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": g}, headers=team.h("builder"))
    v = client.post(f"/api/v1/apps/{app_id}/validate", json={}, headers=team.h("builder")).json()
    assert not v["valid"] and any("실패' 길" in e["message"] for e in v["errors"])


def test_agent_uses_tools(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_llm(client, team)
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "규정"},
        headers=team.h("builder"),
    ).json()
    client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("r.txt", "출장비 한도는 하루 10만 원이다.".encode(), "text/plain")},
        headers=team.h("builder"),
    )
    monkeypatch.setattr(
        safe_http,
        "request",
        lambda m, u, **kw: {
            "status": 200,
            "body": "<html><body><p>환율 1달러=1300원</p></body></html>",
            "headers": {},
        },
    )
    fake_llm.script = [
        tool_turn(
            "찾아볼게요.",
            ("search_kb_0", {"query": "출장비"}),
            ("read_web_page", {"url": "https://example.com/fx"}),
        ),
        text_turn("출장비는 하루 10만 원이고 환율은 1300원이에요."),
    ]
    g = chain(
        inp("message"),
        {
            "id": "n2",
            "type": "agent",
            "data": {
                "query": "{{n1.message}}",
                "tools": [{"type": "knowledge", "kb_id": kb["id"]}, {"type": "web"}],
                "max_iterations": 3,
            },
        },
        out("{{n2.text}}"),
    )
    d = run_graph(client, team, g, {"message": "출장비 알려 줘"})
    assert d["status"] == "succeeded", d["error"]
    assert d["output"]["text"] == "출장비는 하루 10만 원이고 환율은 1300원이에요."
    calls = d["steps"][1]["output"]["tool_calls"]
    assert [c["name"] for c in calls] == ["search_kb_0", "read_web_page"]
    assert "10만 원" in calls[0]["summary"] and "1300원" in calls[1]["summary"]


def test_agent_calls_other_app_as_tool(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    child = run_graph(client, team, chain(inp("x"), out("하위 앱 결과: {{n1.x}}")), {"x": "1"})
    assert (
        client.post(
            f"/api/v1/apps/{child['app_id']}/versions", json={}, headers=team.h("builder")
        ).status_code
        == 201
    )
    fake_llm.script = [tool_turn("", ("app_x", {"inputs": {"x": "사과"}})), text_turn("끝")]
    g = chain(
        inp("message"),
        {
            "id": "n2",
            "type": "agent",
            "data": {
                "query": "{{n1.message}}",
                "tools": [{"type": "app", "app_id": child["app_id"]}],
            },
        },
        out("{{n2.tool_calls}}"),
    )
    # 도구 이름은 앱 slug에서 만들어지므로 첫 턴을 실제 이름으로 바꾼다
    from api.db import SessionLocal
    from api.models import App

    with SessionLocal() as db:
        app = db.get(App, child["app_id"])
        assert app is not None
        name = "app_" + app.slug.replace("-", "_")
    fake_llm.script[0] = tool_turn("", (name, {"inputs": {"x": "사과"}}))
    d = run_graph(client, team, g, {"message": "하위 앱 불러 줘"})
    assert d["status"] == "succeeded", d["error"]
    assert "하위 앱 결과: 사과" in d["output"]["text"]
