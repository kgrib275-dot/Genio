"""v0.6 처음 쓰는 사람 안내: 약관 동의 기록, 안내 진행 상태(개인 설정), 시작 체크리스트, 의견·문의."""

import pytest
from fastapi.testclient import TestClient

from api.tests.conftest import ROLES, Team, add_llm
from api.tests.test_v05_engine import make_app, start

PW = "Spring2026walk"


def test_signup_requires_agreement_and_records_it(client: TestClient) -> None:
    base = {"email": "agree@example.com", "password": PW, "name": "동의"}
    no = client.post("/api/v1/auth/signup", json=base)
    assert no.status_code == 422
    assert "동의" in no.json()["detail"]["message"] and no.json()["detail"]["hint"]
    half = client.post("/api/v1/auth/signup", json={**base, "agree_terms": True})
    assert half.status_code == 422
    ok = client.post(
        "/api/v1/auth/signup", json={**base, "agree_terms": True, "agree_privacy": True}
    )
    assert ok.status_code == 200
    h = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    prefs = client.get("/api/v1/me", headers=h).json()["preferences"]
    ag = prefs["agreements"]
    assert ag["terms"] and ag["privacy"] and ag["at"]
    assert prefs["onboarding"] == {
        "tour_done": False,
        "checklist_dismissed": False,
        "steps_done": [],
    }
    # 동의 기록은 PATCH로 바꿀 수 없다
    client.patch("/api/v1/me", json={"preferences": {"agreements": {}}}, headers=h)
    assert client.get("/api/v1/me", headers=h).json()["preferences"]["agreements"] == ag


def test_onboarding_prefs_merge(client: TestClient, team: Team) -> None:
    h = team.h("member")
    client.patch("/api/v1/me", json={"preferences": {"onboarding": {"tour_done": True}}}, headers=h)
    client.patch(
        "/api/v1/me",
        json={"preferences": {"onboarding": {"steps_done": ["samples", "samples", "app"]}}},
        headers=h,
    )
    ob = client.get("/api/v1/me", headers=h).json()["preferences"]["onboarding"]
    assert ob == {"tour_done": True, "checklist_dismissed": False, "steps_done": ["app", "samples"]}
    # 다른 사람에게는 영향이 없다
    other = client.get("/api/v1/me", headers=team.h("builder")).json()["preferences"]
    assert other["onboarding"]["tour_done"] is False


def test_checklist_status_from_real_data(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/onboarding"
    st = client.get(url, headers=team.h("member")).json()
    assert st["ai_connected"] is False and st["app_created"] is False
    # 팀 멤버 5명이 이미 있으니 초대 항목은 끝난 것으로 본다
    assert st["team_invited"] is True
    add_llm(client, team)
    app_id = make_app(
        client,
        team,
        {
            "nodes": [
                {"id": "n1", "type": "input", "data": {"fields": [{"key": "m"}]}},
                {"id": "n2", "type": "output", "data": {"template": "{{n1.m}}"}},
            ],
            "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
        },
    )
    start(client, team, app_id, {"m": "안녕"})
    client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=team.h("builder"))
    st = client.get(url, headers=team.h("member")).json()
    assert st["ai_connected"] and st["app_created"] and st["test_run"] and st["version_saved"]
    assert st["deployed"] is False


@pytest.mark.parametrize("role", ROLES)
def test_feedback_send_and_list_permissions(client: TestClient, team: Team, role: str) -> None:
    sent = client.post(
        f"/api/v1/workspaces/{team.ws}/feedback",
        json={"kind": "bug", "message": "저장 버튼이 안 눌려요", "page": "/apps"},
        headers=team.h(role),
    )
    assert sent.status_code == 201
    listed = client.get(f"/api/v1/workspaces/{team.ws}/feedback", headers=team.h(role))
    if role in ("owner", "admin"):
        assert listed.status_code == 200
        item = listed.json()[0]
        assert item["message"] == "저장 버튼이 안 눌려요" and item["kind"] == "bug"
        assert item["user_email"] == f"{role}@test.local"
    else:
        assert listed.status_code == 403


def test_feedback_validation_and_outsider(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    url = f"/api/v1/workspaces/{team.ws}/feedback"
    bad = client.post(url, json={"message": ""}, headers=team.h("member"))
    assert bad.status_code == 422
    assert client.post(url, json={"message": "안녕하세요"}, headers=outsider).status_code == 404
    logs = client.get(f"/api/v1/workspaces/{team.ws}/audit-logs", headers=team.h("admin")).json()
    assert all(entry["action"] != "feedback.send" for entry in logs)
