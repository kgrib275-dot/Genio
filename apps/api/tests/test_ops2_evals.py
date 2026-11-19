"""평가 세트: 질문 저장 → 한 번에 돌리기 → 규칙 채점 → 점수 변화."""

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from api.models import Run
from api.services import evals
from api.tests.conftest import Team
from api.tests.test_builder import new_session


def _graph(template: str) -> dict[str, Any]:
    return {
        "version": 1,
        "nodes": [
            {
                "id": "n1",
                "type": "input",
                "data": {
                    "label": "입력",
                    "fields": [{"key": "message", "type": "text", "required": True}],
                },
            },
            {"id": "n2", "type": "output", "data": {"label": "결과", "template": template}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
    }


def _setup(client: TestClient, team: Team, template: str) -> str:
    app_id, _ = new_session(client, team, "평가")
    r = client.put(
        f"/api/v1/apps/{app_id}/draft",
        json={"graph": _graph(template)},
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text
    return app_id


CASES: list[dict[str, Any]] = [
    {"name": "환불", "input": {"message": "환불"}, "contains": ["환불", "7일"]},
    {"name": "금지어", "input": {"message": "배송"}, "not_contains": ["욕설"]},
    {"name": "JSON", "input": {"message": "x"}, "json_valid": True},
]


def _save(client: TestClient, team: Team, app_id: str, cases: list[dict[str, Any]]) -> Any:
    return client.put(
        f"/api/v1/apps/{app_id}/evals/cases", json={"cases": cases}, headers=team.h("builder")
    )


def test_clean_case_limits() -> None:
    c = evals.clean_case(
        {
            "name": " " + "가" * 300,
            "input": {"": "x", "q": "a" * 9000, "n": 3},
            "contains": "a, b,\nc, a",
            "max_seconds": "9999",
        }
    )
    assert len(c["name"]) == 100 and len(c["input"]["q"]) == 4000 and c["input"]["n"] == 3
    assert c["contains"] == ["a", "b", "c"] and c["max_seconds"] == 600.0 and c["id"]
    assert evals.clean_case({})["name"] == "이름 없는 질문"


def test_save_run_and_score(client: TestClient, team: Team) -> None:
    app_id = _setup(client, team, "{{n1.message}} 은(는) 7일 안에 가능해요")
    saved = _save(client, team, app_id, CASES).json()["cases"]
    assert [c["name"] for c in saved] == ["환불", "금지어", "JSON"]
    assert (
        client.get(f"/api/v1/apps/{app_id}/evals/cases", headers=team.h("operator")).json()["cases"]
        == saved
    )
    started = client.post(f"/api/v1/apps/{app_id}/evals", headers=team.h("builder"))
    assert started.status_code == 201 and started.json()["total"] == 3
    batch = started.json()["batch"]
    rep = client.get(f"/api/v1/apps/{app_id}/evals/{batch}", headers=team.h("operator")).json()
    assert rep["finished"] == 3 and rep["running"] is False
    by = {r["name"]: r for r in rep["results"]}
    assert by["환불"]["passed"] is True and by["금지어"]["passed"] is True
    assert by["JSON"]["passed"] is False  # 답이 JSON이 아니다
    assert next(c for c in by["JSON"]["checks"] if not c["ok"])["name"] == "JSON 형식"
    assert rep["passed"] == 2 and rep["pass_rate"] == 0.667
    # 평가 실행은 일반 실행 기록에서 구분되는 종류(eval)로 남는다
    from api.db import SessionLocal

    with SessionLocal() as db:
        runs = db.query(Run).filter(Run.app_id == app_id).all()
        assert {r.trigger for r in runs} == {"eval"}


def test_score_drop_is_flagged(client: TestClient, team: Team) -> None:
    app_id = _setup(client, team, "{{n1.message}} 은(는) 7일 안에 가능해요")
    _save(client, team, app_id, CASES[:2])
    first = client.post(f"/api/v1/apps/{app_id}/evals", headers=team.h("builder")).json()
    # 답이 바뀌어(7일 → 30일) 점수가 떨어지는 상황
    client.put(
        f"/api/v1/apps/{app_id}/draft",
        json={"graph": _graph("{{n1.message}} 은(는) 30일 안에 가능해요")},
        headers=team.h("builder"),
    )
    second = client.post(f"/api/v1/apps/{app_id}/evals", headers=team.h("builder")).json()
    # 시간 순서를 분명히 한다
    from api.db import SessionLocal

    with SessionLocal() as db:
        for r in db.query(Run).filter(Run.app_id == app_id).all():
            batch = (r.context or {}).get("eval", {}).get("batch")
            r.created_at = datetime.now(UTC) - timedelta(
                minutes=5 if batch == first["batch"] else 0
            )
        db.commit()
    hist = client.get(f"/api/v1/apps/{app_id}/evals", headers=team.h("operator")).json()["batches"]
    assert [h["batch"] for h in hist] == [second["batch"], first["batch"]]
    assert hist[0]["pass_rate"] == 0.5 and hist[1]["pass_rate"] == 1.0
    assert hist[0]["dropped"] is True and hist[0]["previous_pass_rate"] == 1.0
    assert hist[1]["dropped"] is False


def test_max_seconds_and_unfinished_runs() -> None:
    class R:
        status = "succeeded"
        error = None
        output: ClassVar[dict[str, str]] = {"text": "ok"}
        started_at = datetime(2026, 1, 1, tzinfo=UTC)
        finished_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=3)

    s = evals.score_case({"max_seconds": 2.0}, R())  # type: ignore[arg-type]
    assert s["passed"] is False and s["seconds"] == 3.0
    assert evals.score_case({"max_seconds": 5.0}, R())["passed"] is True  # type: ignore[arg-type]


def test_validation_and_permissions(client: TestClient, team: Team) -> None:
    app_id = _setup(client, team, "{{n1.message}}")
    assert client.post(f"/api/v1/apps/{app_id}/evals", headers=team.h("builder")).status_code == 422
    too_many = [{"name": f"q{i}", "input": {"message": "a"}} for i in range(51)]
    assert _save(client, team, app_id, too_many).status_code == 422
    assert _save(client, team, app_id, CASES[:1]).status_code == 200
    assert (
        client.put(
            f"/api/v1/apps/{app_id}/evals/cases",
            json={"cases": []},
            headers=team.h("operator"),
        ).status_code
        == 403
    )
    assert (
        client.post(f"/api/v1/apps/{app_id}/evals", headers=team.h("operator")).status_code == 403
    )
    assert (
        client.get(f"/api/v1/apps/{app_id}/evals/nope", headers=team.h("builder")).status_code
        == 404
    )
    assert client.get(f"/api/v1/apps/{app_id}/evals").status_code == 401


def test_ai_judge_scores_only_after_judging_and_gate_blocks_deploy(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = _setup(client, team, "{{n1.message}} 은(는) 7일 안에 가능해요")
    cases = [
        {
            "name": "환불",
            "input": {"message": "환불"},
            "contains": ["7일"],
            "judge": "환불 기간을 정확히 말한다",
        },
        {
            "name": "배송",
            "input": {"message": "배송"},
            "contains": ["7일"],
            "judge": "배송비를 안내한다",
        },
    ]
    assert _save(client, team, app_id, cases).status_code == 200
    batch = client.post(f"/api/v1/apps/{app_id}/evals", headers=team.h("builder")).json()["batch"]

    verdicts = {
        "환불": {"ok": True, "reason": "기간을 맞게 말했어요."},
        "배송": {"ok": False, "reason": "배송비 안내가 없어요."},
    }
    monkeypatch.setattr(evals, "judge_answer", lambda db, app, case, answer: verdicts[case["name"]])
    # 내역(history)은 심판 전이라 합격·불합격을 세지 않는다
    before = client.get(f"/api/v1/apps/{app_id}/evals", headers=team.h("operator")).json()[
        "batches"
    ][0]
    assert before["pass_rate"] is None and before["pending_judge"] == 2
    rep = client.get(f"/api/v1/apps/{app_id}/evals/{batch}", headers=team.h("operator")).json()
    by = {r["name"]: r for r in rep["results"]}
    assert by["환불"]["passed"] is True and by["배송"]["passed"] is False
    assert any(
        c["name"] == "AI 심판" and not c["ok"] and "배송비" in c["detail"]
        for c in by["배송"]["checks"]
    )
    assert rep["pass_rate"] == 0.5 and rep["pending_judge"] == 0
    # 한 번 판단한 것은 다시 부르지 않는다
    monkeypatch.setattr(evals, "judge_answer", lambda *a, **k: pytest.fail("두 번 부르면 안 돼요"))
    client.get(f"/api/v1/apps/{app_id}/evals/{batch}", headers=team.h("operator"))

    # 배포 전 통과 조건: 80%를 요구하면 50%라 막고, 낮추면 통과
    gate = f"/api/v1/apps/{app_id}/evals/gate"
    assert client.put(
        gate, json={"enabled": True, "min_pass_rate": 0.8}, headers=team.h("builder")
    ).json()["enabled"]
    assert client.put(gate, json={"enabled": True}, headers=team.h("operator")).status_code == 403
    dep = {"channel": "share_link", "access": "workspace"}
    blocked = client.post(f"/api/v1/apps/{app_id}/deployments", json=dep, headers=team.h("admin"))
    assert blocked.status_code == 409 and "50%" in blocked.json()["detail"]["hint"]
    # 질문을 다시 저장해도 조건은 그대로 남는다
    _save(client, team, app_id, cases)
    assert client.get(gate, headers=team.h("operator")).json()["min_pass_rate"] == 0.8
    client.put(gate, json={"enabled": True, "min_pass_rate": 0.5}, headers=team.h("builder"))
    ok = client.post(f"/api/v1/apps/{app_id}/deployments", json=dep, headers=team.h("admin"))
    assert ok.status_code == 201, ok.text


def test_gate_asks_for_a_check_first_and_judge_failure_is_not_a_pass(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = _setup(client, team, "{{n1.message}} 답")
    _save(client, team, app_id, [{"name": "a", "input": {"message": "x"}, "judge": "기준"}])
    client.put(
        f"/api/v1/apps/{app_id}/evals/gate",
        json={"enabled": True, "min_pass_rate": 0.5},
        headers=team.h("builder"),
    )
    dep = {"channel": "share_link", "access": "workspace"}
    first = client.post(f"/api/v1/apps/{app_id}/deployments", json=dep, headers=team.h("admin"))
    assert first.status_code == 409 and "먼저" in first.json()["detail"]["hint"]

    # AI 연결이 없어 심판이 실패하면 합격으로 치지 않는다
    from api.db import SessionLocal
    from api.models import App

    batch = client.post(f"/api/v1/apps/{app_id}/evals", headers=team.h("builder")).json()["batch"]
    rep = client.get(f"/api/v1/apps/{app_id}/evals/{batch}", headers=team.h("operator")).json()
    assert rep["results"][0]["passed"] is False
    assert "AI 심판을 하지 못했어요" in str(rep["results"][0]["checks"])
    with SessionLocal() as db:
        assert db.get(App, app_id) is not None
