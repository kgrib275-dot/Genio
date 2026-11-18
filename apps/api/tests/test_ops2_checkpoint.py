"""빌더 차례 되돌리기(체크포인트)."""

from typing import Any

from fastapi.testclient import TestClient

from api.tests.conftest import Team, add_llm
from api.tests.fakes import FakeAdapter, text_turn, tool_turn
from api.tests.test_builder import new_session, send


def _msgs(client: TestClient, team: Team, sid: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = client.get(
        f"/api/v1/builder/sessions/{sid}/messages", headers=team.h("builder")
    ).json()
    return rows


def _draft(client: TestClient, team: Team, app_id: str) -> dict[str, Any]:
    graph: dict[str, Any] = client.get(f"/api/v1/apps/{app_id}", headers=team.h("builder")).json()[
        "draft_graph"
    ]
    return graph


def _add(label: str) -> Any:
    return tool_turn(
        "단계를 더할게요.",
        ("add_node", {"type": "template", "data": {"label": label, "template": "안녕"}}),
    )


def test_revert_restores_previous_graph(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    app_id, sid = new_session(client, team, "되돌리기")
    start = {n["id"] for n in _draft(client, team, app_id)["nodes"]}
    fake_llm.script = [_add("인사"), text_turn("더했어요.")]
    events = send(client, team, sid, "인사 단계 더해 줘")
    done = next(d for n, d in events if n == "done")
    assert done["graph_patch"]["revertible"] is True
    assert "checkpoint" not in done["graph_patch"]  # 흐름 전체는 화면에 보내지 않는다
    assert len(_draft(client, team, app_id)["nodes"]) == len(start) + 1
    url = f"/api/v1/builder/sessions/{sid}/messages/{done['id']}/revert"
    res = client.post(url, json={}, headers=team.h("builder"))
    assert res.status_code == 200 and res.json()["had_later_changes"] is False
    assert {n["id"] for n in _draft(client, team, app_id)["nodes"]} == start
    after = next(m for m in _msgs(client, team, sid) if m["id"] == done["id"])
    assert after["graph_patch"]["reverted"] is True and after["graph_patch"]["revertible"] is False
    again = client.post(url, json={}, headers=team.h("builder"))
    assert again.status_code == 409 and "이미 되돌린" in again.json()["detail"]["message"]


def test_revert_needs_force_after_later_change(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    _, sid = new_session(client, team, "뒤 변경")
    fake_llm.script = [_add("첫째"), text_turn("1"), _add("둘째"), text_turn("2")]
    first = next(d for n, d in send(client, team, sid, "하나") if n == "done")
    send(client, team, sid, "둘")
    url = f"/api/v1/builder/sessions/{sid}/messages/{first['id']}/revert"
    res = client.post(url, json={}, headers=team.h("builder"))
    assert res.status_code == 409 and "더 바뀌었어요" in res.json()["detail"]["message"]
    ok = client.post(url, json={"force": True}, headers=team.h("builder"))
    assert ok.status_code == 200 and ok.json()["had_later_changes"] is True


def test_no_change_turn_and_permissions(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    _, sid = new_session(client, team, "권한")
    fake_llm.script = [text_turn("그냥 답해요.")]
    done = next(d for n, d in send(client, team, sid, "안녕") if n == "done")
    url = f"/api/v1/builder/sessions/{sid}/messages/{done['id']}/revert"
    res = client.post(url, json={}, headers=team.h("builder"))
    assert res.status_code == 409 and "되돌릴 수 없어요" in res.json()["detail"]["message"]
    assert client.post(url, json={}, headers=team.h("member")).status_code in (403, 404)
    assert client.post(url, json={}).status_code == 401
