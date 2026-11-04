"""v0.7 계정 스스로 관리: 시스템 메일, 비밀번호 찾기, 이메일 인증, 2단계 인증, 기기, 내 데이터, 탈퇴."""

import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.core import totp
from api.db import SessionLocal
from api.models import User
from api.services import mailer
from api.tests.conftest import PASSWORD, ROLES, Team

NEW_PW = "Brand-new-pass-77!"
SMTP_PW = "smtp-secret-xyz9"
MASKED = "****xyz9"


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, str]]]:
    box: list[dict[str, str]] = []
    monkeypatch.setattr(mailer, "OUTBOX", box)
    yield box


def _setup_mail(client: TestClient, team: Team) -> None:
    r = client.put(
        "/api/v1/admin/system/mail",
        json={
            "host": "smtp.example.com",
            "port": 587,
            "username": "noreply",
            "password": SMTP_PW,
            "from_addr": "noreply@example.com",
            "security": "starttls",
        },
        headers=team.h("owner"),
    )
    assert r.status_code == 200, r.text
    assert SMTP_PW not in r.text and r.json()["password_masked"] == MASKED


def _link_token(mail: dict[str, str]) -> str:
    m = re.search(r"token=([\w-]+)", mail["text"])
    assert m, mail
    return m.group(1)


def _login(client: TestClient, email: str, pw: str = PASSWORD) -> dict[str, Any]:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def test_mail_settings_admin_only_and_test_mail(
    client: TestClient, team: Team, outbox: list[dict[str, str]]
) -> None:
    for role in ROLES:
        r = client.get("/api/v1/admin/system/mail", headers=team.h(role))
        assert (r.status_code == 200) == (role == "owner"), role
    assert (
        client.put(
            "/api/v1/admin/system/mail", json={"host": "x"}, headers=team.h("admin")
        ).status_code
        == 403
    )
    # 설정 전에는 시험 메일·비밀번호 찾기가 두 줄 안내로 막힌다
    r = client.post("/api/v1/admin/system/mail/test", headers=team.h("owner"))
    assert r.status_code == 503 and r.json()["detail"]["hint"]
    _setup_mail(client, team)
    r = client.post("/api/v1/admin/system/mail/test", headers=team.h("owner"))
    assert r.status_code == 200 and outbox[-1]["to"] == "owner@test.local"
    # 가려진 값을 다시 보내도 저장된 비밀번호는 유지된다
    r = client.put("/api/v1/admin/system/mail", json={"password": MASKED}, headers=team.h("owner"))
    assert r.json()["password_masked"] == MASKED


def test_password_reset_flow(client: TestClient, team: Team, outbox: list[dict[str, str]]) -> None:
    _setup_mail(client, team)
    old = _login(client, "builder@test.local")
    same = client.post("/api/v1/auth/password/forgot", json={"email": "builder@test.local"})
    ghost = client.post("/api/v1/auth/password/forgot", json={"email": "nobody@test.local"})
    # 있는 계정·없는 계정의 답이 같다(계정 존재 여부를 숨김)
    assert same.status_code == ghost.status_code == 200 and same.json() == ghost.json()
    assert len(outbox) == 1 and outbox[0]["to"] == "builder@test.local"
    token = _link_token(outbox[0])
    weak = client.post("/api/v1/auth/password/reset", json={"token": token, "password": "12345678"})
    assert weak.status_code == 422
    r = client.post("/api/v1/auth/password/reset", json={"token": token, "password": NEW_PW})
    assert r.status_code == 200, r.text
    again = client.post("/api/v1/auth/password/reset", json={"token": token, "password": NEW_PW})
    assert again.status_code == 400 and again.json()["detail"]["hint"]  # 한 번만
    # 예전 토큰(다른 기기)은 끊기고, 새 비밀번호로 로그인된다
    h_old = {"Authorization": f"Bearer {old['access_token']}"}
    assert client.get("/api/v1/me", headers=h_old).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": old["refresh_token"]}
        ).status_code
        == 401
    )
    assert "access_token" in _login(client, "builder@test.local", NEW_PW)
    # 너무 자주 요청하면 막힌다
    codes = [
        client.post("/api/v1/auth/password/forgot", json={"email": "member@test.local"}).status_code
        for _ in range(4)
    ]
    assert codes[-1] == 429


def test_email_verification_required(
    client: TestClient, team: Team, outbox: list[dict[str, str]]
) -> None:
    r = client.patch(
        "/api/v1/admin/system", json={"require_email_verification": True}, headers=team.h("owner")
    )
    assert r.status_code == 422  # 메일 설정 없이 켤 수 없다
    _setup_mail(client, team)
    r = client.patch(
        "/api/v1/admin/system", json={"require_email_verification": True}, headers=team.h("owner")
    )
    assert r.status_code == 200 and r.json()["require_email_verification"] is True
    email = "newbie@example.com"
    r = client.post(
        "/api/v1/auth/signup", json={"email": email, "password": NEW_PW, "name": "새내기"}
    )
    assert r.status_code == 200 and r.json() == {"verify_required": True, "email": email}
    assert "access_token" not in r.json()
    assert _login(client, email, NEW_PW) == {"verify_required": True, "email": email}
    client.post("/api/v1/auth/verify-email/resend", json={"email": email})
    token = _link_token(outbox[-1])
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    tokens = _login(client, email, NEW_PW)
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.json()["email_verified"] is True
    # 이미 있던 계정(시험 팀)은 인증 필수를 켜도 로그인된다(관리자가 만든 계정 아님 → 인증 전이면 막힘)
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == "member@test.local").one()
        assert u.email_verified_at is None
    assert _login(client, "member@test.local")["verify_required"] is True


def test_two_factor_login_and_recovery(client: TestClient, team: Team) -> None:
    h = team.h("operator")
    setup = client.post("/api/v1/me/2fa/setup", headers=h).json()
    secret = setup["secret"]
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    assert (
        client.post("/api/v1/me/2fa/enable", json={"code": "000000"}, headers=h).status_code == 400
    )
    r = client.post("/api/v1/me/2fa/enable", json={"code": totp.totp(secret)}, headers=h)
    codes = r.json()["recovery_codes"]
    assert r.status_code == 200 and len(codes) == 10
    assert client.get("/api/v1/me", headers=h).json()["two_factor"] is True
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == "operator@test.local").one()
        assert u.totp_secret_encrypted and secret not in u.totp_secret_encrypted
        assert codes[0] not in (u.recovery_codes or [])  # 해시만 저장
    step = _login(client, "operator@test.local")
    assert step["mfa_required"] and "access_token" not in step
    bad = client.post(
        "/api/v1/auth/login/mfa", json={"mfa_token": step["mfa_token"], "code": "123456"}
    )
    assert bad.status_code == 401 and bad.json()["detail"]["hint"]
    ok = client.post(
        "/api/v1/auth/login/mfa", json={"mfa_token": step["mfa_token"], "code": totp.totp(secret)}
    )
    assert ok.status_code == 200 and "access_token" in ok.json()
    # 복구 코드는 한 번만
    step = _login(client, "operator@test.local")
    r1 = client.post(
        "/api/v1/auth/login/mfa", json={"mfa_token": step["mfa_token"], "code": codes[0]}
    )
    r2 = client.post(
        "/api/v1/auth/login/mfa", json={"mfa_token": step["mfa_token"], "code": codes[0]}
    )
    assert r1.status_code == 200 and r2.status_code == 401
    # 접근 토큰으로 mfa 단계를 건너뛸 수 없다
    assert (
        client.post(
            "/api/v1/auth/login/mfa",
            json={"mfa_token": ok.json()["access_token"], "code": totp.totp(secret)},
        ).status_code
        == 401
    )


def test_admin_resets_member_2fa(client: TestClient, team: Team) -> None:
    h = team.h("member")
    secret = client.post("/api/v1/me/2fa/setup", headers=h).json()["secret"]
    client.post("/api/v1/me/2fa/enable", json={"code": totp.totp(secret)}, headers=h)
    members = client.get(f"/api/v1/workspaces/{team.ws}/members", headers=team.h("admin")).json()
    target = next(m for m in members if m["email"] == "member@test.local")
    assert target["two_factor"] is True
    url = f"/api/v1/workspaces/{team.ws}/members/{target['id']}/reset-2fa"
    for role in ("builder", "operator", "member"):
        assert client.post(url, headers=team.h(role)).status_code == 403
    assert client.post(url, headers=team.h("admin")).status_code == 200
    assert "access_token" in _login(client, "member@test.local")
    logs = client.get(f"/api/v1/workspaces/{team.ws}/audit-logs", headers=team.h("owner")).json()
    items = logs.get("items", logs) if isinstance(logs, dict) else logs
    assert any(x.get("action") == "member.2fa_reset" for x in items)


def test_sessions_list_revoke_and_logout_all(client: TestClient, team: Team) -> None:
    a = _login(client, "builder@test.local")
    b = _login(client, "builder@test.local")
    ha = {"Authorization": f"Bearer {a['access_token']}"}
    hb = {"Authorization": f"Bearer {b['access_token']}"}
    sessions = client.get("/api/v1/me/sessions", headers=ha).json()
    assert len(sessions) >= 2 and sum(1 for s in sessions if s["current"]) == 1
    other = next(s for s in sessions if not s["current"])
    assert client.delete(f"/api/v1/me/sessions/{other['id']}", headers=ha).status_code == 204
    # b 기기가 끊겼다(같은 사람의 다른 로그인)
    assert client.get("/api/v1/me", headers=hb).status_code == 401
    c = _login(client, "builder@test.local")
    fresh = client.post("/api/v1/me/sessions/revoke-all", headers=ha)
    assert fresh.status_code == 200 and "access_token" in fresh.json()
    hc = {"Authorization": f"Bearer {c['access_token']}"}
    assert client.get("/api/v1/me", headers=hc).status_code == 401
    hn = {"Authorization": f"Bearer {fresh.json()['access_token']}"}
    assert client.get("/api/v1/me", headers=hn).status_code == 200
    # 남의 기기는 끊을 수 없다
    mine = client.get("/api/v1/me/sessions", headers=hn).json()[0]["id"]
    assert client.delete(f"/api/v1/me/sessions/{mine}", headers=team.h("member")).status_code == 404


def test_export_and_delete_account(client: TestClient, team: Team) -> None:
    h = team.h("builder")
    r = client.get("/api/v1/me/export", headers=h)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["profile"]["email"] == "builder@test.local"
    assert "password" not in r.text.lower().replace("password_change", "")
    assert data["memberships"][0]["role"] == "builder"
    # 비밀번호·확인 글자가 틀리면 안 됨
    assert (
        client.post(
            "/api/v1/me/delete", json={"password": "x", "confirm": "탈퇴"}, headers=h
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/me/delete", json={"password": PASSWORD, "confirm": "no"}, headers=h
        ).status_code
        == 422
    )
    # 하나뿐인 소유자(다른 멤버 있음)는 막힌다
    r = client.post(
        "/api/v1/me/delete", json={"password": PASSWORD, "confirm": "탈퇴"}, headers=team.h("owner")
    )
    assert r.status_code == 409 and "소유권" in r.json()["detail"]["hint"]
    r = client.post("/api/v1/me/delete", json={"password": PASSWORD, "confirm": "탈퇴"}, headers=h)
    assert r.status_code == 200
    assert client.get("/api/v1/me", headers=h).status_code == 401
    bad = client.post(
        "/api/v1/auth/login", json={"email": "builder@test.local", "password": PASSWORD}
    )
    assert bad.status_code == 401
    members = client.get(f"/api/v1/workspaces/{team.ws}/members", headers=team.h("owner")).json()
    assert all(m["email"] != "builder@test.local" for m in members)


def test_totp_rfc6238_vector() -> None:
    # RFC 6238 부록 B(SHA1, 시각 59초) → 94287082의 뒤 6자리
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # noqa: S105 - "12345678901234567890"
    assert totp.totp(secret, at=59) == "287082"
    assert totp.verify(secret, "287082", at=59)
    assert not totp.verify(secret, "287083", at=59)
