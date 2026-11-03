"""워크플로우 앱 공유 화면: 입력 폼 → 실행 → 결과(기능 정의서 앱 유형)."""

from fastapi.testclient import TestClient

from api.tests.conftest import Team


def _form_app(client: TestClient, team: Team) -> tuple[str, str]:
    h = team.h("builder")
    app = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "견적", "type": "workflow"}, headers=h
    ).json()
    client.post(f"/api/v1/apps/{app['id']}/versions", json={}, headers=h)
    dep = client.post(
        f"/api/v1/apps/{app['id']}/deployments",
        json={"channel": "share_link", "access": "public"},
        headers=h,
    ).json()
    return app["id"], dep["public_token"]


def test_form_run_and_result(client: TestClient, team: Team) -> None:
    app_id, token = _form_app(client, team)
    started = client.post(f"/api/v1/public/apps/{token}/runs", json={"input": {"message": "안녕"}})
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    res = client.get(f"/api/v1/public/apps/{token}/runs/{run_id}").json()
    # 테스트에서는 큐가 바로 실행한다
    assert res["status"] == "succeeded" and res["text"] == "안녕"
    # 내부 값(단계 입력·출력)은 주지 않는다
    assert set(res) <= {"run_id", "status", "text", "error"}

    # 다른 앱의 실행이나 공유 화면이 아닌 실행은 볼 수 없다
    _, other_token = _form_app(client, team)
    assert client.get(f"/api/v1/public/apps/{other_token}/runs/{run_id}").status_code == 404
    test_run = client.post(
        f"/api/v1/apps/{app_id}/runs", json={"input": {"message": "x"}}, headers=team.h("builder")
    ).json()
    assert client.get(f"/api/v1/public/apps/{token}/runs/{test_run['id']}").status_code == 404

    # 너무 긴 입력은 거절
    big = client.post(
        f"/api/v1/public/apps/{token}/runs", json={"input": {"message": "가" * 30000}}
    )
    assert big.status_code == 413
