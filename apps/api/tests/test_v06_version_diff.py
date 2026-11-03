"""v0.6 버전 비교: 더한·뺀·바뀐 단계와 선, 작업본 비교, 역할별 권한, 오류 두 줄."""

import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.tests.conftest import ROLES, Team
from api.tests.test_v05_engine import make_app

V1: dict[str, Any] = {
    "nodes": [
        {"id": "n1", "type": "input", "data": {"label": "질문", "fields": [{"key": "m"}]}},
        {"id": "n2", "type": "template", "data": {"label": "다듬기", "template": "A {{n1.m}}"}},
        {"id": "n3", "type": "output", "data": {"label": "결과", "template": "{{n2.output}}"}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ],
}


def _v2() -> dict[str, Any]:
    g = copy.deepcopy(V1)
    g["nodes"][1]["data"]["template"] = "B {{n1.m}}"
    g["nodes"][1]["position"] = {"x": 50, "y": 50}
    g["nodes"].append({"id": "n4", "type": "template", "data": {"label": "요약", "template": "S"}})
    g["edges"].append({"id": "e3", "source": "n1", "target": "n4"})
    g["edges"].append({"id": "e4", "source": "n4", "target": "n3"})
    return g


def _setup(client: TestClient, team: Team) -> str:
    h = team.h("builder")
    app_id = make_app(client, team, V1)
    assert client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=h).status_code == 201
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": _v2()}, headers=h)
    assert client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=h).status_code == 201
    return app_id


def test_diff_between_versions(client: TestClient, team: Team) -> None:
    app_id = _setup(client, team)
    d = client.get(
        f"/api/v1/apps/{app_id}/version-diff",
        params={"from": 1, "to": 2},
        headers=team.h("builder"),
    ).json()
    assert d["from"] == "버전 1" and d["to"] == "버전 2" and not d["same"]
    assert [n["label"] for n in d["nodes_added"]] == ["요약"]
    assert d["nodes_removed"] == []
    changed = d["nodes_changed"][0]
    assert changed["label"] == "다듬기"
    field = changed["fields"][0]
    assert (
        field["name"] == "글 틀"
        and field["before"].startswith("A")
        and field["after"].startswith("B")
    )
    assert sorted(d["edges_added"]) == ["요약 → 결과", "질문 → 요약"]
    assert any("단계 1개 추가" in s for s in d["summary"])


def test_diff_with_draft_and_same(client: TestClient, team: Team) -> None:
    app_id = _setup(client, team)
    d = client.get(
        f"/api/v1/apps/{app_id}/version-diff", params={"from": 2}, headers=team.h("builder")
    ).json()
    assert d["to"] == "작업본" and d["same"] and d["summary"] == ["바뀐 내용이 없어요."]
    back = client.get(
        f"/api/v1/apps/{app_id}/version-diff",
        params={"from": 2, "to": 1},
        headers=team.h("builder"),
    ).json()
    assert [n["label"] for n in back["nodes_removed"]] == ["요약"]


def test_diff_errors_are_two_lines(client: TestClient, team: Team) -> None:
    app_id = _setup(client, team)
    for params, code in (({"from": 9}, 404), ({"from": "abc"}, 422)):
        r = client.get(
            f"/api/v1/apps/{app_id}/version-diff", params=params, headers=team.h("builder")
        )
        assert r.status_code == code
        assert r.json()["detail"]["message"] and r.json()["detail"]["hint"]


@pytest.mark.parametrize("role", ROLES)
def test_diff_permissions(client: TestClient, team: Team, role: str) -> None:
    app_id = _setup(client, team)
    r = client.get(
        f"/api/v1/apps/{app_id}/version-diff", params={"from": 1, "to": 2}, headers=team.h(role)
    )
    # 실행 기록을 볼 수 있는 역할만 허용(사용자 역할은 거부)
    allowed = role in ("owner", "admin", "builder", "operator")
    assert (r.status_code == 200) == allowed, (role, r.status_code)


def test_diff_outsider_denied(client: TestClient, team: Team, outsider: dict[str, str]) -> None:
    app_id = _setup(client, team)
    r = client.get(
        f"/api/v1/apps/{app_id}/version-diff", params={"from": 1, "to": 2}, headers=outsider
    )
    assert r.status_code in (403, 404)
