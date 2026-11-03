"""v0.4 블록: 기다리기·값 정리·날짜·시간·다른 앱 실행·데이터 표, 끈 블록 건너뛰기, 캔버스 메모(ADR 0008)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.engine.executor import RunServices
from api.tests.conftest import Team, add_llm
from api.tests.fakes import FakeAdapter


def chain(*nodes: dict[str, Any], edges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """앞뒤로 이어진 그래프(첫 노드는 input)."""
    all_nodes = [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "message", "type": "text"}]}},
        *nodes,
    ]
    if edges is None:
        edges = [
            {"id": f"e{i}", "source": all_nodes[i]["id"], "target": all_nodes[i + 1]["id"]}
            for i in range(len(all_nodes) - 1)
        ]
    return {"version": 1, "nodes": all_nodes, "edges": edges}


def make_app(
    client: TestClient, team: Team, graph: dict[str, Any], *, save: bool = False, name: str = "블록"
) -> str:
    app_id: str = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": name}, headers=team.h("builder")
    ).json()["id"]
    res = client.put(
        f"/api/v1/apps/{app_id}/draft", json={"graph": graph}, headers=team.h("builder")
    )
    assert res.status_code == 200, res.text
    if save:
        assert (
            client.post(
                f"/api/v1/apps/{app_id}/versions", json={}, headers=team.h("builder")
            ).status_code
            == 201
        )
    return app_id


def run(client: TestClient, team: Team, app_id: str, inp: dict[str, Any]) -> dict[str, Any]:
    res = client.post(f"/api/v1/apps/{app_id}/runs", json={"input": inp}, headers=team.h("builder"))
    assert res.status_code == 201, res.text
    data: dict[str, Any] = client.get(
        f"/api/v1/runs/{res.json()['id']}", headers=team.h("operator")
    ).json()
    return data


def out(text: str) -> dict[str, Any]:
    return {"id": "nz", "type": "output", "data": {"template": text}}


def test_nodes_listed(client: TestClient, team: Team) -> None:
    types = {
        n["type"]: n
        for n in client.get(f"/api/v1/workspaces/{team.ws}/nodes", headers=team.h("builder")).json()
    }
    for t in ("wait", "set_fields", "date_time", "run_app", "data_table"):
        assert t in types and types[t]["label"] and types[t]["description"]
    assert types["data_table"]["ui_schema"]["table_id"]["ui:widget"] == "dataTable"
    assert types["run_app"]["ui_schema"]["app_id"]["ui:widget"] == "app"


def test_set_fields_and_date_time(client: TestClient, team: Team) -> None:
    g = chain(
        {
            "id": "n2",
            "type": "set_fields",
            "data": {
                "fields": [
                    {"key": "count", "value": "{{n1.message}}", "type": "number"},
                    {"key": "ok", "value": "예", "type": "boolean"},
                    {"key": "obj", "value": '{"a": 1}', "type": "json"},
                    {"key": "greet", "value": "안녕 {{n1.message}}"},
                ]
            },
        },
        {
            "id": "n3",
            "type": "date_time",
            "data": {
                "operation": "add",
                "value": "2026-01-31",
                "amount": "1",
                "unit": "months",
                "format": "date",
            },
        },
        {
            "id": "n4",
            "type": "date_time",
            "data": {
                "operation": "diff",
                "value": "2026-11-01",
                "other": "2026-11-15",
                "unit": "days",
            },
        },
        {
            "id": "n5",
            "type": "date_time",
            "data": {
                "operation": "format",
                "value": "2026-11-03T05:00:00Z",
                "format": "korean_datetime",
            },
        },
        out(
            "{{n2.count}}|{{n2.ok}}|{{n2.obj.a}}|{{n2.greet}}|{{n3.result}}|{{n4.result}}|{{n5.result}}"
        ),
    )
    app_id = make_app(client, team, g)
    r = run(client, team, app_id, {"message": "42"})
    assert r["status"] == "succeeded", r
    assert r["output"]["text"] == "42|True|1|안녕 42|2026-02-28|14|2026년 11월 03일 14시 00분"

    bad = run(client, team, app_id, {"message": "숫자아님"})
    assert bad["status"] == "failed" and "숫자로 바꿀 수 없어요" in bad["error"]


def test_set_fields_rejects_bad_key(client: TestClient, team: Team) -> None:
    g = chain(
        {"id": "n2", "type": "set_fields", "data": {"fields": [{"key": "1x", "value": "a"}]}},
        out("x"),
    )
    r = run(client, team, make_app(client, team, g), {"message": "a"})
    assert r["status"] == "failed" and "영문" in r["error"]


def test_wait(client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    waited: list[float] = []
    monkeypatch.setattr(RunServices, "wait", lambda self, *, seconds: waited.append(seconds))
    g = chain({"id": "n2", "type": "wait", "data": {"seconds": 3}}, out("{{n2.waited_seconds}}"))
    r = run(client, team, make_app(client, team, g), {"message": "a"})
    assert r["status"] == "succeeded" and waited == [3.0] and r["output"]["text"] == "3.0"
    over = chain({"id": "n2", "type": "wait", "data": {"seconds": 301}}, out("x"))
    # 300초를 넘기면 검증에서 막는다(실행 전)
    res = client.post(
        f"/api/v1/apps/{make_app(client, team, over)}/runs",
        json={"input": {}},
        headers=team.h("builder"),
    )
    assert res.status_code == 422
    assert any(e.get("field") == "seconds" for e in res.json()["detail"]["errors"])


def test_data_table_node(client: TestClient, team: Team) -> None:
    table = client.post(
        f"/api/v1/workspaces/{team.ws}/data-tables",
        json={"name": "방문", "columns": [{"key": "count", "type": "number"}]},
        headers=team.h("builder"),
    ).json()
    g = chain(
        {
            "id": "n2",
            "type": "data_table",
            "data": {
                "table_id": table["id"],
                "operation": "upsert",
                "row_key": "{{n1.message}}",
                "data": {"count": "1", "who": "{{n1.message}}"},
            },
        },
        {
            "id": "n3",
            "type": "data_table",
            "data": {"table_id": table["id"], "operation": "get", "row_key": "{{n1.message}}"},
        },
        {"id": "n4", "type": "data_table", "data": {"table_id": table["id"], "operation": "count"}},
        {
            "id": "n5",
            "type": "data_table",
            "data": {"table_id": table["id"], "operation": "find", "filter": {"who": "없는사람"}},
        },
        out("{{n3.row.who}}|{{n3.found}}|{{n4.count}}|{{n5.found}}"),
    )
    app_id = make_app(client, team, g)
    r1 = run(client, team, app_id, {"message": "민지"})
    assert r1["status"] == "succeeded", r1
    assert r1["output"]["text"] == "민지|True|1|False"
    run(client, team, app_id, {"message": "서준"})
    rows = client.get(f"/api/v1/data-tables/{table['id']}/rows", headers=team.h("member")).json()
    assert rows["total"] == 2 and {r["data"]["count"] for r in rows["rows"]} == {1}

    # 다른 워크스페이스의 표는 쓸 수 없다(흐름이 표 id를 알아도)
    other = chain(
        {"id": "n2", "type": "data_table", "data": {"table_id": "다른-표", "operation": "list"}},
        out("x"),
    )
    bad = run(client, team, make_app(client, team, other), {"message": "a"})
    assert bad["status"] == "failed" and "데이터 표를 찾을 수 없어요" in bad["error"]


def test_data_table_node_validation(client: TestClient, team: Team) -> None:
    g = chain(
        {"id": "n2", "type": "data_table", "data": {"table_id": "t", "operation": "get"}},
        {"id": "n3", "type": "data_table", "data": {"table_id": "t", "operation": "delete"}},
        out("x"),
    )
    app_id = make_app(client, team, g)
    res = client.post(f"/api/v1/apps/{app_id}/runs", json={"input": {}}, headers=team.h("builder"))
    assert res.status_code == 422
    fields = {e.get("field") for e in res.json()["detail"]["errors"]}
    assert {"row_key", "filter"} <= fields


def test_run_app_subflow(client: TestClient, team: Team) -> None:
    child = make_app(
        client,
        team,
        chain(
            {
                "id": "n2",
                "type": "set_fields",
                "data": {"fields": [{"key": "upper", "value": "[{{n1.message}}]"}]},
            },
            {"id": "nz", "type": "output", "data": {"template": "자식: {{n2.upper}}"}},
        ),
        save=True,
        name="자식 앱",
    )
    parent = chain(
        {
            "id": "n2",
            "type": "run_app",
            "data": {"app_id": child, "input": {"message": "{{n1.message}}!"}},
        },
        out("부모 <- {{n2.text}}"),
    )
    r = run(client, team, make_app(client, team, parent), {"message": "hi"})
    assert r["status"] == "succeeded", r
    assert r["output"]["text"] == "부모 <- 자식: [hi!]"

    unsaved = make_app(client, team, chain(out("x")), name="저장 안 함")
    p2 = chain({"id": "n2", "type": "run_app", "data": {"app_id": unsaved}}, out("x"))
    r2 = run(client, team, make_app(client, team, p2), {"message": "a"})
    assert r2["status"] == "failed" and "버전 저장" in r2["error"]


def test_disabled_nodes_skip(client: TestClient, team: Team, fake_llm: FakeAdapter) -> None:
    add_llm(client, team)
    # 끈 LLM 블록은 설정이 비어 있어도(필수 칸 없음) 검증을 통과하고, 실행에서 건너뛴다
    g = chain(
        {"id": "n2", "type": "llm", "data": {}, "disabled": True},
        out("{{n1.message}}/{{n2.message}}"),
    )
    r = run(client, team, make_app(client, team, g), {"message": "그대로"})
    assert r["status"] == "succeeded", r
    assert r["output"]["text"] == "그대로/그대로"
    step = next(s for s in r["steps"] if s["node_id"] == "n2")
    assert step["status"] == "skipped"
    assert not [c for c in fake_llm.calls if c.get("kind") == "complete"]

    # 끈 갈림길은 첫 번째 출구로 간다
    cond = {
        "version": 1,
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "message"}]}},
            {
                "id": "n2",
                "type": "condition",
                "disabled": True,
                "data": {"cases": [{"id": "a", "when": "False"}], "else": "else"},
            },
            {"id": "n3", "type": "output", "data": {"template": "첫 출구"}},
            {"id": "n4", "type": "output", "data": {"template": "그 밖"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3", "sourceHandle": "a"},
            {"id": "e3", "source": "n2", "target": "n4", "sourceHandle": "else"},
        ],
    }
    r2 = run(client, team, make_app(client, team, cond), {"message": "x"})
    assert r2["output"]["text"] == "첫 출구"


def test_disabled_input_rejected_and_notes_kept(client: TestClient, team: Team) -> None:
    g = chain(out("x"))
    g["nodes"][0]["disabled"] = True
    app_id = make_app(client, team, g)
    res = client.post(f"/api/v1/apps/{app_id}/runs", json={"input": {}}, headers=team.h("builder"))
    assert res.status_code == 422
    assert any("입력 블록은 끌 수 없어요" in e["message"] for e in res.json()["detail"]["errors"])

    noted = chain(out("x"))
    noted["notes"] = [
        {"id": "m1", "text": "여기서 고객 분류", "position": {"x": 10, "y": 20}, "color": "blue"}
    ]
    app2 = make_app(client, team, noted)
    got = client.get(f"/api/v1/apps/{app2}", headers=team.h("builder")).json()
    note = got["draft_graph"]["notes"][0]
    assert note["text"] == "여기서 고객 분류" and note["color"] == "blue" and note["width"] == 220
    assert run(client, team, app2, {"message": "a"})["status"] == "succeeded"
