"""v0.3: 개인 설정(이름·테마·글자 크기·기본 워크스페이스·비밀번호)과 프로젝트(공개 범위·접근 제어)."""

from fastapi.testclient import TestClient

from api.db import SessionLocal
from api.models import Membership, User
from api.tests.conftest import PASSWORD, Team


def test_personal_settings(client: TestClient, team: Team) -> None:
    me = client.get("/api/v1/me", headers=team.h("builder")).json()
    assert me["preferences"] == {
        "theme": "system",
        "font_size": "normal",
        "default_workspace_id": None,
        "enter_to_send": True,
        "lists": {},
        "onboarding": {"tour_done": False, "checklist_dismissed": False, "steps_done": []},
        "agreements": {},
    }
    upd = client.patch(
        "/api/v1/me",
        json={
            "name": "새 이름",
            "preferences": {"theme": "dark", "font_size": "large", "default_workspace_id": team.ws},
        },
        headers=team.h("builder"),
    ).json()
    assert (
        upd["name"] == "새 이름"
        and upd["preferences"]["theme"] == "dark"
        and upd["preferences"]["enter_to_send"] is True
    )
    assert (
        client.patch(
            "/api/v1/me", json={"preferences": {"theme": "neon"}}, headers=team.h("builder")
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/v1/me",
            json={"preferences": {"default_workspace_id": "없는곳"}},
            headers=team.h("builder"),
        ).status_code
        == 404
    )
    # 다른 사용자에게는 영향 없음
    assert (
        client.get("/api/v1/me", headers=team.h("member")).json()["preferences"]["theme"]
        == "system"
    )


def test_change_password(client: TestClient, team: Team) -> None:
    bad = client.post(
        "/api/v1/me/password",
        json={"current_password": "틀림12345", "new_password": "newpass123"},
        headers=team.h("member"),
    )
    assert bad.status_code == 400 and "지금 비밀번호" in bad.json()["detail"]["message"]
    ok = client.post(
        "/api/v1/me/password",
        json={"current_password": PASSWORD, "new_password": "newpass123"},
        headers=team.h("member"),
    )
    assert ok.json()["ok"] is True and ok.json()["access_token"] and ok.json()["refresh_token"]
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "member@test.local", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "member@test.local", "password": "newpass123"}
        ).status_code
        == 200
    )


def _other_builder(team: Team) -> dict[str, str]:
    """같은 워크스페이스의 두 번째 builder."""
    from api.core.security import create_tokens, hash_password

    with SessionLocal() as db:
        u = User(email="builder2@test.local", name="빌더2", password_hash=hash_password(PASSWORD))
        db.add(u)
        db.flush()
        db.add(Membership(user_id=u.id, workspace_id=team.ws, role="builder"))
        db.commit()
        team.users["builder2"] = u.id
        return {"Authorization": f"Bearer {create_tokens(u.id)['access_token']}"}


def test_projects_visibility_and_access(client: TestClient, team: Team) -> None:
    b2 = _other_builder(team)
    pub = client.post(
        f"/api/v1/workspaces/{team.ws}/projects",
        json={"name": "공용 프로젝트"},
        headers=team.h("builder"),
    ).json()
    priv = client.post(
        f"/api/v1/workspaces/{team.ws}/projects",
        json={"name": "내 개인", "visibility": "private", "color": "rose"},
        headers=team.h("builder"),
    ).json()
    assert (
        client.post(
            f"/api/v1/workspaces/{team.ws}/projects", json={"name": "x"}, headers=team.h("operator")
        ).status_code
        == 403
    )

    a_pub = client.post(
        f"/api/v1/workspaces/{team.ws}/apps",
        json={"name": "공용앱", "project_id": pub["id"]},
        headers=team.h("builder"),
    ).json()
    a_priv = client.post(
        f"/api/v1/workspaces/{team.ws}/apps",
        json={"name": "개인앱", "project_id": priv["id"]},
        headers=team.h("builder"),
    ).json()
    client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "미분류"}, headers=team.h("builder")
    )
    kb_priv = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "개인KB", "project_id": priv["id"]},
        headers=team.h("builder"),
    ).json()

    # 만든 사람: 전부 보임, 프로젝트별 필터
    def names(h: dict[str, str], q: str = "") -> set[str]:
        return {
            a["name"] for a in client.get(f"/api/v1/workspaces/{team.ws}/apps{q}", headers=h).json()
        }

    assert names(team.h("builder")) == {"공용앱", "개인앱", "미분류"}
    assert names(team.h("builder"), f"?project={priv['id']}") == {"개인앱"}
    assert names(team.h("builder"), "?project=none") == {"미분류"}

    # 다른 builder: 비공개 프로젝트·앱·KB가 안 보이고 직접 열어도 없음
    assert {
        p["name"] for p in client.get(f"/api/v1/workspaces/{team.ws}/projects", headers=b2).json()
    } == {"공용 프로젝트"}
    assert names(b2) == {"공용앱", "미분류"}
    assert client.get(f"/api/v1/apps/{a_priv['id']}", headers=b2).status_code == 404
    assert (
        client.post(f"/api/v1/apps/{a_priv['id']}/builder/sessions", headers=b2).status_code == 404
    )
    assert (
        client.get(f"/api/v1/knowledge-bases/{kb_priv['id']}/documents", headers=b2).status_code
        == 404
    )
    assert (
        "개인KB" not in client.get(f"/api/v1/workspaces/{team.ws}/knowledge-bases", headers=b2).text
    )
    assert client.get(f"/api/v1/apps/{a_pub['id']}", headers=b2).status_code == 200
    # 비공개 프로젝트로 옮겨 넣기도 막힘
    assert (
        client.patch(
            f"/api/v1/apps/{a_pub['id']}", json={"project_id": priv["id"]}, headers=b2
        ).status_code
        == 403
    )

    # 관리자는 관리 목적으로 모두 봄
    assert names(team.h("admin")) == {"공용앱", "개인앱", "미분류"}

    # 멤버로 초대하면 보임, 관리(수정)는 만든 사람·관리자만
    res = client.put(
        f"/api/v1/projects/{priv['id']}/members",
        json={"user_ids": [team.users["builder2"]]},
        headers=team.h("builder"),
    ).json()
    assert [m["name"] for m in res["members"]] == ["빌더2"]
    assert client.get(f"/api/v1/apps/{a_priv['id']}", headers=b2).status_code == 200
    assert (
        client.patch(
            f"/api/v1/projects/{priv['id']}", json={"name": "바꿈"}, headers=b2
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/v1/projects/{priv['id']}/members",
            json={"user_ids": ["외부인"]},
            headers=team.h("builder"),
        ).status_code
        == 422
    )

    # 앱 옮기기 → 프로젝트 없음
    moved = client.patch(
        f"/api/v1/apps/{a_pub['id']}", json={"project_id": ""}, headers=team.h("builder")
    ).json()
    assert moved["project_id"] is None

    # 프로젝트 삭제: 앱·KB는 남고 공용으로
    counts = {
        p["name"]: (p["app_count"], p["knowledge_base_count"])
        for p in client.get(
            f"/api/v1/workspaces/{team.ws}/projects", headers=team.h("builder")
        ).json()
    }
    assert counts["내 개인"] == (1, 1)
    assert (
        client.delete(f"/api/v1/projects/{priv['id']}", headers=team.h("builder")).status_code
        == 204
    )
    assert names(b2) == {"공용앱", "개인앱", "미분류"}
    logs = {
        e["action"]
        for e in client.get(
            f"/api/v1/workspaces/{team.ws}/audit-logs", headers=team.h("owner")
        ).json()
    }
    assert {"project.create", "project.members", "project.delete"} <= logs
