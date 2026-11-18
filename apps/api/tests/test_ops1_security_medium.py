"""운영 준비 1차 B1(보통): F3 DNS 재바인딩·리다이렉트 헤더, F4 연결 정보 허용 주소, F5 링크 주소,
F6 AI 연결 주소, F7 압축 폭탄, F8 공개 앱 하루 업로드 총량."""

import asyncio
import io
import socket
import zipfile
from typing import Any

import httpx
import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from starlette.requests import Request

from api.config import get_settings
from api.connectors import database, http_auth
from api.core.errors import AppError
from api.db import SessionLocal
from api.engine import safe_http
from api.models import App, Workspace
from api.routers.common import public_origin
from api.services import batches, files, knowledge
from api.services.zipguard import ZipBombError, check_zip
from api.tests.conftest import Team
from nodes import NodeError

PUBLIC_IP = "93.184.216.34"


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """호스트 이름 → IP 목록(가짜 DNS)."""
    table: dict[str, list[str]] = {}

    def fake(host: str, port: Any, *a: Any, **k: Any) -> list[Any]:
        ips = table.get(host, [host])
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0)) for ip in ips]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return table


# ---------------- F3 ----------------
def test_prepare_pins_checked_ip(dns: dict[str, list[str]]) -> None:
    dns["api.example.com"] = [PUBLIC_IP]
    url, headers, ext, host = safe_http._prepare(
        "https://api.example.com:8443/v1/x?q=1", {"Authorization": "Bearer t"}, None
    )
    assert url == f"https://{PUBLIC_IP}:8443/v1/x?q=1"
    assert headers["Host"] == "api.example.com:8443" and headers["Authorization"] == "Bearer t"
    assert ext == {"sni_hostname": "api.example.com"} and host == "api.example.com"


def test_prepare_blocks_private_answer(dns: dict[str, list[str]]) -> None:
    dns["rebind.example.com"] = [PUBLIC_IP, "127.0.0.1"]
    with pytest.raises(NodeError, match="내부"):
        safe_http._prepare("http://rebind.example.com/", {}, None)


def test_redirect_to_other_host_drops_auth(
    dns: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    dns["a.example.com"] = [PUBLIC_IP]
    dns["b.example.net"] = ["93.184.216.35"]
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.headers["host"] == "a.example.com":
            return httpx.Response(302, headers={"location": "http://b.example.net/next"})
        return httpx.Response(200, json={"ok": True})

    real = httpx.Client

    def client(**kw: Any) -> httpx.Client:
        return real(transport=httpx.MockTransport(handler), follow_redirects=False)

    monkeypatch.setattr(safe_http.httpx, "Client", client)
    out = safe_http.request(
        "GET",
        "http://a.example.com/start",
        headers={"Authorization": "Bearer secret", "X-Api-Key": "k", "Accept": "application/json"},
    )
    assert out["status"] == 200
    first, second = seen
    # 검사한 IP로 직접 연결하고, 원래 이름은 Host로 보낸다
    assert first.url.host == PUBLIC_IP and first.headers["authorization"] == "Bearer secret"
    assert second.url.host == "93.184.216.35" and second.headers["host"] == "b.example.net"
    assert "authorization" not in second.headers and "x-api-key" not in second.headers
    assert second.headers["accept"] == "application/json"


def test_same_host_redirect_keeps_auth(dns: dict[str, list[str]]) -> None:
    hdrs = {"Authorization": "x"}
    assert safe_http._next_headers(hdrs, "a.example.com", "https://A.example.com/b") == hdrs
    assert safe_http._next_headers(hdrs, "a.example.com", "https://evil.example.com/") == {}


def test_db_connects_to_checked_ip(dns: dict[str, list[str]]) -> None:
    dns["db.example.com"] = [PUBLIC_IP]
    assert database.check_host("db.example.com", 5432, []) == PUBLIC_IP
    assert database.check_host("10.0.0.5", 5432, ["10.0.0.5"]) is None


# ---------------- F4 ----------------
def test_parse_hosts() -> None:
    assert http_auth.parse_hosts(" api.example.com, *.foo.kr https://x.io/path ") == [
        "api.example.com",
        "foo.kr",
        "x.io",
    ]
    assert http_auth.parse_hosts(None) == []


def test_credential_destination_check() -> None:
    http_auth.check_destination({}, "https://anywhere.example/")  # 비우면 예전처럼
    s = {"allowed_hosts": "api.example.com, foo.kr"}
    http_auth.check_destination(s, "https://api.example.com/v1")
    http_auth.check_destination(s, "https://x.foo.kr/v1")
    for bad in ("https://evil.com/?api.example.com", "https://api.example.com.evil.com/", None):
        with pytest.raises(NodeError, match="쓸 수 없어요"):
            http_auth.check_destination(s, bad)


def test_preview_refuses_credential_to_other_host(
    client: TestClient, team: Team, dns: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.tests.conftest import install

    install(client, team, "http_credentials")
    cid = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={
            "connector_key": "http_credentials",
            "name": "키",
            "secrets": {"token": "tok-1234", "allowed_hosts": "api.example.com"},
        },
        headers=team.h("admin"),
    ).json()["id"]
    sent: list[dict[str, str]] = []
    monkeypatch.setattr(
        safe_http,
        "request",
        lambda m, u, headers=None, body=None, **k: (
            sent.append(headers or {}) or {"status": 200, "body": {}, "headers": {}}
        ),
    )
    url = f"/api/v1/workspaces/{team.ws}/http/preview"
    auth = {"type": "bearer", "credential_id": cid}
    bad = client.post(
        url,
        json={"method": "GET", "url": "https://evil.example/", "auth": auth},
        headers=team.h("builder"),
    )
    assert bad.status_code == 422 and "쓸 수 없어요" in bad.text and not sent
    ok = client.post(
        url,
        json={"method": "GET", "url": "https://api.example.com/x", "auth": auth},
        headers=team.h("builder"),
    )
    assert ok.status_code == 200, ok.text
    assert sent[0]["Authorization"] == "Bearer tok-1234"


# ---------------- F5 ----------------
def _req(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
    )


def test_public_origin_ignores_untrusted(monkeypatch: pytest.MonkeyPatch) -> None:
    st = get_settings()
    monkeypatch.setattr(st, "genio_public_web_url", "http://localhost:5190")
    monkeypatch.setattr(st, "genio_cors_origins", "https://partner.example.com")
    assert public_origin(_req({"origin": "https://evil.example"})) == "http://localhost:5190"
    assert public_origin(_req({"x-forwarded-host": "evil.example"})) == "http://localhost:5190"
    assert public_origin(_req({"origin": "http://localhost:5173"})) == "http://localhost:5173"
    assert (
        public_origin(_req({"origin": "https://partner.example.com"}))
        == "https://partner.example.com"
    )
    monkeypatch.setattr(st, "genio_public_web_url", "https://genio.example.com")
    assert public_origin(_req({"origin": "http://localhost:5173"})) == "https://genio.example.com"


def test_reset_link_not_poisoned(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.services import mailer

    st = get_settings()
    monkeypatch.setattr(st, "genio_public_web_url", "http://localhost:5190")
    box: list[dict[str, str]] = []
    monkeypatch.setattr(mailer, "OUTBOX", box)
    r = client.put(
        "/api/v1/admin/system/mail",
        json={
            "host": "smtp.example.com",
            "port": 587,
            "username": "noreply",
            "password": "smtp-secret-xyz9",
            "from_addr": "noreply@example.com",
            "security": "starttls",
        },
        headers=team.h("owner"),
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/auth/password/forgot",
        json={"email": "member@test.local"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 200, r.text
    assert box, "재설정 메일이 나가야 한다"
    text = str(box)
    assert "evil.example" not in text and "http://localhost:5190/reset-password" in text


# ---------------- F6 ----------------
def test_ai_base_url_private_blocked(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/llm-providers"
    body = {
        "provider": "openai-compatible",
        "label": "사내",
        "api_key": "sk-test-123",
        "base_url": "http://10.1.2.3:8000/v1",
        "default_model": "m",
    }
    r = client.post(url, json=body, headers=team.h("owner"))
    assert r.status_code == 422 and "허용할 내부 주소" in r.text
    r = client.post(f"{url}/test", json=body, headers=team.h("owner"))
    assert r.status_code == 422
    with SessionLocal() as db:
        ws = db.get(Workspace, team.ws)
        assert ws is not None
        ws.settings = {**(ws.settings or {}), "allow_private_hosts": ["10.1.2.3"]}
        db.commit()
    r = client.post(url, json=body, headers=team.h("owner"))
    assert r.status_code == 200, r.text


# ---------------- F7 ----------------
def _bomb(size: int = 4 * 1024 * 1024, name: str = "xl/worksheets/sheet1.xml") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(name, b"0" * size)
    return buf.getvalue()


def test_zip_guard() -> None:
    with pytest.raises(ZipBombError, match="압축 폭탄"):
        check_zip(_bomb())
    check_zip(b"not a zip")  # zip이 아니면 여기서는 넘긴다
    small = io.BytesIO()
    with zipfile.ZipFile(small, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("a.txt", "hello world " * 10)
    check_zip(small.getvalue())
    many = io.BytesIO()
    with zipfile.ZipFile(many, "w") as z:
        for i in range(5001):
            z.writestr(f"f{i}", "")
    with pytest.raises(ZipBombError, match="항목"):
        check_zip(many.getvalue())


def test_bomb_rejected_by_parsers() -> None:
    bomb = _bomb()
    with pytest.raises(ValueError, match="압축 폭탄"):
        knowledge.extract_text(bomb, "a.xlsx", "")
    with pytest.raises(AppError) as e:
        batches._read_table("a.xlsx", bomb)
    assert e.value.status == 422


# ---------------- F8 ----------------
def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(io.BytesIO(data), filename=name)


def test_public_daily_upload_cap(team: Team) -> None:
    with SessionLocal() as db:
        a = App(workspace_id=team.ws, name="공개", slug="pub", type="chat", draft_graph={})
        db.add(a)
        db.commit()
        cap = 1024 * 1024
        data = b"x" * (600 * 1024)
        asyncio.run(
            files.save_upload(
                db, team.ws, _upload("a.txt", data), app_id=a.id, daily_app_cap_bytes=cap
            )
        )
        with pytest.raises(AppError) as e:
            asyncio.run(
                files.save_upload(
                    db, team.ws, _upload("b.txt", data), app_id=a.id, daily_app_cap_bytes=cap
                )
            )
        assert e.value.status == 429
        # 다른 앱이나 워크스페이스 화면에서 올리는 것은 상관없다
        asyncio.run(files.save_upload(db, team.ws, _upload("c.txt", data)))
