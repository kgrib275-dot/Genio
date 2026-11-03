"""v0.4 자동 실행: 웹훅·예약·지금 실행·다시 실행·실패하면 다른 앱 실행(ADR 0008)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.db import SessionLocal
from api.models import AppTrigger, Run
from api.services.triggers import dispatch_schedules
from api.tests.conftest import ROLES, Team


def echo_graph(prefix: str = "받음") -> dict[str, Any]:
    return {
        "version": 1,
        "nodes": [
            {
                "id": "n1",
                "type": "input",
                "data": {"fields": [{"key": "message", "type": "text"}]},
            },
            {
                "id": "n2",
                "type": "output",
                "data": {"template": prefix + ": {{n1.message}} / {{input.source}}"},
            },
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
    }


FAIL_GRAPH: dict[str, Any] = {
    "version": 1,
    "nodes": [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "message", "type": "text"}]}},
        # 사설 IP는 막혀 있어(SSRF) 늘 실패한다
        {"id": "n2", "type": "http", "data": {"method": "GET", "url": "http://127.0.0.1:9/x"}},
        {"id": "n3", "type": "output", "data": {"template": "끝"}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ],
}


def make_app(
    client: TestClient, team: Team, graph: dict[str, Any], *, save: bool = True, name: str = "앱"
) -> str:
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": name}, headers=team.h("builder")
    )
    app_id: str = res.json()["id"]
    res = client.put(
        f"/api/v1/apps/{app_id}/draft", json={"graph": graph}, headers=team.h("builder")
    )
    assert res.status_code == 200, res.text
    if save:
        v = client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=team.h("builder"))
        assert v.status_code == 201, v.text
    return app_id


def add_trigger(
    client: TestClient,
    team: Team,
    app_id: str,
    kind: str,
    config: dict[str, Any],
    role: str = "builder",
) -> Any:
    return client.post(
        f"/api/v1/apps/{app_id}/triggers",
        json={"kind": kind, "config": config},
        headers=team.h(role),
    )


def hook_path(url: str) -> str:
    return url[url.index("/api/v1/hooks/") :]


def test_trigger_permissions(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, echo_graph())
    for role in ROLES:
        res = add_trigger(client, team, app_id, "webhook", {}, role)
        assert res.status_code == (201 if role in ("owner", "admin", "builder") else 403), role
    tid = add_trigger(client, team, app_id, "webhook", {}).json()["id"]
    for role in ROLES:
        res = client.get(f"/api/v1/apps/{app_id}/triggers", headers=team.h(role))
        assert res.status_code == (403 if role == "member" else 200), role
        if role == "operator":
            # 보기만 하는 사람에게는 웹훅 주소(비밀)를 보여 주지 않는다
            assert all(t["url"] is None for t in res.json())
        for path in ("rotate-token", "run-now"):
            r = client.post(f"/api/v1/triggers/{tid}/{path}", headers=team.h(role))
            if role in ("operator", "member"):
                assert r.status_code == 403
    assert client.delete(f"/api/v1/triggers/{tid}", headers=team.h("operator")).status_code == 403
    assert client.delete(f"/api/v1/triggers/{tid}", headers=team.h("builder")).status_code == 204


def test_webhook_async_sync_rotate_disable(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, echo_graph(), save=False)
    t = add_trigger(client, team, app_id, "webhook", {"mode": "async"}).json()
    assert t["kind"] == "webhook" and "/api/v1/hooks/" in t["url"] and t["name"] == "외부에서 받기"
    path = hook_path(t["url"])
    # 저장한 버전이 없으면 409
    nov = client.post(path, json={"message": "x"})
    assert nov.status_code == 409 and "버전 저장" in nov.json()["detail"]["hint"]
    client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=team.h("builder"))

    res = client.post(path + "?source=외부", json={"message": "안녕"})
    assert res.status_code == 202
    run = client.get(f"/api/v1/runs/{res.json()['run_id']}", headers=team.h("operator")).json()
    assert run["trigger"] == "webhook" and run["status"] == "succeeded"
    assert run["output"]["text"] == "받음: 안녕 / 외부"
    listed = client.get(f"/api/v1/apps/{app_id}/triggers", headers=team.h("builder")).json()
    assert listed[0]["last_run_id"] == run["id"] and listed[0]["last_status"] == "succeeded"

    # 결과까지 기다리기(sync), GET도 된다
    client.patch(
        f"/api/v1/triggers/{t['id']}", json={"config": {"mode": "sync"}}, headers=team.h("builder")
    )
    sync = client.get(path + "?message=쿼리")
    assert sync.status_code == 200
    body = sync.json()
    assert body["status"] == "succeeded" and body["output"]["text"].startswith("받음: 쿼리")
    # JSON이 아닌 본문(일반 글)은 body로 넘긴다, JSON이라고 해 놓고 틀리면 400
    assert (
        client.post(path, content=b"plain", headers={"content-type": "text/plain"}).status_code
        == 200
    )
    bad = client.post(path, content=b"{oops", headers={"content-type": "application/json"})
    assert bad.status_code == 400 and bad.json()["detail"]["hint"]

    # 주소 다시 만들기 → 옛 주소 막힘, 끄기 → 404
    new = client.post(f"/api/v1/triggers/{t['id']}/rotate-token", headers=team.h("builder")).json()
    assert new["url"] != t["url"]
    assert client.post(path, json={}).status_code == 404
    client.patch(f"/api/v1/triggers/{t['id']}", json={"enabled": False}, headers=team.h("builder"))
    assert client.post(hook_path(new["url"]), json={}).status_code == 404
    assert client.post("/api/v1/hooks/없는토큰", json={}).status_code == 404


def test_schedule_validation_and_dispatch(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, echo_graph("예약"))
    for cron in ("abc", "* * *", "0 25 * * *", "* * * * * *"):
        res = add_trigger(client, team, app_id, "schedule", {"cron": cron})
        assert res.status_code == 422, cron
        assert res.json()["detail"]["hint"]
    bad_tz = add_trigger(
        client, team, app_id, "schedule", {"cron": "0 9 * * *", "timezone": "Mars/Base"}
    )
    assert bad_tz.status_code == 422
    t = add_trigger(
        client,
        team,
        app_id,
        "schedule",
        {"cron": "0 9 * * 1-5", "input": {"message": "아침 요약", "source": "예약"}},
    ).json()
    assert t["config"]["timezone"] == "Asia/Seoul" and t["url"] is None
    nxt = datetime.fromisoformat(t["next_run_at"])
    assert nxt > datetime.now(UTC)
    # 서울 오전 9시 = UTC 0시
    assert nxt.astimezone(UTC).hour == 0 and nxt.weekday() < 5

    # 아직 때가 아니면 실행하지 않는다
    with SessionLocal() as db:
        assert dispatch_schedules(db) == []
    # 때가 지나면 실행하고 다음 시각으로 넘긴다
    with SessionLocal() as db:
        trig = db.get(AppTrigger, t["id"])
        assert trig is not None
        trig.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
        started = dispatch_schedules(db)
        assert len(started) == 1
        db.refresh(trig)
        assert trig.next_run_at is not None
        assert trig.next_run_at.replace(tzinfo=trig.next_run_at.tzinfo or UTC) > datetime.now(UTC)
    run = client.get(f"/api/v1/runs/{started[0]}", headers=team.h("operator")).json()
    assert run["trigger"] == "schedule" and run["output"]["text"] == "예약: 아침 요약 / 예약"

    # 꺼 두면 다음 시각이 없고 실행하지 않는다
    off = client.patch(
        f"/api/v1/triggers/{t['id']}", json={"enabled": False}, headers=team.h("builder")
    ).json()
    assert off["next_run_at"] is None
    # 지금 실행
    now_run = client.post(f"/api/v1/triggers/{t['id']}/run-now", headers=team.h("builder"))
    assert now_run.status_code == 201 and now_run.json()["trigger"] == "schedule"


def test_schedule_without_version_is_skipped(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, echo_graph(), save=False)
    t = add_trigger(client, team, app_id, "schedule", {"cron": "*/5 * * * *"}).json()
    with SessionLocal() as db:
        trig = db.get(AppTrigger, t["id"])
        assert trig is not None
        trig.next_run_at = datetime.now(UTC) - timedelta(seconds=5)
        db.commit()
        assert dispatch_schedules(db) == []
        db.refresh(trig)
        assert trig.last_status == "no_version" and trig.next_run_at is not None


def test_rerun(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, echo_graph())
    first = client.post(
        f"/api/v1/apps/{app_id}/runs",
        json={"input": {"message": "처음"}},
        headers=team.h("builder"),
    ).json()
    for role, code in (("operator", 403), ("member", 403)):
        assert (
            client.post(
                f"/api/v1/runs/{first['id']}/rerun", json={}, headers=team.h(role)
            ).status_code
            == code
        )
    same = client.post(f"/api/v1/runs/{first['id']}/rerun", json={}, headers=team.h("builder"))
    assert same.status_code == 201
    assert same.json()["trigger"] == "rerun" and same.json()["output"]["text"].startswith(
        "받음: 처음"
    )
    changed = client.post(
        f"/api/v1/runs/{first['id']}/rerun",
        json={"input": {"message": "고침"}},
        headers=team.h("builder"),
    ).json()
    assert changed["output"]["text"].startswith("받음: 고침")


def test_on_failure_runs_other_app(client: TestClient, team: Team) -> None:
    handler = make_app(client, team, echo_graph("실패 알림"), name="실패 처리")
    failing = make_app(client, team, FAIL_GRAPH, name="잘 깨지는 앱")
    res = client.patch(
        f"/api/v1/apps/{failing}/features",
        json={"on_failure": {"app_id": handler}},
        headers=team.h("builder"),
    )
    assert res.status_code == 200 and res.json()["features"]["on_failure"]["app_id"] == handler

    # 빌더 테스트 실행은 실패해도 부르지 않는다
    client.post(f"/api/v1/apps/{failing}/runs", json={"input": {}}, headers=team.h("builder"))
    with SessionLocal() as db:
        assert db.scalar(select(Run).where(Run.trigger == "on_failure")) is None

    hook = add_trigger(client, team, failing, "webhook", {}).json()
    res = client.post(hook_path(hook["url"]), json={"message": "주문"})
    failed = client.get(f"/api/v1/runs/{res.json()['run_id']}", headers=team.h("operator")).json()
    assert failed["status"] == "failed"
    with SessionLocal() as db:
        handled = list(db.scalars(select(Run).where(Run.trigger == "on_failure")))
        assert len(handled) == 1
        h = handled[0]
        assert h.app_id == handler and h.status == "succeeded"
        assert h.input["failed_app_name"] == "잘 깨지는 앱"
        assert h.input["run_id"] == failed["id"]
        assert h.input["input"] == {"message": "주문"}
        assert h.input["error"]


def test_on_failure_ignores_other_workspace_app(client: TestClient, team: Team) -> None:
    failing = make_app(client, team, FAIL_GRAPH)
    client.patch(
        f"/api/v1/apps/{failing}/features",
        json={"on_failure": {"app_id": "없는-앱"}},
        headers=team.h("builder"),
    )
    hook = add_trigger(client, team, failing, "webhook", {}).json()
    client.post(hook_path(hook["url"]), json={})
    with SessionLocal() as db:
        assert db.scalar(select(Run).where(Run.trigger == "on_failure")) is None
