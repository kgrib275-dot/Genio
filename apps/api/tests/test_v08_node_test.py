"""v0.8 단계 하나만 시험: 값 채우기, 단독 실행, 저장 전 설정으로 시험, 사람 단계·권한·안전 규칙."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.tests.conftest import ROLES, Team, add_llm
from api.tests.fakes import FakeAdapter

GRAPH: dict[str, Any] = {
    "nodes": [
        {
            "id": "n1",
            "type": "input",
            "data": {
                "label": "입력",
                "fields": [
                    {"key": "name", "label": "이름", "type": "text", "required": True},
                    {"key": "qty", "label": "수량", "type": "number"},
                ],
            },
        },
        {
            "id": "n2",
            "type": "template",
            "data": {"label": "계산", "template": "{{n1.name}}: {{ 100 // n1.qty }}"},
        },
        {"id": "n3", "type": "output", "data": {"template": "{{n2.output}}"}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ],
}


def _app(client: TestClient, team: Team, graph: dict[str, Any] | None = None) -> str:
    h = team.h("builder")
    app_id: str = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "단계 시험"}, headers=h
    ).json()["id"]
    assert (
        client.put(
            f"/api/v1/apps/{app_id}/draft", json={"graph": graph or GRAPH}, headers=h
        ).status_code
        == 200
    )
    return app_id


def _run_once(client: TestClient, team: Team, app_id: str, inp: dict[str, Any]) -> None:
    r = client.post(f"/api/v1/apps/{app_id}/runs", json={"input": inp}, headers=team.h("builder"))
    assert r.status_code == 201, r.text


def _url(app_id: str, node: str, kind: str = "test") -> str:
    return f"/api/v1/apps/{app_id}/nodes/{node}/{'test-inputs' if kind == 'inputs' else 'test'}"


def test_inputs_prefilled_from_last_success(client: TestClient, team: Team) -> None:
    app_id = _app(client, team)
    _run_once(client, team, app_id, {"name": "김", "qty": 5})
    r = client.post(_url(app_id, "n2", "inputs"), json={}, headers=team.h("builder"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["testable"] and d["label"] == "계산" and d["last_run_id"]
    assert d["warn"] is None
    g = d["groups"][0]
    assert g["scope"] == "n1" and g["label"] == "입력"
    fields = {f["field"]: f for f in g["fields"]}
    assert fields["name"]["value"] == "김" and fields["name"]["kind"] == "string"
    assert fields["qty"]["value"] == 5 and fields["qty"]["kind"] == "number"
    assert fields["name"]["path"] == "{{n1.name}}" and fields["name"]["from_last_run"]


def test_run_with_last_run_values_and_overrides(client: TestClient, team: Team) -> None:
    app_id = _app(client, team)
    _run_once(client, team, app_id, {"name": "김", "qty": 5})
    h = team.h("builder")
    r = client.post(_url(app_id, "n2"), json={}, headers=h)  # 값을 안 보내면 최근 성공 값
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and d["output"]["output"] == "김: 20" and d["error"] is None
    assert d["ms"] >= 0 and d["summary"]
    r = client.post(
        _url(app_id, "n2"), json={"values": {"n1": {"name": "박", "qty": 4}}}, headers=h
    )
    assert r.json()["output"]["output"] == "박: 25"
    # 실행 기록은 남기지 않는다
    runs = client.get(f"/api/v1/apps/{app_id}/runs", headers=h).json()
    assert len(runs) == 1


def test_error_is_two_lines(client: TestClient, team: Team) -> None:
    app_id = _app(client, team)
    h = team.h("builder")
    r = client.post(
        _url(app_id, "n2"), json={"values": {"n1": {"name": "박", "qty": 0}}}, headers=h
    )
    d = r.json()
    assert r.status_code == 200 and d["ok"] is False and d["output"] is None
    assert d["error"]["message"] and d["error"]["hint"]
    # 아직 실행한 적이 없고 값도 안 주면 값이 비어 있다는 안내가 나온다
    r2 = client.post(_url(app_id, "n2", "inputs"), json={}, headers=h).json()
    assert r2["last_run_id"] is None
    assert all(not f["from_last_run"] for f in r2["groups"][0]["fields"])


def test_unsaved_settings_are_tested(client: TestClient, team: Team) -> None:
    app_id = _app(client, team)
    _run_once(client, team, app_id, {"name": "김", "qty": 5})
    h = team.h("builder")
    body = {"data": {"label": "계산", "template": "안녕 {{n1.name}}님, {{n1.qty}}개"}}
    inputs = client.post(_url(app_id, "n2", "inputs"), json=body, headers=h).json()
    assert {f["field"] for f in inputs["groups"][0]["fields"]} == {"name", "qty"}
    out = client.post(_url(app_id, "n2"), json=body, headers=h).json()
    assert out["output"]["output"] == "안녕 김님, 5개"
    # 저장된 흐름은 그대로다
    saved = client.get(f"/api/v1/apps/{app_id}", headers=h).json()
    tpl = next(n for n in saved["draft_graph"]["nodes"] if n["id"] == "n2")["data"]["template"]
    assert tpl.startswith("{{n1.name}}")


def test_person_nodes_and_missing_node(client: TestClient, team: Team) -> None:
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "m"}]}},
            {"id": "ap", "type": "approval", "data": {"message": "{{n1.m}} 승인?"}},
            {"id": "n3", "type": "output", "data": {"template": "끝"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "ap"},
            {"id": "e2", "source": "ap", "target": "n3"},
        ],
    }
    app_id = _app(client, team, graph)
    h = team.h("builder")
    d = client.post(_url(app_id, "ap", "inputs"), json={}, headers=h).json()
    assert d["testable"] is False and "사람 단계" in d["reason"]
    r = client.post(_url(app_id, "ap"), json={}, headers=h)
    assert (
        r.status_code == 422
        and "사람 단계는 단독으로 시험할 수 없어요" in r.json()["detail"]["message"]
    )
    assert r.json()["detail"]["hint"]
    r = client.post(_url(app_id, "nope"), json={}, headers=h)
    assert r.status_code == 404 and r.json()["detail"]["hint"]


def test_warnings_for_side_effect_nodes(client: TestClient, team: Team) -> None:
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "m"}]}},
            {
                "id": "h1",
                "type": "http",
                "data": {"method": "POST", "url": "https://example.com/x"},
            },
            {"id": "h2", "type": "http", "data": {"method": "GET", "url": "https://example.com/x"}},
            {"id": "l1", "type": "llm", "data": {"provider": "default", "prompt": "{{n1.m}}"}},
            {"id": "n9", "type": "output", "data": {"template": "끝"}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n9"}],
    }
    app_id = _app(client, team, graph)
    h = team.h("builder")
    warn = {
        n: client.post(_url(app_id, n, "inputs"), json={}, headers=h).json()["warn"]
        for n in ("h1", "h2", "l1")
    }
    assert "실제 요청" in warn["h1"] and warn["h2"] is None and "비용" in warn["l1"]


def test_safety_rules_apply(client: TestClient, team: Team) -> None:
    """실제 실행과 같은 사설망 차단이 적용된다."""
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": []}},
            {
                "id": "h",
                "type": "http",
                "data": {"method": "GET", "url": "http://127.0.0.1:8000/health"},
            },
            {"id": "n9", "type": "output", "data": {"template": "끝"}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n9"}],
    }
    app_id = _app(client, team, graph)
    d = client.post(_url(app_id, "h"), json={}, headers=team.h("builder")).json()
    assert d["ok"] is False and d["error"]["message"] and d["error"]["hint"]


def test_llm_node_counts_tokens(client: TestClient, team: Team, fake_llm: FakeAdapter) -> None:
    add_llm(client, team)
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "m"}]}},
            {
                "id": "l1",
                "type": "llm",
                "data": {"provider": "default", "prompt": "요약: {{n1.m}}"},
            },
            {"id": "n9", "type": "output", "data": {"template": "{{l1.text}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "l1"},
            {"id": "e2", "source": "l1", "target": "n9"},
        ],
    }
    app_id = _app(client, team, graph)
    d = client.post(
        _url(app_id, "l1"), json={"values": {"n1": {"m": "안녕하세요"}}}, headers=team.h("builder")
    ).json()
    assert d["ok"] and d["output"]["text"] and d["tokens"]["input_tokens"] > 0


@pytest.mark.parametrize("role", ROLES)
def test_node_test_permissions(client: TestClient, team: Team, role: str) -> None:
    app_id = _app(client, team)
    allowed = role in ("owner", "admin", "builder")
    for kind in ("inputs", "test"):
        r = client.post(
            _url(app_id, "n2", kind),
            json={"values": {"n1": {"name": "김", "qty": 5}}} if kind == "test" else {},
            headers=team.h(role),
        )
        assert (r.status_code == 200) == allowed, (role, kind, r.status_code)


def test_node_test_outsider_denied(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    app_id = _app(client, team)
    for kind in ("inputs", "test"):
        r = client.post(_url(app_id, "n2", kind), json={}, headers=outsider)
        assert r.status_code in (403, 404)
    assert client.post(_url(app_id, "n2"), json={}).status_code == 401
