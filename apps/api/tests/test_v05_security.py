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
        json={
            "email": "w@example.com",
            "password": "12345678",
            "name": "약함",
            "agree_terms": True,
            "agree_privacy": True,
        },
    )
    assert weak.status_code == 422 and weak.json()["detail"]["hint"]
    same = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "kimchi99@example.com",
            "password": "kimchi99",
            "name": "x",
            "agree_terms": True,
            "agree_privacy": True,
        },
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


# ---------------- v0.9 점검에서 찾은 인증 보강 ----------------
def test_password_change_revokes_other_sessions(client: TestClient, team: Team) -> None:
    """비밀번호를 바꾸면 다른 기기의 로그인(옛 토큰)은 끊기고, 이 기기는 새 토큰으로 이어 쓴다."""
    import time

    email = "builder@test.local"
    pw = "password123!"
    other = client.post("/api/v1/auth/login", json={"email": email, "password": pw}).json()
    time.sleep(1.1)  # 토큰 발급 시각(초 단위)이 서로 다르게
    mine = client.post("/api/v1/auth/login", json={"email": email, "password": pw}).json()
    h_mine = {"Authorization": f"Bearer {mine['access_token']}"}
    h_other = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get("/api/v1/me", headers=h_other).status_code == 200
    time.sleep(1.1)
    r = client.post(
        "/api/v1/me/password",
        json={"current_password": pw, "new_password": "Brand#New2026pw"},
        headers=h_mine,
    )
    assert r.status_code == 200, r.text
    new_h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/v1/me", headers=new_h).status_code == 200  # 이 기기는 계속
    assert client.get("/api/v1/me", headers=h_other).status_code == 401  # 다른 기기는 끊김
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": other["refresh_token"]})
    assert refreshed.status_code == 401


def test_password_longer_than_72_bytes_rejected(client: TestClient, team: Team) -> None:
    """bcrypt는 앞 72바이트만 보므로 더 긴 새 비밀번호는 거절한다(뒤쪽이 무시되는 착각 방지)."""
    long_pw = "Aa1" + "x" * 70  # 73바이트
    r = client.post(
        "/api/v1/me/password",
        json={"current_password": "password123!", "new_password": long_pw},
        headers=team.h("member"),
    )
    assert r.status_code == 422 and "72" in r.json()["detail"]["message"]
    korean = "가나다라마바사아자차카타파하거너더러머버서어저처" + "Aa1"  # 한글 3바이트 × 24 + 3
    r = client.post(
        "/api/v1/me/password",
        json={"current_password": "password123!", "new_password": korean},
        headers=team.h("member"),
    )
    assert r.status_code == 422
    ok = client.post(
        "/api/v1/me/password",
        json={"current_password": "password123!", "new_password": "A1" + "y" * 70},
        headers=team.h("member"),
    )
    assert ok.status_code == 200  # 정확히 72바이트는 허용


def test_login_timing_does_not_reveal_accounts(client: TestClient, team: Team) -> None:
    """없는 계정도 비밀번호 확인(bcrypt)을 한 번 거치므로 응답 시간이 크게 다르지 않다."""
    import time

    def avg(email: str) -> float:
        times = []
        for i in range(4):
            t = time.perf_counter()
            client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong-pass-1"},
                headers={"X-Forwarded-For": f"10.9.{abs(hash(email)) % 200}.{i}"},
            )
            times.append(time.perf_counter() - t)
        return sum(times) / len(times)

    known, unknown = avg("owner@test.local"), avg("nobody-here@test.local")
    assert unknown > known * 0.5, (known, unknown)


def test_query_token_only_on_stream_routes(client: TestClient, team: Team) -> None:
    """주소창 토큰(?access_token=)은 스트림 경로에서만 받는다. 일반 API에서는 무시한다."""
    token = team.tokens["owner"]
    assert client.get(f"/api/v1/me?access_token={token}").status_code == 401
    assert client.get("/api/v1/me", headers=team.h("owner")).status_code == 200


def _invite(client: TestClient, team: Team, email: str) -> str:
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/invitations",
        json={"email": email, "role": "operator"},
        headers=team.h("admin"),
    )
    assert r.status_code in (200, 201), r.text
    return str(r.json()["token"])


def _existing_user(email: str, totp: bool = False) -> None:
    from api.core.security import hash_password
    from api.db import SessionLocal
    from api.models import User

    with SessionLocal() as db:
        db.add(
            User(email=email, password_hash=hash_password(PASSWORD), name="기존", totp_enabled=totp)
        )
        db.commit()


def test_invite_accept_is_not_a_password_oracle(client: TestClient, team: Team) -> None:
    """기존 계정으로 초대를 수락할 때 비밀번호를 틀리면 로그인과 같은 시도 제한이 걸린다."""
    _existing_user("someone@example.com")
    token = _invite(client, team, "someone@example.com")
    url = f"/api/v1/auth/invitations/{token}/accept"
    codes = [
        client.post(url, json={"name": "x", "password": f"wrong-{i}-pw"}).status_code
        for i in range(12)
    ]
    assert codes[0] == 401 and 429 in codes


def test_invite_accept_refuses_2fa_account_without_login(client: TestClient, team: Team) -> None:
    """2단계 인증 계정은 비밀번호만으로 초대를 수락(=토큰 발급)할 수 없다."""
    _existing_user("otp@example.com", totp=True)
    token = _invite(client, team, "otp@example.com")
    r = client.post(
        f"/api/v1/auth/invitations/{token}/accept", json={"name": "x", "password": PASSWORD}
    )
    assert r.status_code == 409 and "2단계" in r.json()["detail"]["message"]


def test_invite_accept_when_logged_in_needs_no_password(client: TestClient, team: Team) -> None:
    _existing_user("me2@example.com")
    login = client.post(
        "/api/v1/auth/login", json={"email": "me2@example.com", "password": PASSWORD}
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    token = _invite(client, team, "me2@example.com")
    r = client.post(f"/api/v1/auth/invitations/{token}/accept", json={"name": "기존"}, headers=h)
    assert r.status_code == 200, r.text


def test_csv_formula_cells_are_neutralized() -> None:
    from api.routers.ops import _csv_safe

    assert _csv_safe("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert _csv_safe("@SUM(A1)") == "'@SUM(A1)"
    assert _csv_safe("member.login") == "member.login"
    assert _csv_safe("") == ""


def test_non_ascii_signature_does_not_crash() -> None:
    from api.core.totp import verify

    assert verify("JBSWY3DPEHPK3PXP", "١٢٣٤٥٦") is False
    from api.services import file_links

    assert file_links.verify("a", "f", "서명", 9999999999) is False


def test_not_found_uses_right_particle() -> None:
    from api.core.errors import eul_reul

    assert eul_reul("앱") == "앱을"
    assert eul_reul("파일") == "파일을"
    assert eul_reul("멤버") == "멤버를"
    assert eul_reul("API 키") == "API 키를"
    assert eul_reul("MCP") == "MCP을(를)"
