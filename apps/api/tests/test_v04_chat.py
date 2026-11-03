"""v0.4 챗 경험: 답 조각 중계, 지난 대화 불러오기, 위젯 모양, 대화로 시험하기(작업본)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.services import chat as chat_svc
from api.tests.conftest import Team
from api.tests.test_v02_features import chat, deploy, faq_app, parse_sse


class FakeDeltas:
    """첫 번째 확인 때 미리 정한 조각을 돌려주는 가짜 구독."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.closed = False

    def poll(self, timeout: float) -> list[dict[str, Any]]:
        out, self.items = self.items, []
        return out

    def close(self) -> None:
        self.closed = True


def _fake(monkeypatch: pytest.MonkeyPatch, items: list[dict[str, Any]]) -> list[FakeDeltas]:
    made: list[FakeDeltas] = []

    def open_source(run_id: str) -> FakeDeltas:
        f = FakeDeltas([{"type": "delta", **i} for i in items])
        made.append(f)
        return f

    monkeypatch.setattr(chat_svc, "open_delta_source", open_source)
    return made


def test_delta_relay(client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch) -> None:
    app_id = faq_app(client, team)
    token = deploy(client, team, app_id)
    made = _fake(
        monkeypatch,
        [
            {"node_id": "n2", "text": "안"},
            {"node_id": "n2", "text": "녕"},
            {"node_id": "n4", "text": "다른 단계"},
        ],
    )
    ev = chat(client, token, "안녕")
    names = [n for n, _ in ev]
    assert names[:2] == ["session", "status"]
    deltas = [(n, d) for n, d in ev if n in ("delta", "delta_reset")]
    assert deltas == [
        ("delta", {"text": "안", "node_id": "n2"}),
        ("delta", {"text": "녕", "node_id": "n2"}),
        ("delta_reset", {}),
        ("delta", {"text": "다른 단계", "node_id": "n4"}),
    ]
    # 조각 다음에 최종 답이 오고, 구독은 닫힌다
    assert names.index("answer") > names.index("delta")
    assert next(d for n, d in ev if n == "answer")["text"] == "메아리: 안녕"
    assert made and made[0].closed


def test_no_deltas_when_output_moderation(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = faq_app(client, team)
    client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={"moderation": {"enabled": True, "keywords": ["금지"], "check_output": True}},
        headers=team.h("builder"),
    )
    token = deploy(client, team, app_id)
    made = _fake(monkeypatch, [{"node_id": "n2", "text": "검열 전 글"}])
    ev = chat(client, token, "안녕")
    assert not [n for n, _ in ev if n.startswith("delta")]
    assert not made  # 구독 자체를 하지 않는다


def test_session_messages(client: TestClient, team: Team) -> None:
    app_id = faq_app(client, team)
    token = deploy(client, team, app_id)
    ev = chat(client, token, "첫 질문")
    sid = next(d for n, d in ev if n == "session")["session_id"]
    chat(client, token, "두 번째", session_id=sid)
    msgs = client.get(f"/api/v1/public/apps/{token}/sessions/{sid}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[1]["content"] == "메아리: 첫 질문"
    assert {"id", "created_at", "feedback", "citations"} <= set(msgs[1])
    missing = client.get(f"/api/v1/public/apps/{token}/sessions/없는세션/messages")
    assert missing.status_code == 404 and missing.json()["detail"]["hint"]
    # 다른 배포 링크로는 이 세션을 볼 수 없다
    other = deploy(client, team, app_id)
    assert client.get(f"/api/v1/public/apps/{other}/sessions/{sid}/messages").status_code == 404


def test_appearance(client: TestClient, team: Team) -> None:
    app_id = faq_app(client, team)
    res = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={"channel": "web_widget", "access": "public"},
        headers=team.h("builder"),
    ).json()
    dep_id, token = res["id"], res["public_token"]
    assert res["appearance"]["primary_color"] == "#4f46e5"
    assert client.get(f"/api/v1/public/apps/{token}").json()["appearance"]["position"] == "right"

    look = {
        "primary_color": "#0EA5E9",
        "position": "left",
        "launcher_text": "도움말",
        "greeting": "안녕하세요! </script><b>",
        "open_on_load": True,
        "width": 420,
        "height": 640,
        "title": "상담 봇",
    }
    for role, code in [
        ("owner", 200),
        ("admin", 200),
        ("builder", 200),
        ("operator", 403),
        ("member", 403),
    ]:
        r = client.patch(
            f"/api/v1/deployments/{dep_id}", json={"appearance": look}, headers=team.h(role)
        )
        assert r.status_code == code, (role, r.text)
    pub = client.get(f"/api/v1/public/apps/{token}").json()["appearance"]
    assert pub["position"] == "left" and pub["title"] == "상담 봇"

    for bad in ({"primary_color": "red"}, {"width": 5000}, {"position": "top"}, {"x": 1}):
        r = client.patch(
            f"/api/v1/deployments/{dep_id}",
            json={"appearance": bad},
            headers=team.h("builder"),
        )
        assert r.status_code == 422, bad

    js = client.get(f"/api/v1/public/apps/{token}/widget.js").text
    assert "#0EA5E9" in js and '"position": "left"' in js and "__CFG__" not in js
    assert "</script>" not in js  # 인사말 안의 태그로 스크립트를 빠져나가지 못한다
    assert "\\u003c/script\\u003e" in js


def test_preview_chat(client: TestClient, team: Team) -> None:
    app_id = faq_app(client, team)
    for role, code in [
        ("owner", 200),
        ("admin", 200),
        ("builder", 200),
        ("operator", 403),
        ("member", 403),
    ]:
        r = client.post(
            f"/api/v1/apps/{app_id}/preview/chat", json={"message": "hi"}, headers=team.h(role)
        )
        assert r.status_code == code, (role, r.text)

    # 작업본만 바꾸고(버전 저장 없이) 대화해 본다
    draft = client.get(f"/api/v1/apps/{app_id}", headers=team.h("builder")).json()["draft_graph"]
    draft["nodes"][-1]["data"]["template"] = "작업본: {{n1.message}}"
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": draft}, headers=team.h("builder"))
    res = client.post(
        f"/api/v1/apps/{app_id}/preview/chat", json={"message": "안녕"}, headers=team.h("builder")
    )
    ev = parse_sse(res.text)
    sid = next(d for n, d in ev if n == "session")["session_id"]
    assert sid.startswith("preview:")
    assert next(d for n, d in ev if n == "answer")["text"] == "작업본: 안녕"
    # 이어서 묻기(같은 세션)
    ev2 = parse_sse(
        client.post(
            f"/api/v1/apps/{app_id}/preview/chat",
            json={"message": "또", "session_id": sid},
            headers=team.h("builder"),
        ).text
    )
    assert next(d for n, d in ev2 if n == "session")["session_id"] == sid

    # 로그·통계에는 들어가지 않는다
    assert (
        client.get(f"/api/v1/apps/{app_id}/conversations", headers=team.h("builder")).json() == []
    )
    totals = client.get(f"/api/v1/apps/{app_id}/stats", headers=team.h("builder")).json()["totals"]
    assert totals["runs"] == 0 and totals["conversations"] == 0 and totals["messages"] == 0

    # 고칠 부분이 있는 작업본은 두 줄 오류
    draft["nodes"] = [n for n in draft["nodes"] if n["type"] != "output"]
    draft["edges"] = []
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": draft}, headers=team.h("builder"))
    bad = client.post(
        f"/api/v1/apps/{app_id}/preview/chat", json={"message": "x"}, headers=team.h("builder")
    )
    assert bad.status_code == 422 and bad.json()["detail"]["hint"]
