"""라우터별 권한 테스트: 설계서 §3-1 권한표대로 각 역할이 허용/거부되는지."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.tests.conftest import ROLES, Team, add_llm, install, membership_id

ALLOWED = {
    "manage_members": {"owner", "admin"},
    "manage_secrets": {"owner", "admin"},
    "manage_market": {"owner", "admin"},
    "edit_apps": {"owner", "admin", "builder"},
    "deploy": {"owner", "admin", "builder"},
    "view_runs": {"owner", "admin", "builder", "operator"},
    "any_member": set(ROLES),
}


def _new_app(client: TestClient, team: Team) -> str:
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "권한 테스트"}, headers=team.h("owner")
    )
    assert res.status_code == 201, res.text
    app_id: str = res.json()["id"]
    return app_id


Call = Callable[[TestClient, Team, str], Any]

CASES: list[tuple[str, str, Call]] = [
    (
        "초대",
        "manage_members",
        lambda c, t, r: c.post(
            f"/api/v1/workspaces/{t.ws}/invitations",
            json={"email": "new@x.com", "role": "member"},
            headers=t.h(r),
        ),
    ),
    (
        "역할 변경",
        "manage_members",
        lambda c, t, r: c.patch(
            f"/api/v1/workspaces/{t.ws}/members/{membership_id(t, 'member')}",
            json={"role": "operator"},
            headers=t.h(r),
        ),
    ),
    (
        "감사 로그",
        "manage_members",
        lambda c, t, r: c.get(f"/api/v1/workspaces/{t.ws}/audit-logs", headers=t.h(r)),
    ),
    (
        "AI 키 등록",
        "manage_secrets",
        lambda c, t, r: c.post(
            f"/api/v1/workspaces/{t.ws}/llm-providers",
            json={
                "provider": "openai",
                "label": f"k-{r}",
                "api_key": "sk-abcdefgh",
                "default_model": "gpt-4o-mini",
            },
            headers=t.h(r),
        ),
    ),
    (
        "연결 정보 등록",
        "manage_secrets",
        lambda c, t, r: c.post(
            f"/api/v1/workspaces/{t.ws}/connectors/credentials",
            json={
                "connector_key": "slack",
                "name": f"슬랙-{r}",
                "secrets": {"bot_token": "xoxb-12345678"},
            },
            headers=t.h(r),
        ),
    ),
    (
        "마켓 설치",
        "manage_market",
        lambda c, t, r: c.post(
            f"/api/v1/workspaces/{t.ws}/market/install",
            json={"item_key": "google_sheets"},
            headers=t.h(r),
        ),
    ),
    (
        "앱 생성",
        "edit_apps",
        lambda c, t, r: c.post(
            f"/api/v1/workspaces/{t.ws}/apps", json={"name": "앱"}, headers=t.h(r)
        ),
    ),
    (
        "앱 편집",
        "edit_apps",
        lambda c, t, r: c.patch(
            f"/api/v1/apps/{_new_app(c, t)}", json={"name": "새 이름"}, headers=t.h(r)
        ),
    ),
    (
        "앱 삭제",
        "edit_apps",
        lambda c, t, r: c.delete(f"/api/v1/apps/{_new_app(c, t)}", headers=t.h(r)),
    ),
    (
        "빌더 세션",
        "edit_apps",
        lambda c, t, r: c.post(f"/api/v1/apps/{_new_app(c, t)}/builder/sessions", headers=t.h(r)),
    ),
    ("배포", "deploy", lambda c, t, r: _deploy(c, t, r)),
    (
        "실행 이력",
        "view_runs",
        lambda c, t, r: c.get(f"/api/v1/workspaces/{t.ws}/runs", headers=t.h(r)),
    ),
    (
        "사용량",
        "view_runs",
        lambda c, t, r: c.get(f"/api/v1/workspaces/{t.ws}/usage", headers=t.h(r)),
    ),
    (
        "앱 상세",
        "view_runs",
        lambda c, t, r: c.get(f"/api/v1/apps/{_new_app(c, t)}", headers=t.h(r)),
    ),
    (
        "멤버 목록",
        "any_member",
        lambda c, t, r: c.get(f"/api/v1/workspaces/{t.ws}/members", headers=t.h(r)),
    ),
    (
        "노드 목록",
        "any_member",
        lambda c, t, r: c.get(f"/api/v1/workspaces/{t.ws}/nodes", headers=t.h(r)),
    ),
    (
        "앱 목록",
        "any_member",
        lambda c, t, r: c.get(f"/api/v1/workspaces/{t.ws}/apps", headers=t.h(r)),
    ),
]


def _deploy(c: TestClient, t: Team, role: str) -> Any:
    app_id = _new_app(c, t)
    res = c.post(f"/api/v1/apps/{app_id}/versions", json={"note": "v1"}, headers=t.h("owner"))
    assert res.status_code == 201, res.text
    return c.post(
        f"/api/v1/apps/{app_id}/deployments", json={"channel": "share_link"}, headers=t.h(role)
    )


@pytest.mark.parametrize(("name", "perm", "call"), CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("role", ROLES)
def test_role_matrix(
    client: TestClient, team: Team, role: str, name: str, perm: str, call: Call
) -> None:
    install(client, team, "slack")
    res = call(client, team, role)
    if role in ALLOWED[perm]:
        assert res.status_code < 400, f"{name}: {role} 허용이어야 함 ({res.status_code} {res.text})"
    else:
        assert res.status_code == 403, f"{name}: {role} 거부여야 함 ({res.status_code})"
        detail = res.json()["detail"]
        assert detail["message"] and detail["hint"]


def test_unauthenticated_rejected(client: TestClient, team: Team) -> None:
    res = client.get(f"/api/v1/workspaces/{team.ws}/apps")
    assert res.status_code == 401
    assert res.json()["detail"]["message"] == "로그인이 필요해요."


def test_outsider_cannot_see_workspace(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    app_id = _new_app(client, team)
    assert client.get(f"/api/v1/workspaces/{team.ws}/apps", headers=outsider).status_code == 404
    assert client.get(f"/api/v1/apps/{app_id}", headers=outsider).status_code == 404


def test_member_sees_only_published_apps(client: TestClient, team: Team) -> None:
    _new_app(client, team)
    res = client.get(f"/api/v1/workspaces/{team.ws}/apps", headers=team.h("member"))
    assert res.json() == []
    assert (
        len(client.get(f"/api/v1/workspaces/{team.ws}/apps", headers=team.h("builder")).json()) == 1
    )


def test_last_owner_cannot_be_demoted(client: TestClient, team: Team) -> None:
    res = client.patch(
        f"/api/v1/workspaces/{team.ws}/members/{membership_id(team, 'owner')}",
        json={"role": "admin"},
        headers=team.h("owner"),
    )
    assert res.status_code == 409


def test_admin_cannot_grant_owner(client: TestClient, team: Team) -> None:
    res = client.patch(
        f"/api/v1/workspaces/{team.ws}/members/{membership_id(team, 'member')}",
        json={"role": "owner"},
        headers=team.h("admin"),
    )
    assert res.status_code == 403


def test_llm_key_never_returned(client: TestClient, team: Team) -> None:
    created = add_llm(client, team)
    assert created["api_key_masked"] == "****1234"
    listed = client.get(
        f"/api/v1/workspaces/{team.ws}/llm-providers", headers=team.h("builder")
    ).text
    assert "sk-test-secret" not in listed
    logs = client.get(f"/api/v1/workspaces/{team.ws}/audit-logs", headers=team.h("owner")).text
    assert "sk-test-secret" not in logs
