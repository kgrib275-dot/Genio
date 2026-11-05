"""v0.8 관리자가 내준 임시 비밀번호: 첫 로그인 때 바꿔야 하고, 바꾸기 전에는 다른 기능을 막는다.
가입을 끄면 로그인 전 화면이 알 수 있고(auth/config), 가입 요청은 두 줄 오류로 거절한다."""

from typing import Any

from fastapi.testclient import TestClient

from api.tests.conftest import Team

NEW_PW = "BrandNew#2026pw"


def _login(client: TestClient, email: str, password: str) -> dict[str, Any]:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def _issue(client: TestClient, team: Team, email: str, **extra: Any) -> dict[str, Any]:
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/admin/accounts",
        json={"email": email, "name": "신입", **extra},
        headers=team.h("admin"),
    )
    assert r.status_code == 201, r.text
    out: dict[str, Any] = r.json()
    return out


def test_temp_password_must_be_changed(client: TestClient, team: Team) -> None:
    issued = _issue(client, team, "new1@corp.local", role="builder")
    pw = issued["temporary_password"]
    tok = _login(client, "new1@corp.local", pw)["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    me = client.get("/api/v1/me", headers=h).json()
    assert me["must_change_password"] is True
    # 바꾸기 전에는 내 정보·비밀번호 바꾸기만 된다. 다른 기능은 두 줄 오류로 막는다.
    blocked = client.get(f"/api/v1/workspaces/{team.ws}/apps", headers=h)
    assert blocked.status_code == 403
    detail = blocked.json()["detail"]
    assert "임시 비밀번호" in detail["message"] and detail["hint"]
    assert client.get("/api/v1/me/sessions", headers=h).status_code == 200
    # 지금 비밀번호와 같게는 못 바꾼다, 약한 비밀번호도 못 쓴다
    url = "/api/v1/me/password"
    assert (
        client.post(url, json={"current_password": pw, "new_password": pw}, headers=h).status_code
        == 400
    )
    assert (
        client.post(
            url, json={"current_password": pw, "new_password": "12345678"}, headers=h
        ).status_code
        >= 400
    )
    ok = client.post(url, json={"current_password": pw, "new_password": NEW_PW}, headers=h)
    assert ok.status_code == 200, ok.text
    assert client.get("/api/v1/me", headers=h).json()["must_change_password"] is False
    assert client.get(f"/api/v1/workspaces/{team.ws}/apps", headers=h).status_code == 200
    # 새 비밀번호로 다시 로그인된다
    assert "access_token" in _login(client, "new1@corp.local", NEW_PW)


def test_admin_chosen_password_also_forces_change(client: TestClient, team: Team) -> None:
    _issue(client, team, "new2@corp.local", password="Chosen#pass2026")  # noqa: S106
    tok = _login(client, "new2@corp.local", "Chosen#pass2026")["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/v1/me", headers=h).json()["must_change_password"] is True
    assert client.get(f"/api/v1/workspaces/{team.ws}/apps", headers=h).status_code == 403


def test_reset_password_forces_change_and_ends_old_sessions(client: TestClient, team: Team) -> None:
    issued = _issue(client, team, "new3@corp.local", role="operator")
    tok = _login(client, "new3@corp.local", issued["temporary_password"])["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    client.post(
        "/api/v1/me/password",
        json={"current_password": issued["temporary_password"], "new_password": NEW_PW},
        headers=h,
    )
    tok = _login(client, "new3@corp.local", NEW_PW)["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get(f"/api/v1/workspaces/{team.ws}/apps", headers=h).status_code == 200
    members = client.get(f"/api/v1/workspaces/{team.ws}/members", headers=team.h("owner")).json()
    mid = next(m["id"] for m in members if m["email"] == "new3@corp.local")
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/members/{mid}/reset-password", headers=team.h("admin")
    )
    assert r.status_code == 200
    temp = r.json()["temporary_password"]
    # 예전 로그인은 끊기고, 새 임시 비밀번호로 들어오면 다시 바꿔야 한다
    assert client.get("/api/v1/me", headers=h).status_code == 401
    tok2 = _login(client, "new3@corp.local", temp)["access_token"]
    h2 = {"Authorization": f"Bearer {tok2}"}
    assert client.get("/api/v1/me", headers=h2).json()["must_change_password"] is True


def test_existing_accounts_are_not_forced(client: TestClient, team: Team) -> None:
    me = client.get("/api/v1/me", headers=team.h("builder")).json()
    assert me["must_change_password"] is False


def test_signup_closed(client: TestClient, team: Team) -> None:
    assert client.get("/api/v1/auth/config").json() == {"allow_signup": True}
    r = client.patch("/api/v1/admin/system", json={"allow_signup": False}, headers=team.h("owner"))
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/auth/config").json() == {"allow_signup": False}
    closed = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "walkin@example.com",
            "password": NEW_PW,
            "name": "지나가던 사람",
            "agree_terms": True,
            "agree_privacy": True,
        },
    )
    assert closed.status_code == 403
    assert closed.json()["detail"]["message"] and closed.json()["detail"]["hint"]
