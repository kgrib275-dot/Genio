"""v0.6 대화 기억 요약: 기억 창 밖으로 밀려난 대화를 요약해 다음 답에 함께 넘긴다."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.db import SessionLocal
from api.models import Conversation
from api.tests.conftest import Team, add_llm
from api.tests.fakes import FakeAdapter
from api.tests.test_v02_features import chat, deploy

GRAPH = {
    "nodes": [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "message"}]}},
        {"id": "n2", "type": "output", "data": {"template": "기록<{{input.history}}>"}},
    ],
    "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
}


def _chat_app(client: TestClient, team: Team, summary: bool) -> str:
    h = team.h("builder")
    app_id: str = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "요약 기억", "type": "chat"}, headers=h
    ).json()["id"]
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": GRAPH}, headers=h)
    client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=h)
    res = client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={"memory": {"window": 1, "summary": summary}},
        headers=h,
    )
    assert res.status_code == 200, res.text
    assert res.json()["features"]["memory"] == {"window": 1, "summary": summary}
    return app_id


def _answer(events: list[tuple[str, object]]) -> str:
    return str(next(d for n, d in events if n == "answer")["text"])  # type: ignore[index]


def test_summary_memory(client: TestClient, team: Team, fake_llm: FakeAdapter) -> None:
    add_llm(client, team)
    app_id = _chat_app(client, team, summary=True)
    token = deploy(client, team, app_id)
    ev = chat(client, token, "제 이름은 김철수예요")
    sid = next(d for n, d in ev if n == "session")["session_id"]
    for msg in ("주문번호는 A-17", "배송지는 부산", "언제 와요?"):
        ev = chat(client, token, msg, session_id=sid)
    # 메시지 8개 중 기억 창(1턴=2개) 밖의 6개 → 요약이 만들어졌다
    with SessionLocal() as db:
        conv = db.scalar(select(Conversation).where(Conversation.app_id == app_id))
        assert conv is not None
        assert conv.summary.startswith("요약:")
        assert conv.summary_upto is not None
    summary_calls = [c for c in fake_llm.calls if "대화 기록을 요약" in c["system"]]
    assert summary_calls and "김철수" in summary_calls[0]["prompt"]
    # 다음 답에는 요약 + 최근 대화가 함께 들어간다
    text = _answer(chat(client, token, "고마워요", session_id=sid))
    assert "[앞선 대화 요약]" in text and "[최근 대화]" in text and "언제 와요?" in text


def test_summary_off_keeps_plain_window(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    token = deploy(client, team, _chat_app(client, team, summary=False))
    ev = chat(client, token, "하나")
    sid = next(d for n, d in ev if n == "session")["session_id"]
    for msg in ("둘", "셋", "넷"):
        ev = chat(client, token, msg, session_id=sid)
    text = _answer(ev)
    assert text.startswith("기록<user: 셋")
    assert not any("대화 기록을 요약" in c["system"] for c in fake_llm.calls)


def test_summary_skipped_without_ai_key(client: TestClient, team: Team) -> None:
    """AI 연결이 없어도 대화는 그대로 이어진다(요약만 건너뜀)."""
    token = deploy(client, team, _chat_app(client, team, summary=True))
    ev = chat(client, token, "하나")
    sid = next(d for n, d in ev if n == "session")["session_id"]
    for msg in ("둘", "셋", "넷"):
        ev = chat(client, token, msg, session_id=sid)
    assert "user: 셋" in _answer(ev)
