"""단계별 제한 시간(_timeout): 넘기면 실패하고 두 줄 오류가 남는다."""

from fastapi.testclient import TestClient

from api.tests.conftest import Team


def test_step_timeout(client: TestClient, team: Team) -> None:
    h = team.h("builder")
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": []}},
            {"id": "w1", "type": "wait", "data": {"seconds": 3, "_timeout": 1}},
            {"id": "n3", "type": "output", "data": {"template": "끝"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "w1"},
            {"id": "e2", "source": "w1", "target": "n3"},
        ],
    }
    app = client.post(
        f"/api/v1/workspaces/{team.ws}/apps",
        json={"name": "제한 시간", "type": "workflow"},
        headers=h,
    ).json()
    assert (
        client.put(f"/api/v1/apps/{app['id']}/draft", json={"graph": graph}, headers=h).status_code
        == 200
    )
    run = client.post(f"/api/v1/apps/{app['id']}/runs", json={"input": {}}, headers=h).json()
    d = client.get(f"/api/v1/runs/{run['id']}", headers=h).json()
    assert d["status"] == "failed"
    step = next(s for s in d["steps"] if s["node_id"] == "w1")
    assert step["status"] == "failed"
