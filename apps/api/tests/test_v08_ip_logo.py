"""v0.8 IP 접근 제한과 웹앱 로고: 허용 목록(IPv4·IPv6·CIDR), 프록시 헤더 위조, 모든 공개 경로 적용,
권한, 감사 기록, 로고 올리기·보여 주기."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.core.errors import AppError
from api.db import SessionLocal
from api.main import app as fastapi_app
from api.models import AuditLog
from api.services.ip_access import ip_allowed, normalize
from api.tests.conftest import Team
from api.tests.test_v08_share_meta import _deploy, _png, _upload

NGINX = ("172.18.0.5", 50000)  # 믿을 수 있는 프록시(사설 대역)


def _via_proxy() -> TestClient:
    return TestClient(fastapi_app, client=NGINX)


def _direct(ip: str) -> TestClient:
    return TestClient(fastapi_app, client=(ip, 50000))


def _set_ips(
    client: TestClient, team: Team, dep_id: str, ips: list[str], role: str = "builder"
) -> Any:
    return client.patch(
        f"/api/v1/deployments/{dep_id}", json={"allowed_ips": ips}, headers=team.h(role)
    )


# ---------------- 순수 함수 ----------------
def test_normalize_and_match() -> None:
    assert normalize([" 203.0.113.7 ", "203.0.113.7", "203.0.113.5/24", "2001:db8::/32", ""]) == [
        "203.0.113.7",
        "203.0.113.0/24",
        "2001:db8::/32",
    ]
    assert normalize(["10.0.0.1/32"]) == ["10.0.0.1"]
    for bad in ("abc", "300.1.1.1", "10.0.0.0/40"):
        with pytest.raises(AppError) as exc:
            normalize([bad])
        assert "올바른 IP" in exc.value.message
    assert ip_allowed("1.2.3.4", []) and ip_allowed("anything", [])  # 비어 있으면 제한 없음
    assert ip_allowed("203.0.113.9", ["203.0.113.0/24"])
    assert not ip_allowed("203.0.114.9", ["203.0.113.0/24"])
    assert ip_allowed("2001:db8::5", ["2001:db8::/32"])
    assert not ip_allowed("2001:db9::5", ["2001:db8::/32"])
    assert ip_allowed("::ffff:203.0.113.9", ["203.0.113.0/24"])  # IPv4로 들어온 IPv6 표기
    assert not ip_allowed("203.0.113.9", ["2001:db8::/32"])  # 종류가 다르면 안 맞음
    assert not ip_allowed("unknown", ["203.0.113.0/24"])  # 주소를 모르면 제한이 있을 때 거절
    assert len(normalize([f"10.0.0.{i}" for i in range(50)])) == 50
    with pytest.raises(AppError) as exc:
        normalize([f"10.0.0.{i}" for i in range(51)])
    assert "최대 50개" in exc.value.message


# ---------------- 모든 공개 경로 ----------------
def test_guard_on_every_public_endpoint(client: TestClient, team: Team) -> None:
    _app_id, dep_id, token = _deploy(client, team)
    r = _set_ips(client, team, dep_id, ["203.0.113.0/24"])
    assert r.status_code == 200 and r.json()["allowed_ips"] == ["203.0.113.0/24"]
    base = f"/api/v1/public/apps/{token}"
    ok_hdr = {"X-Forwarded-For": "203.0.113.7"}
    bad_hdr = {"X-Forwarded-For": "198.51.100.9"}
    c = _via_proxy()
    calls: list[tuple[str, str, dict[str, Any] | None]] = [
        ("GET", base, None),
        ("POST", f"{base}/chat", {"message": "안녕"}),
        ("POST", f"{base}/runs", {"input": {}}),
        ("GET", f"{base}/runs/none", None),
        ("GET", f"{base}/sessions/none/messages", None),
        ("POST", f"{base}/files", None),
        ("GET", f"{base}/widget.js", None),
    ]
    for method, url, body in calls:
        blocked = c.request(method, url, json=body, headers=bad_hdr)
        assert blocked.status_code == 403, (method, url, blocked.status_code)
        detail = blocked.json()["detail"]
        assert detail["message"] and detail["hint"]
        assert "203.0.113" not in blocked.text  # 허용 목록을 알려 주지 않는다
        allowed = c.request(method, url, json=body, headers=ok_hdr)
        assert allowed.status_code != 403, (method, url)
    assert c.get(base, headers=ok_hdr).status_code == 200


def test_proxy_spoofing_is_ignored(client: TestClient, team: Team) -> None:
    _app_id, dep_id, token = _deploy(client, team)
    _set_ips(client, team, dep_id, ["203.0.113.7"])
    url = f"/api/v1/public/apps/{token}"
    # 바깥에서 바로 온 요청이 헤더를 꾸며도 소용없다
    forged = _direct("198.51.100.1").get(url, headers={"X-Forwarded-For": "203.0.113.7"})
    assert forged.status_code == 403
    assert _direct("203.0.113.7").get(url).status_code == 200
    # 프록시를 거치면 프록시가 붙인 오른쪽(마지막) 주소를 쓴다: 앞쪽에 꾸민 값이 있어도 무시
    c = _via_proxy()
    assert c.get(url, headers={"X-Forwarded-For": "203.0.113.7, 198.51.100.1"}).status_code == 403
    assert c.get(url, headers={"X-Forwarded-For": "198.51.100.1, 203.0.113.7"}).status_code == 200


def test_ipv6_and_clearing(client: TestClient, team: Team) -> None:
    _app_id, dep_id, token = _deploy(client, team)
    _set_ips(client, team, dep_id, ["2001:db8::/32", "10.1.0.0/16"])
    url = f"/api/v1/public/apps/{token}"
    assert _direct("2001:db8::77").get(url).status_code == 200
    assert _direct("2001:db9::77").get(url).status_code == 403
    assert _direct("10.1.2.3").get(url).status_code == 200
    # 목록을 비우면 제한이 풀린다
    cleared = _set_ips(client, team, dep_id, [])
    assert cleared.status_code == 200 and cleared.json()["allowed_ips"] == []
    assert _direct("198.51.100.1").get(url).status_code == 200


def test_create_with_ips_and_invalid_input(client: TestClient, team: Team) -> None:
    app_id, dep_id, _token = _deploy(client, team)
    bad = _set_ips(client, team, dep_id, ["not-an-ip"])
    assert bad.status_code == 422
    assert "올바른 IP" in bad.json()["detail"]["message"] and bad.json()["detail"]["hint"]
    too_many = _set_ips(client, team, dep_id, [f"10.0.{i // 250}.{i % 250}" for i in range(60)])
    assert too_many.status_code == 422
    h = team.h("builder")
    made = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={"channel": "share_link", "access": "public", "allowed_ips": ["192.0.2.0/24"]},
        headers=h,
    )
    assert made.status_code == 201 and made.json()["allowed_ips"] == ["192.0.2.0/24"]
    listed = client.get(f"/api/v1/apps/{app_id}/deployments", headers=h).json()
    assert {tuple(d["allowed_ips"]) for d in listed} == {(), ("192.0.2.0/24",)}


def test_ips_permissions_and_audit(client: TestClient, team: Team) -> None:
    _app_id, dep_id, _token = _deploy(client, team)
    for role in ("operator", "member"):
        assert _set_ips(client, team, dep_id, ["192.0.2.1"], role=role).status_code == 403
    assert _set_ips(client, team, dep_id, ["192.0.2.1"], role="admin").status_code == 200
    with SessionLocal() as db:
        rows = list(db.scalars(select(AuditLog).where(AuditLog.action == "app.deploy_ips")))
    assert len(rows) == 1 and rows[0].meta == {"count": 1}
    # 같은 값을 다시 저장해도 기록은 늘지 않는다
    _set_ips(client, team, dep_id, ["192.0.2.1"])
    with SessionLocal() as db:
        assert (
            len(list(db.scalars(select(AuditLog).where(AuditLog.action == "app.deploy_ips")))) == 1
        )


def test_my_ip_uses_same_logic(client: TestClient, team: Team) -> None:
    assert client.get("/api/v1/me/ip").status_code == 401
    c = _via_proxy()
    r = c.get(
        "/api/v1/me/ip", headers={**team.h("member"), "X-Forwarded-For": "9.9.9.9, 203.0.113.44"}
    )
    assert r.status_code == 200 and r.json() == {"ip": "203.0.113.44"}


def test_restricted_app_not_leaked_in_preview(client: TestClient, team: Team) -> None:
    _app_id, dep_id, token = _deploy(client, team, name="사내 전용 앱")
    assert "사내 전용 앱" in client.get(f"/api/v1/public/share/{token}").text
    _set_ips(client, team, dep_id, ["192.0.2.0/24"])
    page = client.get(f"/api/v1/public/share/{token}").text
    assert "사내 전용 앱" not in page and "제니오" in page
    # 미리보기 그림은 IP 제한에서 빠진다(기본 그림이 나간다)
    img = _via_proxy().get(
        f"/api/v1/public/apps/{token}/share-image", headers={"X-Forwarded-For": "198.51.100.1"}
    )
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"


# ---------------- 웹앱 로고 ----------------
def test_logo_upload_and_serving(client: TestClient, team: Team) -> None:
    _app_id, dep_id, token = _deploy(client, team)
    url = f"/api/v1/public/apps/{token}/share-logo"
    assert client.get(url).status_code == 404  # 아직 없음
    logo = _upload(client, team, "logo.png", _png(8, 8), "image/png")
    r = client.patch(
        f"/api/v1/deployments/{dep_id}",
        json={"appearance": {"share_logo": logo}},
        headers=team.h("builder"),
    )
    assert r.status_code == 200 and r.json()["appearance"]["share_logo"] == logo
    got = client.get(url)
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    assert got.content == _png(8, 8) and got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["cache-control"].startswith("public")
    assert client.head(url).status_code == 200
    # 공개 앱 정보에도 로고 id가 들어 있다(화면이 주소를 만든다)
    assert client.get(f"/api/v1/public/apps/{token}").json()["appearance"]["share_logo"] == logo
    # IP 제한이 있으면 로고도 막는다
    _set_ips(client, team, dep_id, ["192.0.2.0/24"])
    assert _direct("198.51.100.1").get(url).status_code == 403


def test_logo_rejects_bad_files(client: TestClient, team: Team) -> None:
    _app_id, dep_id, _token = _deploy(client, team)
    pdf = _upload(client, team, "x.pdf", b"%PDF-1.4 x", "application/pdf")
    gif = _upload(client, team, "a.gif", b"GIF89a\x01\x00", "image/gif")
    big = _upload(client, team, "big.png", b"\x89PNG" + b"0" * (1024 * 1024 + 10), "image/png")
    for bad in (pdf, gif, big, "no-such-file"):
        r = client.patch(
            f"/api/v1/deployments/{dep_id}",
            json={"appearance": {"share_logo": bad}},
            headers=team.h("builder"),
        )
        assert r.status_code == 422, bad
        assert "로고" in r.json()["detail"]["message"] and r.json()["detail"]["hint"]
