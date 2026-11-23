"""외부 카탈로그(ADR 0020): MCP 레지스트리 검색·설치, 회사별 켜기, 권한, 기록."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.db import SessionLocal
from api.engine import safe_http
from api.models import AuditLog
from api.services import catalog
from api.tests.conftest import Team

REGISTRY_BODY = {
    "servers": [
        {
            "server": {
                "name": "io.example/notes",
                "description": "메모 서비스",
                "version": "1.2.0",
                "repository": {"url": "https://github.com/example/notes", "source": "github"},
                "remotes": [
                    {
                        "type": "streamable-http",
                        "url": "https://mcp.example.com/mcp",
                        "headers": [
                            {"name": "X-API-Key", "isRequired": True, "isSecret": True},
                        ],
                    }
                ],
            },
            "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active"}},
        },
        {
            "server": {
                "name": "io.example/local-only",
                "description": "내 컴퓨터에서만 도는 서버",
                "version": "0.1.0",
                "packages": [{"registryType": "npm", "identifier": "x"}],
            },
        },
        {
            "server": {
                "name": "io.example/templated",
                "description": "주소에 자리표시자",
                "version": "1.0.0",
                "remotes": [{"type": "streamable-http", "url": "https://{tenant}.example.com/mcp"}],
            },
        },
        {
            "server": {"name": "io.example/old", "description": "삭제됨", "version": "1"},
            "_meta": {"io.modelcontextprotocol.registry/official": {"status": "deleted"}},
        },
    ],
    "metadata": {"nextCursor": "io.example/next:1", "count": 4},
}


@pytest.fixture(autouse=True)
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def fake(method: str, url: str, **_: Any) -> dict[str, Any]:
        calls.append(url)
        return {"status": 200, "body": REGISTRY_BODY, "headers": {}}

    monkeypatch.setattr(safe_http, "request", fake)
    catalog._cache.clear()
    return calls


def _on(client: TestClient, team: Team) -> None:
    r = client.put(
        f"/api/v1/workspaces/{team.ws}/security",
        json={"external_catalog": True},
        headers=team.h("admin"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["external_catalog"] is True


def test_catalog_is_off_by_default(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/catalog/mcp"
    r = client.get(url, headers=team.h("builder"))
    assert r.status_code == 403
    assert "켜" in r.json()["detail"]["message"] + r.json()["detail"]["hint"]
    r = client.post(f"{url}/install", json={"name": "io.example/notes"}, headers=team.h("admin"))
    assert r.status_code == 403


def test_catalog_search_roles_and_filtering(client: TestClient, team: Team) -> None:
    _on(client, team)
    url = f"/api/v1/workspaces/{team.ws}/catalog/mcp?q=notes"
    assert client.get(url, headers=team.h("member")).status_code == 403
    assert client.get(url, headers=team.h("operator")).status_code == 403
    r = client.get(url, headers=team.h("builder"))
    assert r.status_code == 200, r.text
    items = {i["name"]: i for i in r.json()["items"]}
    assert "io.example/old" not in items  # 삭제된 항목은 숨김
    assert items["io.example/notes"]["installable"] is True
    assert items["io.example/local-only"]["installable"] is False
    assert items["io.example/templated"]["installable"] is False  # 자리표시자 주소는 설치 불가
    assert r.json()["items"][0]["name"] == "io.example/notes"  # 설치 가능한 것이 앞
    assert r.json()["next_cursor"] == "io.example/next:1"
    with SessionLocal() as db:
        n = db.query(AuditLog).filter(AuditLog.action == "catalog.search").count()
    assert n == 1


def test_catalog_search_is_cached(client: TestClient, team: Team, fake_registry: list[str]) -> None:
    _on(client, team)
    url = f"/api/v1/workspaces/{team.ws}/catalog/mcp?q=notes"
    client.get(url, headers=team.h("builder"))
    client.get(url, headers=team.h("builder"))
    assert len(fake_registry) == 1


def test_catalog_registry_failure_message(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    _on(client, team)

    def boom(*_: Any, **__: Any) -> dict[str, Any]:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(safe_http, "request", boom)
    r = client.get(f"/api/v1/workspaces/{team.ws}/catalog/mcp?q=zzz", headers=team.h("builder"))
    assert r.status_code == 502
    assert "secret" not in r.text


def test_catalog_install_creates_connection(client: TestClient, team: Team) -> None:
    _on(client, team)
    url = f"/api/v1/workspaces/{team.ws}/catalog/mcp/install"
    # 제작자는 연결 정보를 만들 수 없다
    r = client.post(url, json={"name": "io.example/notes"}, headers=team.h("builder"))
    assert r.status_code == 403
    r = client.post(
        url,
        json={"name": "io.example/notes", "token": "tok-123"},
        headers=team.h("admin"),
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["host"] == "mcp.example.com"
    assert out["has_token"] is True
    assert out["source"] == "io.example/notes"
    assert "tok-123" not in r.text
    listed = client.get(
        f"/api/v1/workspaces/{team.ws}/mcp/servers", headers=team.h("builder")
    ).json()
    assert [s["host"] for s in listed] == ["mcp.example.com"]
    with SessionLocal() as db:
        row = db.query(AuditLog).filter(AuditLog.action == "catalog.install").one()
    assert row.meta["name"] == "io.example/notes"
    assert "tok-123" not in str(row.meta)


def test_catalog_install_rejects_unknown_or_not_installable(client: TestClient, team: Team) -> None:
    _on(client, team)
    url = f"/api/v1/workspaces/{team.ws}/catalog/mcp/install"
    for name in ("io.example/local-only", "io.example/templated", "io.example/missing"):
        r = client.post(url, json={"name": name}, headers=team.h("admin"))
        assert r.status_code == 404, name


def test_catalog_toggle_is_admin_only(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/security"
    for role in ("builder", "operator", "member"):
        r = client.put(url, json={"external_catalog": True}, headers=team.h(role))
        assert r.status_code == 403, role
    assert client.get(url, headers=team.h("admin")).json()["external_catalog"] is False
