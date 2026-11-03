"""프로젝트 현황판: 프로젝트별 집계, 공개 범위, 역할 권한."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from api.db import SessionLocal
from api.models import Run
from api.tests.conftest import Team


def _add_runs(app_id: str, statuses: list[str], cost: str = "0.01", days_ago: int = 0) -> None:
    with SessionLocal() as db:
        for st in statuses:
            db.add(
                Run(
                    app_id=app_id,
                    status=st,
                    trigger="test",
                    token_usage={"input_tokens": 10, "output_tokens": 5},
                    cost=Decimal(cost),
                    created_at=datetime.now(UTC) - timedelta(days=days_ago),
                )
            )
        db.commit()


def test_projects_overview(client: TestClient, team: Team) -> None:
    base = f"/api/v1/workspaces/{team.ws}"
    pub = client.post(
        f"{base}/projects", json={"name": "공용", "color": "sky"}, headers=team.h("builder")
    ).json()
    priv = client.post(
        f"{base}/projects",
        json={"name": "비밀", "visibility": "private"},
        headers=team.h("builder"),
    ).json()
    a_pub = client.post(
        f"{base}/apps", json={"name": "A", "project_id": pub["id"]}, headers=team.h("builder")
    ).json()
    a_priv = client.post(
        f"{base}/apps", json={"name": "B", "project_id": priv["id"]}, headers=team.h("builder")
    ).json()
    a_none = client.post(f"{base}/apps", json={"name": "C"}, headers=team.h("builder")).json()
    client.post(
        f"{base}/knowledge-bases",
        json={"name": "KB", "project_id": pub["id"]},
        headers=team.h("builder"),
    )
    _add_runs(a_pub["id"], ["succeeded", "succeeded", "succeeded", "failed", "waiting_approval"])
    _add_runs(a_priv["id"], ["succeeded"], cost="1.5")
    _add_runs(a_none["id"], ["failed"])
    _add_runs(a_pub["id"], ["succeeded"], days_ago=40)  # 기간 밖

    # 관리자: 비공개 프로젝트까지 모두 보인다
    d = client.get(f"{base}/projects/overview?days=30", headers=team.h("admin")).json()
    by = {r["project"]["name"]: r for r in d["projects"]}
    assert set(by) == {"공용", "비밀"} and d["days"] == 30
    p = by["공용"]
    assert (p["apps"], p["knowledge_bases"], p["runs"]) == (1, 1, 5)
    assert (p["succeeded"], p["failed"], p["waiting_approval"]) == (3, 1, 1)
    assert p["success_rate"] == 0.75 and p["input_tokens"] == 50
    assert len(p["series"]) == 30 and sum(x["runs"] for x in p["series"]) == 5
    assert p["last_activity_at"] is not None
    assert d["unassigned"]["apps"] == 1 and d["unassigned"]["failed"] == 1
    t = d["totals"]
    assert (t["projects"], t["apps"], t["runs"]) == (2, 3, 7)
    assert abs(t["cost"] - 1.56) < 1e-6 and t["success_rate"] == round(4 / 6, 3)

    # 운영자: 비공개 프로젝트는 숨겨지고 합계에서도 빠진다
    d = client.get(f"{base}/projects/overview", headers=team.h("operator")).json()
    assert [r["project"]["name"] for r in d["projects"]] == ["공용"]
    assert d["totals"]["runs"] == 6 and d["totals"]["apps"] == 2

    # 기간 7일 / 범위 밖 값은 1~90으로 맞춘다
    d7 = client.get(f"{base}/projects/overview?days=7", headers=team.h("admin")).json()
    assert d7["days"] == 7 and all(len(r["series"]) == 7 for r in d7["projects"])
    assert (
        client.get(f"{base}/projects/overview?days=999", headers=team.h("admin")).json()["days"]
        == 90
    )

    # 일반 사용자는 실행 기록을 볼 수 없으므로 거부
    assert client.get(f"{base}/projects/overview", headers=team.h("member")).status_code == 403
    assert client.get(f"{base}/projects/overview", headers=team.h("owner")).status_code == 200
    assert client.get(f"{base}/projects/overview", headers=team.h("builder")).status_code == 200
