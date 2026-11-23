"""n8n 템플릿 가져오기(ADR 0020 2단계): 변환 규칙, 검색·가져오기 API, 권한·기록."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.core.errors import AppError
from api.db import SessionLocal
from api.engine import safe_http
from api.models import App, AuditLog
from api.services import catalog, n8n_import
from api.tests.conftest import Team

WORKFLOW: dict[str, Any] = {
    "name": "슬랙 알림",
    "nodes": [
        {
            "id": "1",
            "name": "Webhook",
            "type": "n8n-nodes-base.webhook",
            "position": [100, 100],
            "parameters": {},
        },
        {
            "id": "2",
            "name": "날씨 조회",
            "type": "n8n-nodes-base.httpRequest",
            "position": [300, 100],
            "parameters": {
                "method": "post",
                "url": "=https://api.example.com/{{ $json.city }}/weather",
                "sendHeaders": True,
                "headerParameters": {"parameters": [{"name": "X-Key", "value": "abc"}]},
                "authentication": "genericCredentialType",
            },
            "credentials": {"httpHeaderAuth": {"id": "9", "name": "내 키"}},
        },
        {
            "id": "3",
            "name": "Code",
            "type": "n8n-nodes-base.code",
            "position": [500, 100],
            "parameters": {"jsCode": "return [];"},
        },
        {
            "id": "4",
            "name": "Slack",
            "type": "n8n-nodes-base.slack",
            "position": [700, 100],
            "parameters": {},
            "credentials": {"slackApi": {"id": "1", "name": "slack"}},
        },
        {
            "id": "5",
            "name": "메모",
            "type": "n8n-nodes-base.stickyNote",
            "position": [0, 300],
            "parameters": {"content": "설명 메모"},
        },
    ],
    "connections": {
        "Webhook": {"main": [[{"node": "날씨 조회", "type": "main", "index": 0}]]},
        "날씨 조회": {"main": [[{"node": "Code", "type": "main", "index": 0}]]},
        "Code": {"main": [[{"node": "Slack", "type": "main", "index": 0}]]},
    },
}

SEARCH = {
    "totalWorkflows": 25,
    "workflows": [
        {
            "id": 101,
            "name": "날씨 알림",
            "description": "## 제목\n**굵게** [링크](http://x.y) <b>태그</b>",
            "totalViews": 50,
            "price": None,
            "user": {"username": "maker", "name": "Maker"},
            "nodes": [
                {"displayName": "Webhook"},
                {"displayName": "Slack"},
                {"displayName": "Slack"},
            ],
            "createdAt": "2025-01-01",
        },
        {"id": 102, "name": "유료", "price": 10, "nodes": [], "user": {}},
    ],
}


def test_convert_maps_safely_and_reports() -> None:
    conv = n8n_import.convert(
        {"workflow": {"workflow": WORKFLOW}}, source="n8n 템플릿 #1(a, https://n8n.io/workflows/1)"
    )
    nodes = {n["data"]["label"]: n for n in conv.graph["nodes"]}
    assert nodes["Webhook"]["type"] == "input" and nodes["Webhook"]["id"] == "n1"
    http = nodes["날씨 조회"]
    assert http["type"] == "http" and http["data"]["method"] == "POST"
    # n8n 식은 비워진다(깨진 참조를 남기지 않는다)
    assert "{{" not in http["data"]["url"] and "$json" not in http["data"]["url"]
    assert http["data"]["headers"] == {"X-Key": "abc"}
    # 코드·앱 연동은 꺼 둔 자리 표시
    for label in ("Code", "Slack"):
        assert nodes[label]["type"] == "template" and nodes[label]["disabled"] is True
    assert "return []" not in str(conv.graph)  # 코드는 가져오지 않는다
    assert len(conv.graph["edges"]) == 3
    assert conv.graph["notes"][0]["text"] == "설명 메모"
    rep = conv.report.dump()
    assert rep["stats"]["unsupported"] == 2
    assert any("slackApi" in a["message"] for a in rep["needs_attention"])
    assert any(
        "httpHeaderAuth" in a["message"] or "인증" in a["message"] for a in rep["needs_attention"]
    )
    assert any("식 1곳" in w for w in rep["warnings"])
    assert any("출처" in w for w in rep["warnings"])


def test_convert_without_trigger_adds_input_and_rejects_bad_files() -> None:
    conv = n8n_import.convert({"nodes": [WORKFLOW["nodes"][2]], "connections": {}})
    assert conv.graph["nodes"][0]["type"] == "input"
    bad_files: list[Any] = [{}, {"foo": 1}, {"nodes": [], "connections": {}}, "x"]
    for bad in bad_files:
        with pytest.raises(AppError):
            n8n_import.convert(bad)


@pytest.fixture(autouse=True)
def fake_n8n(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def fake(method: str, url: str, **_: Any) -> dict[str, Any]:
        calls.append(url)
        if "/search" in url:
            return {"status": 200, "body": SEARCH, "headers": {}}
        if url.endswith("/workflows/101"):
            return {
                "status": 200,
                "body": {
                    "workflow": {
                        "name": "날씨 알림",
                        "description": "설명",
                        "user": {"username": "maker"},
                        "workflow": WORKFLOW,
                    }
                },
                "headers": {},
            }
        if url.endswith("/workflows/102"):
            return {
                "status": 200,
                "body": {"workflow": {"name": "유료", "price": 5}},
                "headers": {},
            }
        return {"status": 404, "body": None, "headers": {}}

    monkeypatch.setattr(safe_http, "request", fake)
    catalog._n8n_cache.clear()
    return calls


def _on(client: TestClient, team: Team) -> None:
    r = client.put(
        f"/api/v1/workspaces/{team.ws}/security",
        json={"external_catalog": True},
        headers=team.h("admin"),
    )
    assert r.status_code == 200, r.text


def test_n8n_search_and_import_flow(client: TestClient, team: Team) -> None:
    base = f"/api/v1/workspaces/{team.ws}/catalog/n8n"
    assert client.get(base, headers=team.h("builder")).status_code == 403  # 기본 꺼짐
    _on(client, team)
    assert client.get(base, headers=team.h("member")).status_code == 403
    r = client.get(f"{base}?q=weather", headers=team.h("builder"))
    assert r.status_code == 200, r.text
    out = r.json()
    assert [i["id"] for i in out["items"]] == [101]  # 유료는 숨김
    item = out["items"][0]
    assert item["services"] == ["Webhook", "Slack"]
    assert "<" not in item["description"] and "**" not in item["description"]
    assert out["has_more"] is True

    imp = f"{base}/import"
    assert client.post(imp, json={"id": 101}, headers=team.h("member")).status_code == 403
    r = client.post(imp, json={"id": 101}, headers=team.h("builder"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["app"]["status"] == "draft"
    assert body["report"]["stats"]["unsupported"] == 2
    with SessionLocal() as db:
        assert db.query(App).filter(App.name == "날씨 알림").count() == 1
        log = db.query(AuditLog).filter(AuditLog.action == "catalog.import_n8n").one()
    assert log.meta["template_id"] == 101

    assert client.post(imp, json={"id": 102}, headers=team.h("builder")).status_code == 403
    assert client.post(imp, json={"id": 999}, headers=team.h("builder")).status_code == 502
