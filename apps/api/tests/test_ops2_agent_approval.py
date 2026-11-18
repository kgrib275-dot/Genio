"""에이전트 도구 실행 전 사람 승인: 멈췄다가 승인·반려로 이어진다."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.engine import safe_http
from api.engine.agent import tool_key
from api.tests.conftest import Team, add_llm
from api.tests.fakes import FakeAdapter, text_turn, tool_turn
from api.tests.test_v02_nodes import chain, inp, out

URL = {"url": "https://example.com/fx"}


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def fake(m: str, u: str, **kw: Any) -> dict[str, Any]:
        seen.append(u)
        return {"status": 200, "body": "<p>환율 1300원</p>", "headers": {}}

    monkeypatch.setattr(safe_http, "request", fake)
    return seen


def _start(client: TestClient, team: Team, approval: bool) -> tuple[str, dict[str, Any]]:
    g = chain(
        inp("message"),
        {
            "id": "n2",
            "type": "agent",
            "data": {
                "query": "{{n1.message}}",
                "tools": [{"type": "web", "approval": approval}],
                "approver_roles": ["owner", "admin", "builder"],
                "max_iterations": 3,
            },
        },
        out("{{n2.text}}"),
    )
    app_id = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "승인"}, headers=team.h("builder")
    ).json()["id"]
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": g}, headers=team.h("builder"))
    run = client.post(
        f"/api/v1/apps/{app_id}/runs",
        json={"input": {"message": "환율 알려 줘"}},
        headers=team.h("builder"),
    ).json()
    return run["id"], client.get(f"/api/v1/runs/{run['id']}", headers=team.h("builder")).json()


def _script(fake_llm: FakeAdapter) -> None:
    # 처음 한 번 호출 → (승인 뒤 다시 실행) → 같은 호출 → 최종 답
    fake_llm.script = [
        tool_turn("환율을 확인할게요.", ("read_web_page", URL)),
        text_turn("환율은 1300원이에요."),
    ]


def test_tool_key_is_stable() -> None:
    assert tool_key("a", {"x": 1, "y": 2}) == tool_key("a", {"y": 2, "x": 1})
    assert tool_key("a", {"x": 1}) != tool_key("a", {"x": 2})
    assert tool_key("a", {"x": 1}) != tool_key("b", {"x": 1})


def test_pauses_then_approved_runs_the_tool(
    client: TestClient, team: Team, fake_llm: FakeAdapter, web: list[str]
) -> None:
    add_llm(client, team)
    _script(fake_llm)
    run_id, d = _start(client, team, approval=True)
    assert d["status"] == "waiting_approval" and web == []  # 아직 도구를 쓰지 않았다
    assert "read_web_page" in d["approval"]["title"]
    assert d["approval"]["detail"].count("example.com/fx") == 1
    assert d["approval"]["approver_roles"] == ["owner", "admin", "builder"]
    # 승인 권한이 없는 역할은 거절된다
    deny = client.post(
        f"/api/v1/runs/{run_id}/approve", json={"approved": True}, headers=team.h("operator")
    )
    assert deny.status_code in (403, 404)
    # 승인 → 같은 호출이 이번에는 실행되고 흐름이 끝난다
    _script(fake_llm)
    res = client.post(
        f"/api/v1/runs/{run_id}/approve",
        json={"approved": True, "comment": "괜찮아요"},
        headers=team.h("builder"),
    )
    assert res.status_code == 200, res.text
    done = client.get(f"/api/v1/runs/{run_id}", headers=team.h("builder")).json()
    assert done["status"] == "succeeded", done["error"]
    assert web == [URL["url"]]
    assert done["output"]["text"] == "환율은 1300원이에요."
    log = " ".join(str(s.get("logs")) for s in done["steps"])
    assert "승인했어요" in log


def test_rejected_tool_is_not_run(
    client: TestClient, team: Team, fake_llm: FakeAdapter, web: list[str]
) -> None:
    add_llm(client, team)
    _script(fake_llm)
    run_id, d = _start(client, team, approval=True)
    assert d["status"] == "waiting_approval"
    fake_llm.script = [
        tool_turn("확인할게요.", ("read_web_page", URL)),
        text_turn("승인되지 않아 환율은 확인하지 못했어요."),
    ]
    client.post(
        f"/api/v1/runs/{run_id}/approve", json={"approved": False}, headers=team.h("builder")
    )
    done = client.get(f"/api/v1/runs/{run_id}", headers=team.h("builder")).json()
    assert done["status"] == "succeeded" and web == []
    tool_step = [s for s in done["steps"] if s["node_id"] == "n2"][-1]
    calls = tool_step["output"]["tool_calls"]
    assert calls[0]["ok"] is False and "거절" in calls[0]["summary"]


def test_tool_without_approval_runs_immediately(
    client: TestClient, team: Team, fake_llm: FakeAdapter, web: list[str]
) -> None:
    add_llm(client, team)
    _script(fake_llm)
    _, d = _start(client, team, approval=False)
    assert d["status"] == "succeeded" and web == [URL["url"]]
