"""쓸 수 있는 단계 제한."""

from typing import Any

from fastapi.testclient import TestClient

from api.tests.conftest import Team
from api.tests.test_builder import new_session


def _code_graph() -> dict[str, Any]:
    return {
        "version": 1,
        "nodes": [
            {
                "id": "n1",
                "type": "input",
                "data": {"fields": [{"key": "message", "type": "text", "required": True}]},
            },
            {"id": "n3", "type": "code", "data": {"label": "계산", "code": "result = {'a': 1}"}},
            {"id": "n2", "type": "output", "data": {"label": "결과", "template": "{{n3.a}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n3"},
            {"id": "e2", "source": "n3", "target": "n2"},
        ],
    }


def test_blocked_type_fails_validation_and_hides_from_builder(
    client: TestClient, team: Team
) -> None:
    app_id, _ = new_session(client, team, "제한")
    client.put(
        f"/api/v1/apps/{app_id}/draft", json={"graph": _code_graph()}, headers=team.h("builder")
    )
    url = f"/api/v1/workspaces/{team.ws}/node-policy"
    before = client.get(url, headers=team.h("admin")).json()
    assert before["blocked_types"] == []
    assert any(n["type"] == "code" for n in before["node_types"])
    assert client.post(
        f"/api/v1/apps/{app_id}/validate", json={}, headers=team.h("builder")
    ).json()["valid"]
    res = client.put(
        url,
        json={"blocked_types": ["code", "input", "output", "없는타입"]},
        headers=team.h("admin"),
    )
    assert res.status_code == 200 and res.json()["blocked_types"] == ["code"]
    v = client.post(f"/api/v1/apps/{app_id}/validate", json={}, headers=team.h("builder")).json()
    assert not v["valid"] and "막아 뒀어요" in v["errors"][0]["message"]
    assert v["errors"][0]["node_id"] == "n3"
    run = client.post(
        f"/api/v1/apps/{app_id}/runs", json={"input": {"message": "a"}}, headers=team.h("builder")
    )
    assert run.status_code == 422
    # 끈 단계는 막지 않는다
    g = _code_graph()
    g["nodes"][1]["disabled"] = True
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": g}, headers=team.h("builder"))
    assert client.post(
        f"/api/v1/apps/{app_id}/validate", json={}, headers=team.h("builder")
    ).json()["valid"]
    assert (
        client.put(url, json={"blocked_types": []}, headers=team.h("admin")).json()["blocked_types"]
        == []
    )


def test_policy_permissions_and_builder_list(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/node-policy"
    assert client.get(url, headers=team.h("builder")).status_code == 403
    assert (
        client.put(url, json={"blocked_types": ["code"]}, headers=team.h("builder")).status_code
        == 403
    )
    assert client.get(url).status_code == 401
    client.put(url, json={"blocked_types": ["code"]}, headers=team.h("owner"))
    from api.builder.tools import BuilderToolbox
    from api.db import SessionLocal
    from api.models import App

    app_id, _ = new_session(client, team, "빌더목록")
    with SessionLocal() as db:
        app = db.get(App, app_id)
        assert app is not None
        types = {
            n["type"]
            for n in BuilderToolbox(db, app, "u")
            .execute("list_available_nodes", {})
            .result["node_types"]
        }
    assert "code" not in types and "llm" in types
