"""이번 주 새로 나온 것(트렌드): 하루 한 번 모아 저장, 화면은 저장본을 읽는다."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.core import ratelimit
from api.engine import safe_http
from api.services import catalog, trends
from api.tests.conftest import Team
from nodes import NodeError

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def _mcp(name: str, hours_ago: int, remote: bool = True, latest: bool = True) -> dict[str, Any]:
    stamp = (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    server: dict[str, Any] = {"name": name, "description": f"{name} 설명", "version": "1.0.0"}
    if remote:
        server["remotes"] = [
            {"type": "streamable-http", "url": f"https://{name.split('/')[-1]}.example.com/mcp"}
        ]
    return {
        "server": server,
        "_meta": {
            "io.modelcontextprotocol.registry/official": {
                "status": "active",
                "isLatest": latest,
                "updatedAt": stamp,
                "publishedAt": stamp,
            }
        },
    }


def _wf(i: int, views: int, price: int | None = None) -> dict[str, Any]:
    return {
        "id": i,
        "name": f"템플릿 {i}",
        "description": "설명",
        "totalViews": views,
        "price": price,
        "user": {"username": "maker"},
        "nodes": [{"displayName": "Slack"}],
        "createdAt": "2026-11-20",
    }


@pytest.fixture(autouse=True)
def fake_sources(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"calls": [], "fail_mcp": False, "fail_n8n": False}

    def fake(method: str, url: str, **_: Any) -> dict[str, Any]:
        state["calls"].append(url)
        if "registry.modelcontextprotocol.io" in url:
            if state["fail_mcp"]:
                raise NodeError("레지스트리 오류")
            assert "updated_since=" in url
            body = {
                "servers": [
                    _mcp("io.a/fresh", 2),
                    _mcp("io.b/older", 100),
                    _mcp("io.c/local-only", 3, remote=False),
                    _mcp("io.d/not-latest", 1, latest=False),
                ],
                "metadata": {},
            }
            return {"status": 200, "body": body, "headers": {}}
        if state["fail_n8n"]:
            raise NodeError("n8n 오류")
        ws = [_wf(1, 900), _wf(2, 10), _wf(3, 50, price=9)]
        return {"status": 200, "body": {"totalWorkflows": 3, "workflows": ws}, "headers": {}}

    monkeypatch.setattr(safe_http, "request", fake)
    trends._memory.clear()
    catalog._n8n_cache.clear()
    return state


def _on(client: TestClient, team: Team) -> None:
    r = client.put(
        f"/api/v1/workspaces/{team.ws}/security",
        json={"external_catalog": True},
        headers=team.h("admin"),
    )
    assert r.status_code == 200, r.text


def test_refresh_collects_installable_new_services_and_templates() -> None:
    data = trends.refresh(now=NOW)
    names = [i["name"] for i in data["mcp_new"]]
    assert names == ["io.a/fresh", "io.b/older"]  # 최근 갱신순, 바로 연결 가능한 것만, 옛 판 제외
    assert data["mcp_new_total"] == 3  # 옛 판(isLatest=false)은 세지 않는다
    assert data["mcp_new_today"] == 1  # 24시간 안에 갱신된 것
    assert [i["id"] for i in data["n8n_new"]] == [1, 2] * 2  # 유료(3)는 숨김, 두 쪽 합침
    assert data["errors"] == []
    assert trends._load() is not None


def test_partial_failure_keeps_other_lists_and_previous_data(fake_sources: dict[str, Any]) -> None:
    first = trends.refresh(now=NOW)
    fake_sources["fail_mcp"] = True
    second = trends.refresh(now=NOW + timedelta(days=1))
    assert second["errors"] and "MCP" in second["errors"][0]
    assert second["mcp_new"] == first["mcp_new"]  # 못 가져오면 어제 목록을 그대로 둔다
    assert second["n8n_new"]  # n8n은 새로 받아 둔다
    fake_sources["fail_n8n"] = True
    third = trends.refresh(now=NOW + timedelta(days=2))
    assert (
        third["mcp_new"] == first["mcp_new"] or third == second
    )  # 전부 실패해도 저장본은 지워지지 않는다
    assert trends._load() is not None


def test_get_uses_saved_copy_until_it_is_old(
    monkeypatch: pytest.MonkeyPatch, fake_sources: dict[str, Any]
) -> None:
    ratelimit.reset()
    first = trends.get()
    n = len(fake_sources["calls"])
    assert first["mcp_new"] and n > 0
    trends.get()
    assert len(fake_sources["calls"]) == n  # 저장본이 신선하면 다시 부르지 않는다
    # 36시간 지난 저장본이면 새로 만든다(5분 제한이 풀린 뒤)
    old = dict(trends._memory)
    old["updated_at"] = (datetime.now(UTC) - timedelta(hours=40)).isoformat()
    trends._memory.clear()
    trends._memory.update(old)
    monkeypatch.setattr(ratelimit, "allow", lambda *a, **k: True)
    trends.get()
    assert len(fake_sources["calls"]) > n


def test_trends_endpoint_is_off_by_default_and_role_gated(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/catalog/trends"
    assert client.get(url, headers=team.h("builder")).status_code == 403  # 기본 꺼짐
    _on(client, team)
    assert client.get(url, headers=team.h("member")).status_code == 403
    r = client.get(url, headers=team.h("builder"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mcp_new"] and body["n8n_popular"] and "updated_at" in body
    assert all(i["installable"] for i in body["mcp_new"])
