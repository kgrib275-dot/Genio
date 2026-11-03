"""v0.5 사람에게 묻기·할 일 맡기기와 작업함(역할별 권한 포함)."""

from typing import Any

from fastapi.testclient import TestClient

from api.db import SessionLocal
from api.models import HumanTask
from api.tests.conftest import Team
from api.tests.test_v05_engine import make_app, start

ASK_GRAPH: dict[str, Any] = {
    "nodes": [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "item"}]}},
        {
            "id": "q1",
            "type": "ask_person",
            "data": {
                "question": "{{n1.item}} 견적 금액을 알려 주세요",
                "fields": [
                    {"key": "price", "label": "금액", "type": "number"},
                    {"key": "memo", "label": "메모", "type": "text", "required": False},
                ],
                "assignee_role": "operator",
            },
        },
        {
            "id": "n3",
            "type": "output",
            "data": {"template": "{{q1.price}}원 ({{q1.completed_by}})"},
        },
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "q1"},
        {"id": "e2", "source": "q1", "target": "n3"},
    ],
}

ASSIGN_GRAPH: dict[str, Any] = {
    "nodes": [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "name"}]}},
        {
            "id": "a1",
            "type": "assign_task",
            "data": {
                "title": "{{n1.name}}님 노트북 준비",
                "assignee_role": "builder",
                "due_hours": 24,
            },
        },
        {"id": "n3", "type": "output", "data": {"template": "완료: {{a1.comment}}"}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "a1"},
        {"id": "e2", "source": "a1", "target": "n3"},
    ],
}


def tasks(client: TestClient, team: Team, role: str, **params: Any) -> list[dict[str, Any]]:
    res = client.get(f"/api/v1/workspaces/{team.ws}/tasks", params=params, headers=team.h(role))
    assert res.status_code == 200, res.text
    out: list[dict[str, Any]] = res.json()
    return out


def test_ask_person_via_inbox(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, ASK_GRAPH)
    v = client.post(f"/api/v1/apps/{app_id}/validate", json={}, headers=team.h("builder")).json()
    assert v["valid"], v["errors"]
    d = start(client, team, app_id, {"item": "노트북"})
    assert d["status"] == "waiting_approval"
    assert d["approval"]["kind"] == "question"
    mine = tasks(client, team, "operator", mine=True)
    assert (
        len(mine) == 1
        and mine[0]["can_act"]
        and mine[0]["title"] == "노트북 견적 금액을 알려 주세요"
    )
    assert client.get(
        f"/api/v1/workspaces/{team.ws}/tasks/count", headers=team.h("operator")
    ).json() == {"open": 1}
    # 담당이 아닌 역할(사용자)은 처리 못 함, 내 것 목록에도 없음
    assert tasks(client, team, "member", mine=True) == []
    tid = mine[0]["id"]
    deny = client.post(
        f"/api/v1/workspaces/{team.ws}/tasks/{tid}/complete",
        json={"values": {"price": 10}},
        headers=team.h("member"),
    )
    assert deny.status_code == 403
    # 필수 칸 빠짐·숫자 아님 → 두 줄 오류
    bad = client.post(
        f"/api/v1/workspaces/{team.ws}/tasks/{tid}/complete",
        json={"values": {"price": "많이"}},
        headers=team.h("operator"),
    )
    assert bad.status_code == 422 and bad.json()["detail"]["hint"]
    ok = client.post(
        f"/api/v1/workspaces/{team.ws}/tasks/{tid}/complete",
        json={"values": {"price": "1200000"}, "comment": "부가세 포함"},
        headers=team.h("operator"),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "done"
    done = client.get(f"/api/v1/runs/{d['id']}", headers=team.h("builder")).json()
    assert done["status"] == "succeeded", done["error"]
    assert done["output"]["text"].startswith("1200000.0원")
    assert tasks(client, team, "operator", mine=True) == []
    assert len(tasks(client, team, "owner", status="done")) == 1


def test_assign_task_via_link_and_cancel(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, ASSIGN_GRAPH)
    d = start(client, team, app_id, {"name": "김신입"})
    with SessionLocal() as db:
        token = db.query(HumanTask).filter(HumanTask.run_id == d["id"]).one().token
    got = client.get(f"/api/v1/public/tasks/{token}").json()
    assert got["kind"] == "assignment" and got["due_at"]
    res = client.post(f"/api/v1/public/tasks/{token}", json={"comment": "준비 끝"})
    assert res.status_code == 200
    done = client.get(f"/api/v1/runs/{d['id']}", headers=team.h("builder")).json()
    assert done["output"]["text"] == "완료: 준비 끝"
    # 취소: 제작자 이상만, 실행은 멈춘다
    d2 = start(client, team, app_id, {"name": "박신입"})
    tid = next(t for t in tasks(client, team, "owner") if t["run_id"] == d2["id"])["id"]
    assert (
        client.post(
            f"/api/v1/workspaces/{team.ws}/tasks/{tid}/cancel", headers=team.h("operator")
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/workspaces/{team.ws}/tasks/{tid}/cancel", headers=team.h("builder")
        ).status_code
        == 200
    )
    stopped = client.get(f"/api/v1/runs/{d2['id']}", headers=team.h("builder")).json()
    assert stopped["status"] == "failed" and "취소" in stopped["error"]


def test_assign_requires_assignee(client: TestClient, team: Team) -> None:
    g = {
        **ASSIGN_GRAPH,
        "nodes": [
            ASSIGN_GRAPH["nodes"][0],
            {"id": "a1", "type": "assign_task", "data": {"title": "x"}},
            ASSIGN_GRAPH["nodes"][2],
        ],
    }
    d = start(client, team, make_app(client, team, g), {"name": "x"})
    assert d["status"] == "failed" and "담당" in d["error"]


def test_tasks_permissions_per_role(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    app_id = make_app(client, team, ASK_GRAPH)
    start(client, team, app_id, {"item": "x"})
    for role in ("owner", "admin", "builder", "operator", "member"):
        assert (
            client.get(f"/api/v1/workspaces/{team.ws}/tasks", headers=team.h(role)).status_code
            == 200
        )
    assert client.get(f"/api/v1/workspaces/{team.ws}/tasks", headers=outsider).status_code in (
        403,
        404,
    )
    assert client.get(f"/api/v1/workspaces/{team.ws}/tasks").status_code == 401
    tid = tasks(client, team, "owner")[0]["id"]
    assert client.get(
        f"/api/v1/workspaces/{team.ws}/tasks/{tid}", headers=outsider
    ).status_code in (403, 404)
