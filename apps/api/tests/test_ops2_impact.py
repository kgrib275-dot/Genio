"""효과 리포트(절약 시간 추정)."""

from typing import Any

from fastapi.testclient import TestClient

from api.services import app_config
from api.tests.conftest import Team
from api.tests.test_builder import new_session
from api.tests.test_v05_builder import FIXED_CODE, code_graph


def test_feature_clamps_minutes() -> None:
    assert app_config.merged_features({})["time_saved"] == {"minutes_per_run": 0}
    assert app_config.patch_features({}, {"time_saved": {"minutes_per_run": 15}})["time_saved"] == {
        "minutes_per_run": 15
    }
    assert app_config.patch_features({}, {"time_saved": {"minutes_per_run": -5}})["time_saved"] == {
        "minutes_per_run": 0
    }
    big = app_config.patch_features({}, {"time_saved": {"minutes_per_run": 99999}})
    assert big["time_saved"]["minutes_per_run"] == 1440


def _run(client: TestClient, team: Team, app_id: str) -> dict[str, Any]:
    res: dict[str, Any] = client.post(
        f"/api/v1/apps/{app_id}/runs",
        json={"input": {"message": "안녕"}},
        headers=team.h("builder"),
    ).json()
    return res


def test_report_counts_only_real_succeeded_runs(client: TestClient, team: Team) -> None:
    app_id, _ = new_session(client, team, "효과")
    client.put(
        f"/api/v1/apps/{app_id}/draft",
        json={"graph": code_graph(FIXED_CODE)},
        headers=team.h("builder"),
    )
    r = client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={"time_saved": {"minutes_per_run": 12}},
        headers=team.h("builder"),
    )
    assert r.status_code == 200 and r.json()["features"]["time_saved"]["minutes_per_run"] == 12
    _run(client, team, app_id)  # 시험 실행(trigger=test)은 세지 않는다
    url = f"/api/v1/workspaces/{team.ws}/impact"
    empty = client.get(url, headers=team.h("operator")).json()
    mine = next(a for a in empty["apps"] if a["app_id"] == app_id)
    assert mine["succeeded_runs"] == 0 and mine["saved_minutes"] == 0
    assert mine["minutes_per_run"] == 12 and empty["estimate"] is True

    from api.db import SessionLocal
    from api.models import Run

    with SessionLocal() as db:
        for trig, status in (("api", "succeeded"), ("chat", "succeeded"), ("api", "failed")):
            db.add(Run(app_id=app_id, trigger=trig, status=status, input={}))
        db.commit()
    out = client.get(url, headers=team.h("operator")).json()
    row = next(a for a in out["apps"] if a["app_id"] == app_id)
    assert row["succeeded_runs"] == 2 and row["saved_minutes"] == 24
    assert out["total_saved_minutes"] >= 24 and out["total_saved_hours"] >= 0.4


def test_report_requires_login_and_workspace(client: TestClient, team: Team) -> None:
    assert client.get(f"/api/v1/workspaces/{team.ws}/impact").status_code == 401


def test_member_cannot_view_report(client: TestClient, team: Team) -> None:
    res = client.get(f"/api/v1/workspaces/{team.ws}/impact", headers=team.h("member"))
    assert res.status_code == 403
