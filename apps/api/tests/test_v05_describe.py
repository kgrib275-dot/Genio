"""실행 결과 문장 설명(기능 정의서 S3): 단계 종류별 문장, 실패 두 줄, 비밀값 비노출."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from api.engine.describe import describe_run, describe_step, failure_lines
from api.tests.conftest import Team

T0 = datetime(2026, 11, 3, 9, 0, 0, tzinfo=UTC)


def step(status: str, output: Any = None, logs: str = "", sec: float = 0.8) -> dict[str, Any]:
    return {
        "status": status,
        "output": output,
        "logs": logs,
        "started_at": T0,
        "finished_at": T0 + timedelta(seconds=sec),
    }


def node(ntype: str, **data: Any) -> dict[str, Any]:
    return {"id": "n2", "type": ntype, "data": data}


def test_sentences_by_type() -> None:
    cls = node("question_classifier", classes=[{"id": "billing", "name": "결제 문의"}])
    assert (
        describe_step(cls, step("succeeded", {"class_id": "billing"}), "분류")
        == "분류 단계에서 '결제 문의'(으)로 판단했어요 (0.8초)."
    )
    cond = node(
        "condition",
        cases=[{"id": "big", "when": "{{n2.amount}} >= 1000000"}],
        **{"else": "small"},
    )
    assert "'amount >= 1000000' 쪽으로" in describe_step(
        cond, step("succeeded", {"matched": "big"}), "금액"
    )
    assert "그 밖의 경우" in describe_step(cond, step("succeeded", {"matched": "small"}), "금액")
    http = node("http", method="get", url="https://api.example.com/v1/x?token=abc")
    s = describe_step(http, step("succeeded", {"status": 200, "body": {}}, sec=0.3), "조회")
    assert s == "조회 단계(외부 호출)가 api.example.com에 GET 요청 → 200 응답 (0.3초)."
    assert "token" not in s
    kb = node("knowledge_search")
    out = {"results": [{"score": 0.82}, {"score": 0.5}, {"score": 0.4}], "context": "…"}
    assert "자료 3개를 찾았어요(최고 0.82점)" in describe_step(kb, step("succeeded", out), "검색")
    llm = node("llm")
    assert '"안녕하세요"' in describe_step(llm, step("succeeded", {"text": "안녕하세요"}), "답변")
    assert "반려됐어요" in describe_step(
        node("approval"), step("succeeded", {"approved": False, "comment": "금액 확인"}), "승인"
    )
    assert "꺼져 있어 건너뛰었어요" in describe_step(llm, step("skipped", {}), "답변")
    assert "승인을 기다리고" in describe_step(node("approval"), step("waiting_approval"), "승인")
    assert describe_step(None, step("succeeded", {}), "무언가").startswith("무언가 단계를 마쳤어요")


def test_connector_sentence_never_shows_secrets() -> None:
    conn = node(
        "connector",
        connector="slack",
        action="send_message",
        credential_id="cred-1",
        params={"channel": "#billing", "token": "xoxb-secret-9999", "text": "{{n1.message}}"},
    )
    s = describe_step(conn, step("succeeded", {"ok": True}), "알림")
    assert s == "알림 단계(연결)가 slack(send_message) #billing(으)로 보냈어요 (0.8초)."
    assert "xoxb" not in s and "cred-1" not in s


def test_failure_two_lines() -> None:
    logs = "시작\n[http] 사내망·내부 IP 주소는 호출할 수 없어요. 외부 공개 주소를 써 주세요."
    problem, fix = failure_lines({"logs": logs})
    assert problem == "사내망·내부 IP 주소는 호출할 수 없어요."
    assert fix == "외부 공개 주소를 써 주세요."
    s = describe_step(node("http"), step("failed", logs=logs), "조회")
    assert s.count("\n") == 1 and s.startswith("조회 단계에서 문제가 생겼어요")
    p2, f2 = failure_lines({"logs": "예상하지 못한 오류: KeyError"})
    assert "예상하지 못한" in p2 and "빌더에게" in f2


def test_story_end_lines() -> None:
    steps = [{"summary": "a"}, {"summary": "b"}]
    assert describe_run({"status": "succeeded"}, steps) == ["a", "b", "모든 단계를 마쳤어요."]
    assert describe_run({"status": "failed"}, steps)[-1].startswith("실행이 실패했어요")


def test_run_detail_has_story(client: TestClient, team: Team) -> None:
    app_id = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "설명"}, headers=team.h("builder")
    ).json()["id"]
    res = client.post(
        f"/api/v1/apps/{app_id}/runs",
        json={"input": {"message": "안녕"}},
        headers=team.h("builder"),
    )
    detail = client.get(f"/api/v1/runs/{res.json()['id']}", headers=team.h("operator")).json()
    assert detail["status"] == "succeeded"
    assert all(s["summary"] for s in detail["steps"])
    assert detail["story"][-1] == "모든 단계를 마쳤어요."
    assert any("결과를 냈어요" in line for line in detail["story"])
