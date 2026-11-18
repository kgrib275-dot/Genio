"""빌더 상시 규칙."""

from fastapi.testclient import TestClient

from api.services import builder_rules
from api.tests.conftest import Team, add_llm
from api.tests.fakes import FakeAdapter, text_turn
from api.tests.test_builder import new_session, send


def test_prompt_block() -> None:
    assert builder_rules.prompt_block("  ") == ""
    block = builder_rules.prompt_block("알림은 늘 잔디로 보내.")
    assert "<rules>" in block and "알림은 늘 잔디로" in block and "기본 규칙" in block


def test_rules_reach_the_builder_system_prompt(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team)
    url = f"/api/v1/workspaces/{team.ws}/builder-rules"
    assert client.get(url, headers=team.h("admin")).json()["rules"] == ""
    res = client.put(
        url, json={"rules": "  알림은 늘 잔디로 보내.\r\n글은 존댓말로.  "}, headers=team.h("admin")
    )
    assert (
        res.status_code == 200 and res.json()["rules"] == "알림은 늘 잔디로 보내.\n글은 존댓말로."
    )
    _, sid = new_session(client, team, "규칙")
    fake_llm.script = [text_turn("네.")]
    send(client, team, sid, "안녕")
    system = str(fake_llm.calls[0]["system"])
    assert "알림은 늘 잔디로 보내." in system and "상시 규칙" in system
    client.put(url, json={"rules": ""}, headers=team.h("admin"))
    fake_llm.script = [text_turn("네.")]
    send(client, team, sid, "또")
    assert "상시 규칙" not in str(fake_llm.calls[-1]["system"])


def test_rules_are_clamped_and_admin_only(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/builder-rules"
    long = client.put(url, json={"rules": "가" * 4000}, headers=team.h("owner")).json()["rules"]
    assert len(long) == builder_rules.MAX_RULES
    assert client.put(url, json={"rules": "x" * 4001}, headers=team.h("owner")).status_code == 422
    assert client.get(url, headers=team.h("builder")).status_code == 403
    assert client.put(url, json={"rules": "a"}, headers=team.h("builder")).status_code == 403
    assert client.get(url).status_code == 401
