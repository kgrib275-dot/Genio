"""v0.5 챗 ↔ 흐름: 사람을 기다렸다 끝난 결과가 대화로 돌아오기, 상담원 전환, 배포 대상 사용자,
챗 앱에도 외부에서 받기(웹훅)."""

from typing import Any

from fastapi.testclient import TestClient

from api.db import SessionLocal
from api.models import HumanTask
from api.tests.conftest import Team
from api.tests.test_v02_features import chat
from api.tests.test_v05_engine import make_app

LEAVE_GRAPH: dict[str, Any] = {
    "nodes": [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "message"}]}},
        {
            "id": "ap",
            "type": "approval",
            "data": {"message": "휴가 신청: {{n1.message}}", "branch": True},
        },
        {"id": "ok", "type": "output", "data": {"template": "휴가가 승인됐어요. ({{ap.comment}})"}},
        {"id": "no", "type": "output", "data": {"template": "휴가가 반려됐어요."}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "ap"},
        {"id": "e2", "source": "ap", "target": "ok", "sourceHandle": "approved"},
        {"id": "e3", "source": "ap", "target": "no", "sourceHandle": "rejected"},
    ],
}

ECHO_GRAPH: dict[str, Any] = {
    "nodes": [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "message"}]}},
        {"id": "n2", "type": "output", "data": {"template": "메아리: {{n1.message}}"}},
    ],
    "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
}


def chat_app(client: TestClient, team: Team, graph: dict[str, Any], **dep: Any) -> tuple[str, str]:
    app_id: str = client.post(
        f"/api/v1/workspaces/{team.ws}/apps",
        json={"name": "휴가 챗봇", "type": "chat"},
        headers=team.h("builder"),
    ).json()["id"]
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": graph}, headers=team.h("builder"))
    client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=team.h("builder"))
    res = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={"channel": "share_link", "access": "public", **dep},
        headers=team.h("builder"),
    )
    assert res.status_code == 201, res.text
    return app_id, str(res.json()["public_token"])


def test_chat_waits_for_approval_then_answers_in_conversation(
    client: TestClient, team: Team
) -> None:
    _, token = chat_app(client, team, LEAVE_GRAPH)
    ev = chat(client, token, "휴가 신청해 줘 금요일")
    names = [n for n, _ in ev]
    assert "pending" in names and names[-1] == "done"
    answer = next(d for n, d in ev if n == "answer")
    assert "승인을 기다리고" in answer["text"]
    sid = next(d for n, d in ev if n == "session")["session_id"]
    state = client.get(f"/api/v1/public/apps/{token}/sessions/{sid}/state").json()
    assert state["status"] == "bot" and state["waiting"] is True
    with SessionLocal() as db:
        task_token = db.query(HumanTask).one().token
    client.post(
        f"/api/v1/public/tasks/{task_token}", json={"approved": True, "comment": "푹 쉬세요"}
    )
    msgs = client.get(f"/api/v1/public/apps/{token}/sessions/{sid}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "assistant"]
    assert msgs[-1]["content"] == "휴가가 승인됐어요. (푹 쉬세요)"
    assert (
        client.get(f"/api/v1/public/apps/{token}/sessions/{sid}/state").json()["waiting"] is False
    )


def test_handoff_keyword_agent_reply_and_close(client: TestClient, team: Team) -> None:
    app_id, token = chat_app(client, team, ECHO_GRAPH)
    # 꺼져 있으면 버튼 요청은 거절, 키워드도 그냥 봇이 답함
    ev = chat(client, token, "상담원 연결해 주세요")
    sid = next(d for n, d in ev if n == "session")["session_id"]
    assert any(n == "answer" for n, _ in ev)
    assert client.post(f"/api/v1/public/apps/{token}/sessions/{sid}/handoff").status_code == 409
    client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={"handoff": {"enabled": True, "keywords": ["상담원"]}},
        headers=team.h("builder"),
    )
    ev = chat(client, token, "상담원 연결해 주세요", session_id=sid)
    assert [n for n, _ in ev] == ["session", "handoff", "done"]
    # 상담 중에는 봇이 답하지 않고 받은 말만 저장
    ev = chat(client, token, "주문번호 1234예요", session_id=sid)
    assert [n for n, _ in ev] == ["session", "handoff", "done"]
    assert (
        client.get(f"/api/v1/public/apps/{token}/sessions/{sid}/state").json()["status"]
        == "handoff"
    )
    convs = client.get(
        f"/api/v1/apps/{app_id}/conversations?status=handoff", headers=team.h("operator")
    ).json()
    assert len(convs) == 1 and convs[0]["status"] == "handoff"
    cid = convs[0]["id"]
    assert (
        client.post(
            f"/api/v1/conversations/{cid}/reply",
            json={"content": "확인해 볼게요"},
            headers=team.h("member"),
        ).status_code
        == 403
    )
    r = client.post(
        f"/api/v1/conversations/{cid}/reply",
        json={"content": "확인해 볼게요"},
        headers=team.h("operator"),
    )
    assert r.status_code == 201 and r.json()["role"] == "agent"
    msgs = client.get(f"/api/v1/public/apps/{token}/sessions/{sid}/messages").json()
    assert msgs[-1]["role"] == "agent" and msgs[-1]["content"] == "확인해 볼게요"
    assert any(m["content"] == "주문번호 1234예요" for m in msgs)
    closed = client.post(f"/api/v1/conversations/{cid}/close", headers=team.h("operator")).json()
    assert closed["status"] == "closed"
    ev = chat(client, token, "고마워요", session_id=sid)
    assert next(d for n, d in ev if n == "answer")["text"] == "메아리: 고마워요"
    assert (
        client.post(
            f"/api/v1/conversations/{cid}/reply", json={"content": "x"}, headers=team.h("operator")
        ).status_code
        == 409
    )


def test_handoff_button(client: TestClient, team: Team) -> None:
    app_id, token = chat_app(client, team, ECHO_GRAPH)
    client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={"handoff": {"enabled": True}},
        headers=team.h("builder"),
    )
    ev = chat(client, token, "안녕")
    sid = next(d for n, d in ev if n == "session")["session_id"]
    r = client.post(f"/api/v1/public/apps/{token}/sessions/{sid}/handoff")
    assert r.status_code == 200 and r.json()["status"] == "handoff"
    assert client.post(f"/api/v1/public/apps/{token}/sessions/없는세션/handoff").status_code == 404


def test_deployment_allowed_users(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, ECHO_GRAPH, name="사람 지정")
    client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=team.h("builder"))
    bad = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={"channel": "share_link", "access": "roles", "allowed_users": ["남의-id"]},
        headers=team.h("builder"),
    )
    assert bad.status_code == 422
    res = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={"channel": "share_link", "access": "roles", "allowed_users": [team.users["member"]]},
        headers=team.h("builder"),
    )
    assert res.status_code == 201, res.text
    dep = res.json()
    assert dep["allowed_users"] == [team.users["member"]] and dep["allowed_roles"] == []
    token = dep["public_token"]
    ok = client.post(
        f"/api/v1/public/apps/{token}/chat", json={"message": "hi"}, headers=team.h("member")
    )
    assert ok.status_code == 200
    no = client.post(
        f"/api/v1/public/apps/{token}/chat", json={"message": "hi"}, headers=team.h("operator")
    )
    assert no.status_code == 403 and "지정되지 않았어요" in no.json()["detail"]["message"]
    # 역할 추가로 바꾸기
    p = client.patch(
        f"/api/v1/deployments/{dep['id']}",
        json={"allowed_roles": ["operator"]},
        headers=team.h("builder"),
    )
    assert p.status_code == 200 and p.json()["allowed_roles"] == ["operator"]
    assert (
        client.post(
            f"/api/v1/public/apps/{token}/chat", json={"message": "hi"}, headers=team.h("operator")
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/deployments/{dep['id']}",
            json={"allowed_users": []},
            headers=team.h("operator"),
        ).status_code
        == 403
    )


def test_chat_app_has_webhook(client: TestClient, team: Team) -> None:
    app_id, _ = chat_app(client, team, ECHO_GRAPH)
    t = client.post(
        f"/api/v1/apps/{app_id}/triggers",
        json={"kind": "webhook", "config": {"mode": "sync"}},
        headers=team.h("builder"),
    )
    assert t.status_code == 201, t.text
    path = "/" + t.json()["url"].split("/api/v1/", 1)[1]
    r = client.post(f"/api/v1{path}", json={"message": "외부에서"})
    assert r.status_code == 200 and r.json()["output"]["text"] == "메아리: 외부에서"
