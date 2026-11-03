"""v0.5 보안(부하 시험 보고서 §4): 로그인 시도 제한, 비밀번호 규칙, 믿을 수 있는 프록시 IP, CORS,
NUL 문자, API 키 권한 범위."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from api.core.password_policy import password_problem
from api.routers.common import client_ip
from api.tests.conftest import PASSWORD, Team
from api.tests.test_v04_triggers import echo_graph, make_app


def _req(peer: str, xff: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    scope: dict[str, Any] = {"type": "http", "headers": headers, "client": (peer, 1234)}
    return Request(scope)


def test_client_ip_only_trusts_proxies() -> None:
    # 바깥에서 바로 온 요청: 헤더를 꾸며도 무시
    assert client_ip(_req("203.0.113.7", "1.1.1.1")) == "203.0.113.7"
    # nginx(사설 IP)를 거친 요청: 오른쪽부터 처음 만나는 바깥 주소
    assert client_ip(_req("172.18.0.5", "9.9.9.9, 203.0.113.7")) == "203.0.113.7"
    assert client_ip(_req("127.0.0.1", "203.0.113.7, 10.0.0.2")) == "203.0.113.7"
    assert client_ip(_req("172.18.0.5")) == "172.18.0.5"
    assert client_ip(_req("172.18.0.5", "10.0.0.9")) == "10.0.0.9"


@pytest.mark.parametrize(
    ("pw", "ok"),
    [
        ("12345678", False),
        ("abcdefgh", False),
        ("abcd1234", False),
        ("short1", False),
        ("Spring2026walk", True),
        (PASSWORD, True),
    ],
)
def test_password_policy(pw: str, ok: bool) -> None:
    assert (password_problem(pw) is None) is ok


def test_password_policy_on_signup_and_change(client: TestClient, team: Team) -> None:
    weak = client.post(
        "/api/v1/auth/signup",
        json={"email": "w@example.com", "password": "12345678", "name": "약함"},
    )
    assert weak.status_code == 422 and weak.json()["detail"]["hint"]
    same = client.post(
        "/api/v1/auth/signup",
        json={"email": "kimchi99@example.com", "password": "kimchi99", "name": "x"},
    )
    assert same.status_code == 422
    res = client.post(
        "/api/v1/me/password",
        json={"current_password": PASSWORD, "new_password": "password123"},
        headers=team.h("member"),
    )
    assert res.status_code == 422 and "흔한" in res.json()["detail"]["message"]


def test_login_throttling(client: TestClient, team: Team) -> None:
    def login(pw: str, email: str = "member@test.local") -> int:
        return client.post("/api/v1/auth/login", json={"email": email, "password": pw}).status_code

    assert login(PASSWORD) == 200
    codes = [login("wrong-pass-1") for _ in range(5)]
    assert codes == [401] * 5
    blocked = client.post(
        "/api/v1/auth/login", json={"email": "member@test.local", "password": PASSWORD}
    )
    assert blocked.status_code == 429 and "분 뒤" in blocked.json()["detail"]["hint"]
    # 다른 계정은 영향 없음
    assert login(PASSWORD, "builder@test.local") == 200
    # 없는 계정도 똑같이 센다(계정이 있는지 드러내지 않음)
    assert [login("x", "ghost@test.local") for _ in range(6)][-1] == 429


def test_cors_restricted(client: TestClient) -> None:
    def allowed(origin: str) -> str | None:
        r = client.options(
            "/api/v1/me",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        return r.headers.get("access-control-allow-origin")

    assert allowed("https://evil-site.attacker.ts.net") is None
    assert allowed("https://evil.example.com") is None
    assert allowed("http://localhost:5190") == "http://localhost:5190"


def test_nul_in_query_is_400(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, echo_graph())
    res = client.get(f"/api/v1/apps/{app_id}/conversations?q=a%00b", headers=team.h("builder"))
    assert res.status_code == 400 and res.json()["detail"]["hint"]


def test_api_key_scopes(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, echo_graph())
    url = f"/api/v1/apps/{app_id}/api-keys"
    default = client.post(url, json={"name": "기본"}, headers=team.h("builder")).json()
    assert default["scopes"] == ["chat", "run"]
    logs_only = client.post(
        url, json={"name": "기록", "scopes": ["logs"]}, headers=team.h("builder")
    ).json()
    assert logs_only["scopes"] == ["logs"]
    assert (
        client.post(url, json={"name": "x", "scopes": []}, headers=team.h("builder")).status_code
        == 422
    )
    assert (
        client.post(
            url, json={"name": "x", "scopes": ["admin"]}, headers=team.h("builder")
        ).status_code
        == 422
    )

    def h(k: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {k['key']}"}

    run = client.post(
        "/api/v1/service/workflows/run", json={"inputs": {"message": "안녕"}}, headers=h(default)
    )
    assert run.status_code == 200, run.text
    denied = client.post("/api/v1/service/workflows/run", json={"inputs": {}}, headers=h(logs_only))
    assert denied.status_code == 403 and "권한" in denied.json()["detail"]["message"]
    assert client.get("/api/v1/service/runs", headers=h(default)).status_code == 403
    listed = client.get("/api/v1/service/runs", headers=h(logs_only))
    assert listed.status_code == 200 and listed.json()[0]["run_id"] == run.json()["run_id"]
    one = client.get(f"/api/v1/service/runs/{run.json()['run_id']}", headers=h(logs_only)).json()
    assert one["status"] == run.json()["status"]
    keys = client.get(url, headers=team.h("builder")).json()
    assert {tuple(k["scopes"]) for k in keys} == {("chat", "run"), ("logs",)}
