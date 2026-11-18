"""챗 허브: 내가 쓸 수 있는 배포된 앱 목록."""

from typing import Any

from fastapi.testclient import TestClient

from api.tests.conftest import Team
from api.tests.test_builder import new_session
from api.tests.test_ops2_evals import _graph


def _deploy(client: TestClient, team: Team, name: str, body: dict[str, Any]) -> tuple[str, str]:
    app_id, _ = new_session(client, team, name)
    client.put(
        f"/api/v1/apps/{app_id}/draft", json={"graph": _graph("답")}, headers=team.h("builder")
    )
    client.post(f"/api/v1/apps/{app_id}/versions", json={"note": "v1"}, headers=team.h("builder"))
    dep = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={"channel": "share_link", **body},
        headers=team.h("builder"),
    )
    assert dep.status_code == 201, dep.text
    return app_id, str(dep.json()["public_token"])


def test_hub_lists_only_usable_apps(client: TestClient, team: Team) -> None:
    a, tok_a = _deploy(client, team, "가 상담봇", {"access": "workspace"})
    b, _ = _deploy(client, team, "나 비밀봇", {"access": "roles", "allowed_roles": ["admin"]})
    new_session(client, team, "다 미배포")
    url = f"/api/v1/workspaces/{team.ws}/hub"
    member = client.get(url, headers=team.h("member")).json()
    assert [x["app_id"] for x in member] == [a]
    assert member[0]["token"] == tok_a and member[0]["name"] == "가 상담봇"
    admin = client.get(url, headers=team.h("admin")).json()
    assert {x["app_id"] for x in admin} == {a, b}
    assert [x["name"] for x in admin] == sorted(x["name"] for x in admin)


def test_hub_requires_login(client: TestClient, team: Team) -> None:
    assert client.get(f"/api/v1/workspaces/{team.ws}/hub").status_code == 401
