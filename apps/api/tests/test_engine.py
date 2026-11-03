"""실행 엔진: 단계 6종(input/llm/condition/http/code/output) + 승인 재개 + 재시도 + 비용."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.db import SessionLocal
from api.engine import safe_http
from api.engine.code_runner import RestrictedPythonRunner
from api.engine.templating import evaluate, render, render_value
from api.models import Run
from api.tests.conftest import Team, add_llm
from api.tests.fakes import FakeAdapter
from nodes import NodeError


def make_app(client: TestClient, team: Team, graph: dict[str, Any]) -> str:
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/apps",
        json={"name": "엔진 테스트"},
        headers=team.h("builder"),
    )
    app_id: str = res.json()["id"]
    res = client.put(
        f"/api/v1/apps/{app_id}/draft", json={"graph": graph}, headers=team.h("builder")
    )
    assert res.status_code == 200, res.text
    return app_id


def run(client: TestClient, team: Team, app_id: str, inp: dict[str, Any]) -> dict[str, Any]:
    res = client.post(f"/api/v1/apps/{app_id}/runs", json={"input": inp}, headers=team.h("builder"))
    assert res.status_code == 201, res.text
    detail = client.get(f"/api/v1/runs/{res.json()['id']}", headers=team.h("operator"))
    assert detail.status_code == 200
    data: dict[str, Any] = detail.json()
    return data


CLASSIFY_GRAPH: dict[str, Any] = {
    "version": 1,
    "nodes": [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "message", "required": True}]}},
        {
            "id": "n2",
            "type": "llm",
            "data": {
                "prompt": "{{n1.message}}",
                "temperature": 0.2,
                "output_schema": {"type": "object", "properties": {"category": {"type": "string"}}},
            },
        },
        {
            "id": "n3",
            "type": "condition",
            "data": {
                "cases": [
                    {"id": "billing", "when": "{{n2.category}} == 'billing'"},
                    {"id": "tech", "when": "{{n2.category}} == 'tech'"},
                ],
                "else": "other",
            },
        },
        {
            "id": "n4",
            "type": "code",
            "data": {
                "inputs": {"msg": "{{n1.message}}"},
                "code": "result = {'length': len(inputs['msg'])}",
            },
        },
        {"id": "n5", "type": "output", "data": {"template": "결제 문의({{n4.length}}자)"}},
        {"id": "n6", "type": "output", "data": {"template": "분류: {{n2.category}}"}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
        {"id": "e3", "source": "n3", "sourceHandle": "billing", "target": "n4"},
        {"id": "e4", "source": "n4", "target": "n5"},
        {"id": "e5", "source": "n3", "sourceHandle": "tech", "target": "n6"},
        {"id": "e6", "source": "n3", "sourceHandle": "other", "target": "n6"},
    ],
    "variables": {},
}


def test_classify_flow_runs_selected_branch_only(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    app_id = make_app(client, team, CLASSIFY_GRAPH)
    detail = run(client, team, app_id, {"message": "결제가 두 번 됐어요"})
    assert detail["status"] == "succeeded", detail["error"]
    assert detail["output"]["text"] == "결제 문의(11자)"
    executed = [s["node_id"] for s in detail["steps"]]
    assert executed == ["n1", "n2", "n3", "n4", "n5"]
    assert detail["token_usage"] == {"input_tokens": 100, "output_tokens": 20}
    # claude-sonnet-5-5: (100*2 + 20*10)/1M
    assert detail["cost"] == pytest.approx(0.0004)

    tech = run(client, team, app_id, {"message": "로그인 오류가 나요"})
    assert tech["output"]["text"] == "분류: tech"
    assert [s["node_id"] for s in tech["steps"]] == ["n1", "n2", "n3", "n6"]


def test_required_input_missing_fails_with_korean_message(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    app_id = make_app(client, team, CLASSIFY_GRAPH)
    detail = run(client, team, app_id, {})
    assert detail["status"] == "failed"
    assert "필수 입력이 비어 있어요" in detail["error"]


def test_llm_without_provider_explains_how_to_fix(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, CLASSIFY_GRAPH)
    detail = run(client, team, app_id, {"message": "안녕"})
    assert detail["status"] == "failed"
    assert "등록된 AI 연결이 없어요" in detail["error"]
    assert "API 키를 등록" in detail["error"]


def test_invalid_draft_cannot_run(client: TestClient, team: Team) -> None:
    graph = {**CLASSIFY_GRAPH, "edges": CLASSIFY_GRAPH["edges"][:2]}
    app_id = make_app(client, team, graph)
    res = client.post(
        f"/api/v1/apps/{app_id}/runs", json={"input": {"message": "x"}}, headers=team.h("builder")
    )
    assert res.status_code == 422
    assert res.json()["detail"]["errors"]


HTTP_GRAPH: dict[str, Any] = {
    "version": 1,
    "nodes": [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "q"}]}},
        {
            "id": "n2",
            "type": "http",
            "data": {"method": "GET", "url": "https://api.example.com/items?q={{n1.q}}"},
        },
        {"id": "n3", "type": "output", "data": {"template": "{{n2.status}} {{n2.body}}"}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ],
    "variables": {},
}


def test_http_node_retries_then_succeeds(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_request(method: str, url: str, **kw: Any) -> dict[str, Any]:
        calls.append(url)
        if len(calls) < 3:
            raise NodeError("상대 서버 오류", retryable=True)
        return {"status": 200, "body": {"ok": True}, "headers": {}}

    monkeypatch.setattr(safe_http, "request", fake_request)
    monkeypatch.setattr("api.engine.executor.time.sleep", lambda s: None)
    app_id = make_app(client, team, HTTP_GRAPH)
    detail = run(client, team, app_id, {"q": "사과"})
    assert detail["status"] == "succeeded", detail["error"]
    assert len(calls) == 3
    assert calls[0] == "https://api.example.com/items?q=사과"
    assert detail["output"]["text"] == '200 {"ok": true}'
    assert "다시 시도" in detail["steps"][1]["logs"]


def test_http_node_blocks_private_address(client: TestClient, team: Team) -> None:
    graph = {
        **HTTP_GRAPH,
        "nodes": [
            HTTP_GRAPH["nodes"][0],
            {**HTTP_GRAPH["nodes"][1], "data": {"url": "http://127.0.0.1:8000/health"}},
            HTTP_GRAPH["nodes"][2],
        ],
    }
    app_id = make_app(client, team, graph)
    detail = run(client, team, app_id, {"q": "x"})
    assert detail["status"] == "failed"
    assert "내부" in detail["error"] or "사내망" in detail["error"]


APPROVAL_GRAPH: dict[str, Any] = {
    "version": 1,
    "nodes": [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "message"}]}},
        {"id": "n2", "type": "approval", "data": {"message": "보낼까요? {{n1.message}}"}},
        {
            "id": "n3",
            "type": "output",
            "data": {"template": "승인됨: {{n2.approved}} / {{n2.comment}}"},
        },
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ],
    "variables": {},
}


def test_approval_waits_and_resumes(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, APPROVAL_GRAPH)
    detail = run(client, team, app_id, {"message": "주간 보고"})
    assert detail["status"] == "waiting_approval"
    assert detail["approval"]["message"] == "보낼까요? 주간 보고"
    assert detail["steps"][-1]["status"] == "waiting_approval"
    assert (
        client.post(
            f"/api/v1/runs/{detail['id']}/approve",
            json={"approved": True},
            headers=team.h("member"),
        ).status_code
        == 403
    )
    res = client.post(
        f"/api/v1/runs/{detail['id']}/approve",
        json={"approved": True, "comment": "좋아요"},
        headers=team.h("operator"),
    )
    assert res.status_code == 200, res.text
    done = res.json()
    assert done["status"] == "succeeded", (done["error"], done["steps"])
    assert done["output"]["text"] == "승인됨: True / 좋아요"
    again = client.post(
        f"/api/v1/runs/{detail['id']}/approve", json={"approved": True}, headers=team.h("owner")
    )
    assert again.status_code == 409


def test_approval_rejected_stops(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, APPROVAL_GRAPH)
    detail = run(client, team, app_id, {"message": "x"})
    res = client.post(
        f"/api/v1/runs/{detail['id']}/approve", json={"approved": False}, headers=team.h("admin")
    )
    assert res.json()["status"] == "failed"
    assert "거절" in res.json()["error"]


def test_run_events_stream_ends(client: TestClient, team: Team, fake_llm: FakeAdapter) -> None:
    add_llm(client, team)
    app_id = make_app(client, team, CLASSIFY_GRAPH)
    run_id = client.post(
        f"/api/v1/apps/{app_id}/runs",
        json={"input": {"message": "환불"}},
        headers=team.h("builder"),
    ).json()["id"]
    with client.stream("GET", f"/api/v1/runs/{run_id}/events", headers=team.h("operator")) as res:
        body = "".join(res.iter_text())
    assert "event: run" in body
    assert body.count("event: step") == 5
    assert "event: end" in body


def test_run_timeout_marks_failed(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = make_app(client, team, APPROVAL_GRAPH)
    monkeypatch.setattr(get_settings(), "genio_run_timeout_seconds", -1)
    detail = run(client, team, app_id, {"message": "x"})
    assert detail["status"] == "failed"
    assert "10분" in detail["error"]
    monkeypatch.undo()
    with SessionLocal() as db:
        assert db.get(Run, detail["id"]) is not None


# ----- 템플릿·조건식 -----
def test_templating_and_conditions() -> None:
    scope = {"n1": {"message": "안녕", "n": 3}, "n2": {"tags": ["a", "b"], "obj": {"k": 1}}}
    assert render("{{n1.message}}!", scope) == "안녕!"
    assert render("{{n2.obj}}", scope) == '{"k": 1}'
    assert render("{{n9.x}}", scope) == ""
    assert render_value({"t": "{{n2.tags}}", "s": "x{{n1.n}}"}, scope) == {
        "t": ["a", "b"],
        "s": "x3",
    }
    assert evaluate("{{n1.n}} > 2 and contains({{n1.message}}, '안')", scope) is True
    assert evaluate("{{n1.message}} == 'billing'", scope) is False


def test_template_sandbox_blocks_attribute_escape() -> None:
    from api.engine.templating import TemplateRenderError

    with pytest.raises(TemplateRenderError):
        render("{{ ''.__class__.__mro__[1].__subclasses__() }}", {})


def test_condition_eval_blocks_dunder() -> None:
    with pytest.raises(Exception):  # noqa: B017 - simpleeval 예외 종류는 여러 가지
        evaluate("{{n1.x}}.__class__", {"n1": {"x": 1}})


# ----- 코드 단계 실행기 -----
def test_code_runner_ok_blocked_and_timeout() -> None:
    runner = RestrictedPythonRunner(timeout=3)
    assert runner.run("import math\nresult = {'v': math.floor(inputs['x'] * 2)}", {"x": 1.7}) == {
        "v": 3
    }
    with pytest.raises(NodeError) as blocked:
        runner.run("import socket\nresult = {}", {})
    assert "쓸 수 없어요" in blocked.value.message
    with pytest.raises(NodeError) as opened:
        runner.run("result = {'x': open('/etc/passwd').read()}", {})
    assert "오류" in opened.value.message
    with pytest.raises(NodeError) as slow:
        RestrictedPythonRunner(timeout=1).run("while True:\n    pass", {})
    assert "초 안에 끝나지" in slow.value.message


# ----- SSRF -----
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1:8080/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://100.100.100.100/",
        "file:///etc/passwd",
        "ftp://example.com/",
    ],
)
def test_ssrf_blocked(url: str) -> None:
    with pytest.raises(NodeError):
        safe_http.check_url(url)


def test_declared_domains_enforced() -> None:
    with pytest.raises(NodeError) as exc:
        safe_http.check_url("https://evil.example.com/", allowed_domains=["slack.com"])
    assert "선언한 도메인" in exc.value.message
