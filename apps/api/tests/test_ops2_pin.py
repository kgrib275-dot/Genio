"""값 고정(시험 전용): 고정한 결과가 있으면 시험 실행은 그 단계를 건너뛰고, 실서비스 실행은 무시한다."""

from typing import Any

from fastapi.testclient import TestClient

from api.tests.conftest import Team
from api.tests.test_builder import new_session
from api.tests.test_v05_builder import BROKEN_CODE, code_graph


def _graph(pinned: bool) -> dict[str, Any]:
    g = code_graph(BROKEN_CODE)  # 이 단계를 실제로 돌리면 0으로 나누어 실패한다
    if pinned:
        for n in g["nodes"]:
            if n["id"] == "n3":
                n["data"]["_pinned"] = {"output": {"n": 99}}
    return g


def _steps(client: TestClient, team: Team, run_id: str) -> dict[str, Any]:
    d = client.get(f"/api/v1/runs/{run_id}", headers=team.h("builder")).json()
    return {
        "status": d["status"],
        "steps": {s["node_id"]: s for s in d["steps"]},
        "out": d["output"],
    }


def test_pinned_step_is_skipped_in_test_run(client: TestClient, team: Team) -> None:
    app_id, _ = new_session(client, team, "고정")
    res = client.put(
        f"/api/v1/apps/{app_id}/draft", json={"graph": _graph(True)}, headers=team.h("builder")
    )
    assert res.status_code == 200, res.text
    run = client.post(
        f"/api/v1/apps/{app_id}/runs",
        json={"input": {"message": "안녕"}},
        headers=team.h("builder"),
    ).json()
    got = _steps(client, team, run["id"])
    assert got["status"] == "succeeded"
    assert got["steps"]["n3"]["output"] == {"n": 99}
    assert "고정한 값을 썼어요" in got["steps"]["n3"]["logs"]
    assert "99자" in str(got["out"])


def test_pin_is_ignored_for_real_runs(client: TestClient, team: Team) -> None:
    from api.engine.executor import pinned_output
    from api.schemas.graph import GraphNode

    node = GraphNode.model_validate(
        {
            "id": "n3",
            "type": "code",
            "position": {"x": 0, "y": 0},
            "data": {"_pinned": {"output": {"n": 1}}},
        }
    )
    assert pinned_output(node, "test") == {"output": {"n": 1}}
    assert pinned_output(node, "preview") == {"output": {"n": 1}}
    for trigger in ("api", "webhook", "chat", "batch", "rerun", "subflow", "manual", "form"):
        assert pinned_output(node, trigger) is None
    out_node = GraphNode.model_validate(
        {
            "id": "n2",
            "type": "output",
            "position": {"x": 0, "y": 0},
            "data": {"_pinned": {"output": {}}},
        }
    )
    assert pinned_output(out_node, "test") is None  # 결과 단계는 고정하지 않는다
