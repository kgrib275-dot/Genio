"""연결 관계 지도."""

from typing import Any

from fastapi.testclient import TestClient

from api.services import dependencies as dep
from api.tests.conftest import Team
from api.tests.test_builder import new_session


def test_graph_refs_scans_nested_ids_and_skips_templates() -> None:
    graph = {
        "nodes": [
            {"id": "n1", "type": "knowledge_search", "data": {"kb_id": "kb-1"}},
            {
                "id": "n2",
                "type": "agent",
                "data": {
                    "skill_ids": ["sk-1", " "],
                    "tools": [
                        {"type": "connector", "credential_id": "cr-1"},
                        {"type": "app", "app_id": "ap-1"},
                        {"type": "knowledge", "kb_id": "{{n1.kb}}"},
                    ],
                },
            },
            {"id": "n3", "type": "data_table", "data": {"table_id": "tb-1"}},
        ]
    }
    assert dep.graph_refs(graph) == {
        ("kb", "kb-1"),
        ("skill", "sk-1"),
        ("credential", "cr-1"),
        ("app", "ap-1"),
        ("table", "tb-1"),
    }
    assert dep.graph_refs(None) == set()


def _put(client: TestClient, team: Team, app_id: str, nodes: list[dict[str, Any]]) -> None:
    g = {
        "version": 1,
        "nodes": [
            {
                "id": "n1",
                "type": "input",
                "data": {"fields": [{"key": "message", "type": "text", "required": True}]},
            },
            *nodes,
            {"id": "n9", "type": "output", "data": {"template": "x"}},
        ],
        "edges": [],
    }
    assert (
        client.put(
            f"/api/v1/apps/{app_id}/draft", json={"graph": g}, headers=team.h("builder")
        ).status_code
        == 200
    )


def test_map_shows_usage_unused_and_missing(client: TestClient, team: Team) -> None:
    ws = team.ws
    h = team.h("builder")
    kb_used = client.post(
        f"/api/v1/workspaces/{ws}/knowledge-bases", json={"name": "규정"}, headers=h
    ).json()["id"]
    client.post(
        f"/api/v1/workspaces/{ws}/knowledge-bases", json={"name": "안 쓰는 지식"}, headers=h
    )
    app_a, _ = new_session(client, team, "A 상담봇")
    app_b, _ = new_session(client, team, "B 요약")
    _put(
        client,
        team,
        app_a,
        [
            {"id": "n2", "type": "knowledge_search", "data": {"kb_id": kb_used, "query": "q"}},
            {"id": "n3", "type": "run_app", "data": {"app_id": app_b}},
            {"id": "n4", "type": "knowledge_search", "data": {"kb_id": "gone-kb", "query": "q"}},
        ],
    )
    out = client.get(f"/api/v1/workspaces/{ws}/dependencies", headers=h).json()
    by = {(r["kind"], r["name"]): r for r in out["resources"]}
    assert [u["app_name"] for u in by[("kb", "규정")]["used_by"]] == ["A 상담봇"]
    assert by[("kb", "안 쓰는 지식")]["unused"] is True and by[("kb", "규정")]["unused"] is False
    assert [u["app_name"] for u in by[("app", "B 요약")]["used_by"]] == ["A 상담봇"]
    uses = {a["name"]: a["uses"] for a in out["apps"]}["A 상담봇"]
    assert any(u["missing"] and u["id"] == "gone-kb" for u in uses)
    assert out["missing_count"] == 1 and out["unused_count"] >= 1
    # 내가 쓰는 자원이 없는 앱
    assert {a["name"]: a["uses"] for a in out["apps"]}["B 요약"] == []


def test_permissions(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/dependencies"
    assert client.get(url, headers=team.h("member")).status_code == 403
    assert client.get(url, headers=team.h("operator")).status_code == 403
    assert client.get(url).status_code == 401
