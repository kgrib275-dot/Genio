"""v0.5 빌더(기능 정의서 S1): 설명 모드·오류 해결 녹화 시나리오, get_run, 측정 지표, 저장한 테스트 입력."""

from typing import Any

from fastapi.testclient import TestClient

from api.db import SessionLocal
from api.models import BuilderSession
from api.tests.conftest import Team, add_llm
from api.tests.fakes import FakeAdapter, last_tool_result, text_turn, tool_turn
from api.tests.test_builder import new_session, send, turn_record

BROKEN_CODE = "result = {'n': 1 / 0}"
FIXED_CODE = "result = {'n': len(inputs['msg'])}"


def code_graph(code: str) -> dict[str, Any]:
    return {
        "version": 1,
        "nodes": [
            {
                "id": "n1",
                "type": "input",
                "data": {
                    "label": "문의 입력",
                    "fields": [{"key": "message", "type": "text", "required": True}],
                },
            },
            {
                "id": "n3",
                "type": "code",
                "data": {"label": "글자 수", "inputs": {"msg": "{{n1.message}}"}, "code": code},
            },
            {"id": "n2", "type": "output", "data": {"label": "결과", "template": "{{n3.n}}자"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n3"},
            {"id": "e2", "source": "n3", "target": "n2"},
        ],
    }


def test_explain_mode_changes_nothing(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    app_id, sid = new_session(client, team, "설명")
    client.put(
        f"/api/v1/apps/{app_id}/draft",
        json={"graph": code_graph(FIXED_CODE), "source": "import"},
        headers=team.h("builder"),
    )
    before = client.get(f"/api/v1/apps/{app_id}", headers=team.h("builder")).json()["draft_graph"]

    def explain(messages: list[Any]) -> Any:
        g = last_tool_result(messages, "get_graph")
        assert "글자 수" in g["summary"]
        return text_turn("1. 문의 입력: 손님이 쓴 문의를 받아요.\n2. 글자 수: 글자 수를 세요.")(
            messages
        )

    fake_llm.script = [tool_turn("흐름을 읽어 볼게요.", ("get_graph", {})), explain]
    rec = turn_record(send(client, team, sid, "이거 뭐 하는 거야?"))
    assert rec["tools"] == [("get_graph", True)] and rec["ops"] == []
    after = client.get(f"/api/v1/apps/{app_id}", headers=team.h("builder")).json()["draft_graph"]
    assert after == before


def test_fix_failed_run_scenario(client: TestClient, team: Team, fake_llm: FakeAdapter) -> None:
    """실패한 실행 → '빌더에게 고쳐 달라고 하기' → get_run → 원인·제안 → 동의 → 패치 → 검증·시험."""
    add_llm(client, team)
    app_id, sid = new_session(client, team, "고치기")
    client.put(
        f"/api/v1/apps/{app_id}/draft",
        json={"graph": code_graph(BROKEN_CODE)},
        headers=team.h("builder"),
    )
    run = client.post(
        f"/api/v1/apps/{app_id}/runs",
        json={"input": {"message": "환불해 주세요"}},
        headers=team.h("builder"),
    ).json()
    detail = client.get(f"/api/v1/runs/{run['id']}", headers=team.h("builder")).json()
    assert detail["status"] == "failed"

    # 1) 원인 읽기 → 고칠지 묻기
    def diagnose(messages: list[Any]) -> Any:
        r = last_tool_result(messages, "get_run")
        assert r["status"] == "failed" and r["run_id"] == run["id"]
        failed = [s for s in r["steps"] if s["status"] == "failed"]
        assert failed and failed[0]["label"] == "글자 수"
        assert "문제가 생겼어요" in failed[0]["summary"]
        assert "story" in r and r["story"][-1].startswith("실행이 실패했어요")
        return tool_turn(
            "'글자 수' 단계에서 0으로 나눠 멈췄어요.\n글자 수를 세는 식으로 바꾸면 돼요.",
            ("ask_user", {"question": "이렇게 고칠까요?", "options": ["고쳐 줘", "그대로 둘게"]}),
        )(messages)

    fake_llm.script = [
        tool_turn("실행 결과를 확인할게요.", ("get_run", {"run_id": run["id"]})),
        diagnose,
    ]
    t1 = turn_record(
        send(client, team, sid, f"이 실행이 왜 실패했는지 보고 고쳐 줘 (실행 {run['id']})")
    )
    assert t1["tools"] == [("get_run", True), ("ask_user", True)] and t1["ops"] == []
    assert t1["ask_user"]["options"] == ["고쳐 줘", "그대로 둘게"]

    # 2) 동의 → 고치고 검증·같은 입력으로 시험
    fake_llm.script = [
        tool_turn(
            "글자 수를 세도록 고칠게요.",
            ("update_node", {"id": "n3", "data": {"code": FIXED_CODE}}),
            ("validate", {}),
        ),
        tool_turn(
            "같은 입력으로 시험해 볼게요.", ("run_test", {"input": {"message": "환불해 주세요"}})
        ),
        text_turn("이제 잘 돼요. '환불해 주세요'를 넣으니 7자라고 나왔어요."),
    ]
    t2 = turn_record(send(client, team, sid, "고쳐 줘"))
    assert t2["tools"] == [("update_node", True), ("validate", True), ("run_test", True)]
    assert t2["test_status"] == "succeeded"

    # 지표: 사용자 차례 2번, 검증 통과 시각과 걸린 시간, 빌더 변경 1건
    with SessionLocal() as db:
        sess = db.get(BuilderSession, sid)
        assert sess is not None
        m = sess.metrics or {}
    assert m["user_turns"] == 2 and m.get("edit_turns", 0) == 0
    assert m["first_valid_at"] and m["seconds_to_valid"] >= 0
    assert m["builder_ops"] >= 1


def test_get_run_without_runs_and_foreign_run(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    other_app, _ = new_session(client, team, "다른 앱")
    other_run = client.post(
        f"/api/v1/apps/{other_app}/runs",
        json={"input": {"message": "x"}},
        headers=team.h("builder"),
    ).json()
    _, sid = new_session(client, team, "빈 앱")
    fake_llm.script = [
        tool_turn("", ("get_run", {}), ("get_run", {"run_id": other_run["id"]})),
        text_turn("아직 실행한 적이 없어요."),
    ]
    events = send(client, team, sid, "방금 결과 설명해 줘")
    results = [d for n, d in events if n == "tool_result"]
    # 실행이 없으면 성공(found=false), 다른 앱의 실행은 읽을 수 없음
    assert [r["ok"] for r in results] == [True, False]


def test_metrics_edit_turns_and_canvas(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    app_id, sid = new_session(client, team, "지표")
    fake_llm.script = [tool_turn("", ("validate", {})), text_turn("검증을 통과했어요.")]
    send(client, team, sid, "검사해 줘")
    fake_llm.script = [text_turn("네.")]
    send(client, team, sid, "고맙습니다")
    graph = client.get(f"/api/v1/apps/{app_id}", headers=team.h("builder")).json()["draft_graph"]
    # 화면 캔버스 자동 저장(source 생략 = canvas)만 센다
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": graph}, headers=team.h("builder"))
    client.put(
        f"/api/v1/apps/{app_id}/draft",
        json={"graph": graph, "source": "import"},
        headers=team.h("builder"),
    )
    with SessionLocal() as db:
        s = db.get(BuilderSession, sid)
        assert s is not None
        m = dict(s.metrics or {})
    assert m["user_turns"] == 2 and m["edit_turns"] == 1 and m["canvas_edits"] == 1

    data = client.get(f"/api/v1/workspaces/{team.ws}/builder/metrics", headers=team.h("admin"))
    assert data.status_code == 200
    body = data.json()
    assert body["sessions"] >= 1 and body["avg_user_turns"] is not None
    row = next(a for a in body["apps"] if a["app_id"] == app_id)
    assert row["canvas_edits"] == 1 and row["manual_ratio"] == 1.0
    for role, code in [
        ("owner", 200),
        ("admin", 200),
        ("builder", 403),
        ("operator", 403),
        ("member", 403),
    ]:
        r = client.get(f"/api/v1/workspaces/{team.ws}/builder/metrics", headers=team.h(role))
        assert r.status_code == code, role


def test_test_inputs(client: TestClient, team: Team) -> None:
    app_id = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "샘플"}, headers=team.h("builder")
    ).json()["id"]
    url = f"/api/v1/apps/{app_id}/test-inputs"
    assert client.get(url, headers=team.h("builder")).json() == []
    items = [
        {"name": "환불 문의", "input": {"message": "환불해 주세요"}},
        {"name": "배송 문의", "input": {"message": "언제 와요?"}},
    ]
    res = client.put(url, json={"items": items}, headers=team.h("builder"))
    assert res.status_code == 200 and res.json() == items
    assert client.get(url, headers=team.h("admin")).json() == items
    dup = client.put(url, json={"items": [items[0], items[0]]}, headers=team.h("builder"))
    assert dup.status_code == 422 and "같은 이름" in dup.json()["detail"]["message"]
    big = client.put(
        url,
        json={"items": [{"name": "긴 글", "input": {"message": "가" * 30000}}]},
        headers=team.h("builder"),
    )
    assert big.status_code == 422
    too_many = client.put(
        url,
        json={"items": [{"name": f"t{i}", "input": {}} for i in range(21)]},
        headers=team.h("builder"),
    )
    assert too_many.status_code == 422
    for role in ("operator", "member"):
        assert client.get(url, headers=team.h(role)).status_code == 403
        assert client.put(url, json={"items": []}, headers=team.h(role)).status_code == 403
    assert client.put(url, json={"items": []}, headers=team.h("owner")).status_code == 200
