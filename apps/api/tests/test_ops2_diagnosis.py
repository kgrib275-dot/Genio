"""실패한 실행의 자동 진단 제안."""

from typing import Any

from fastapi.testclient import TestClient

from api.engine.diagnosis import diagnose
from api.tests.conftest import Team
from api.tests.test_builder import new_session
from api.tests.test_v05_builder import BROKEN_CODE, FIXED_CODE, code_graph


def test_rules_pick_by_error_text_and_node_type() -> None:
    nodes = {"n1": {"id": "n1", "type": "http", "data": {"label": "주문 조회"}}}

    def run(logs: str) -> dict[str, Any]:
        steps = [{"node_id": "n1", "status": "failed", "logs": logs}]
        out = diagnose({"status": "failed", "error": None}, steps, nodes)
        assert out is not None
        return out

    ids = [s["id"] for s in run("서버가 401을 돌려줬어요.")["suggestions"]]
    assert ids[0] == "auth" and ids[-1] == "generic" and "continue" in ids
    assert run("시간 초과로 멈췄어요")["suggestions"][0]["id"] == "timeout"
    top = run("알 수 없는 문제")["suggestions"]
    assert [s["id"] for s in top] == [
        "continue",
        "generic",
    ]  # 외부 호출이라 계속 진행 제안이 붙는다
    assert "주문 조회" in top[0]["prompt"]
    # 단계 종류가 안 맞으면 그 규칙은 건너뛴다(코드 단계에 '모델' 제안은 없다)
    code = {"n1": {"id": "n1", "type": "code", "data": {"label": "계산"}}}
    out = diagnose(
        {"status": "failed", "error": None},
        [{"node_id": "n1", "status": "failed", "logs": "토큰이 너무 길어요"}],
        code,
    )
    assert out is not None and [s["id"] for s in out["suggestions"]] == ["generic"]


def test_not_failed_has_no_diagnosis() -> None:
    assert diagnose({"status": "succeeded"}, [], {}) is None


def test_run_detail_includes_diagnosis(client: TestClient, team: Team) -> None:
    app_id, _ = new_session(client, team, "진단")
    for code in (BROKEN_CODE, FIXED_CODE):
        client.put(
            f"/api/v1/apps/{app_id}/draft",
            json={"graph": code_graph(code)},
            headers=team.h("builder"),
        )
        run = client.post(
            f"/api/v1/apps/{app_id}/runs",
            json={"input": {"message": "안녕"}},
            headers=team.h("builder"),
        ).json()
        detail = client.get(f"/api/v1/runs/{run['id']}", headers=team.h("builder")).json()
        if code == BROKEN_CODE:
            d = detail["diagnosis"]
            assert detail["status"] == "failed" and d["node_label"] == "글자 수"
            assert d["suggestions"][-1]["id"] == "generic"
        else:
            assert detail["status"] == "succeeded" and detail["diagnosis"] is None
