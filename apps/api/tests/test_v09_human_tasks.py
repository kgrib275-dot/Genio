"""v0.9 사람 단계 보강: 전달(권한·이력·알림), 시간 초과 처리(자동 반려·승인·올리기·정해 둔 값·'시간 초과' 길),
다시 알리기(한 번만), 병렬 갈래·일괄 실행 안에서의 이어 가기, 검증 규칙, 실행 이야기."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.db import SessionLocal
from api.models import AuditLog, HumanTask, User
from api.services import notify as notify_svc
from api.services import tasks as tsvc
from api.services.queue import enqueue_run
from api.tests.conftest import ROLES, Team
from api.tests.test_v05_engine import make_app, start, validate

SLACK_NOTIFY = {"slack": {"credential_id": "cred-1", "channel": "#ops"}}


def approval_graph(**data: Any) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "message"}]}},
            {"id": "ap", "type": "approval", "data": {"message": "승인해 주세요", **data}},
            {"id": "out", "type": "output", "data": {"template": "승인={{ap.approved}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "ap"},
            {"id": "e2", "source": "ap", "target": "out"},
        ],
    }


def branch_graph(**data: Any) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "message"}]}},
            {
                "id": "ap",
                "type": "approval",
                "data": {"message": "승인?", "branch": True, "due_hours": 2, **data},
            },
            {"id": "ok", "type": "output", "data": {"template": "승인됨"}},
            {"id": "no", "type": "output", "data": {"template": "반려됨"}},
            {"id": "late", "type": "output", "data": {"template": "시간 초과 길"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "ap"},
            {"id": "e2", "source": "ap", "target": "ok", "sourceHandle": "approved"},
            {"id": "e3", "source": "ap", "target": "no", "sourceHandle": "rejected"},
            {"id": "e4", "source": "ap", "target": "late", "sourceHandle": "timeout"},
        ],
    }


def ask_graph(**data: Any) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "item"}]}},
            {
                "id": "q1",
                "type": "ask_person",
                "data": {
                    "question": "{{n1.item}} 금액은?",
                    "fields": [{"key": "price", "label": "금액", "type": "number"}],
                    "assignee_role": "operator",
                    "due_hours": 4,
                    **data,
                },
            },
            {
                "id": "out",
                "type": "output",
                "data": {"template": "금액={{q1.price}} 초과={{q1.timed_out}}"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "q1"},
            {"id": "e2", "source": "q1", "target": "out"},
        ],
    }


def sweep_at(hours: float) -> dict[str, list[str]]:
    """지금부터 hours시간 뒤인 것처럼 열린 일을 훑고, 이어서 실행할 것을 큐(바로 실행)에 넣는다."""
    with SessionLocal() as db:
        res = tsvc.sweep(db, datetime.now(UTC) + timedelta(hours=hours))
    for run_id in res["resume"]:
        enqueue_run(run_id)
    return res


def run_detail(client: TestClient, team: Team, run_id: str) -> dict[str, Any]:
    out: dict[str, Any] = client.get(f"/api/v1/runs/{run_id}", headers=team.h("builder")).json()
    return out


def open_tasks(app_id: str | None = None) -> list[HumanTask]:
    with SessionLocal() as db:
        q = select(HumanTask).where(HumanTask.status == "open")
        if app_id:
            q = q.where(HumanTask.app_id == app_id)
        return list(db.scalars(q))


def task_row(task_id: str) -> HumanTask:
    with SessionLocal() as db:
        t = db.get(HumanTask, task_id)
        assert t is not None
        db.expunge(t)
        return t


# ---------------- 시간 초과: 자동 반려·승인 ----------------
def test_timeout_auto_reject_stops_run_with_clear_text(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, approval_graph(due_hours=24, on_timeout="reject"))
    assert validate(client, team, app_id)["valid"]
    d = start(client, team, app_id, {"message": "x"})
    assert d["status"] == "waiting_approval"
    # 아직 기한 전이면 아무 일도 없다
    assert sweep_at(1) == {"resume": [], "reminded": [], "timed_out": []}
    res = sweep_at(25)
    assert len(res["timed_out"]) == 1 and res["resume"] == [d["id"]]
    done = run_detail(client, team, d["id"])
    assert done["status"] == "failed" and "자동으로 반려" in done["error"]
    ap = next(s for s in done["steps"] if s["node_id"] == "ap")
    assert ap["status"] == "failed" and ap["output"]["timed_out"] is True
    assert "자동으로 반려" in ap["summary"]
    t = task_row(open_or_done(d["id"]))
    assert t.status == "done" and t.response["timed_out"] is True
    assert t.completed_by is None


def open_or_done(run_id: str) -> str:
    with SessionLocal() as db:
        t = db.scalar(select(HumanTask).where(HumanTask.run_id == run_id))
        assert t is not None
        return t.id


def test_timeout_auto_approve_continues(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, approval_graph(due_hours=6, on_timeout="approve"))
    d = start(client, team, app_id, {"message": "x"})
    sweep_at(7)
    done = run_detail(client, team, d["id"])
    assert done["status"] == "succeeded" and done["output"]["text"] == "승인=True"
    ap = next(s for s in done["steps"] if s["node_id"] == "ap")
    assert ap["output"]["approver"] == "시스템" and "자동으로 승인" in ap["summary"]
    assert any("자동으로 승인" in line for line in done["story"])
    # 두 번 훑어도 같은 일을 또 처리하지 않는다
    assert sweep_at(30)["timed_out"] == []


def test_timeout_none_keeps_waiting_and_marks_overdue(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, approval_graph(due_hours=1))
    d = start(client, team, app_id, {"message": "x"})
    assert sweep_at(50)["timed_out"] == []
    assert run_detail(client, team, d["id"])["status"] == "waiting_approval"
    t = open_tasks(app_id)[0]
    row = client.get(f"/api/v1/workspaces/{team.ws}/tasks/{t.id}", headers=team.h("owner")).json()
    assert row["timeout_mode"] == "none" and row["overdue"] is False  # 실제 시계로는 아직 기한 전


# ---------------- '시간 초과' 길 ----------------
def test_timeout_branch_handle(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, branch_graph(on_timeout="branch"))
    assert validate(client, team, app_id)["valid"]
    d = start(client, team, app_id, {"message": "x"})
    sweep_at(3)
    done = run_detail(client, team, d["id"])
    assert done["status"] == "succeeded" and done["output"]["text"] == "시간 초과 길"
    ran = {s["node_id"] for s in done["steps"]}
    assert "late" in ran and "ok" not in ran and "no" not in ran
    ap = next(s for s in done["steps"] if s["node_id"] == "ap")
    assert "'시간 초과' 길" in ap["summary"]
    # 사람이 제때 처리하면 승인·반려 길로 간다(시간 초과 길은 건너뛴다)
    d2 = start(client, team, app_id, {"message": "y"})
    r = client.post(
        f"/api/v1/runs/{d2['id']}/approve", json={"approved": True}, headers=team.h("builder")
    )
    assert r.status_code == 200
    fin = run_detail(client, team, d2["id"])
    assert fin["output"]["text"] == "승인됨"
    assert "late" not in {s["node_id"] for s in fin["steps"]}


def test_timeout_branch_for_ask_person(client: TestClient, team: Team) -> None:
    g = ask_graph(on_timeout="branch")
    g["nodes"].append({"id": "late", "type": "output", "data": {"template": "답 없음"}})
    g["edges"].append({"id": "e3", "source": "q1", "target": "late", "sourceHandle": "timeout"})
    app_id = make_app(client, team, g)
    assert validate(client, team, app_id)["valid"]
    d = start(client, team, app_id, {"item": "노트북"})
    sweep_at(5)
    done = run_detail(client, team, d["id"])
    ran = {s["node_id"] for s in done["steps"]}
    assert done["status"] == "succeeded" and "late" in ran and "out" not in ran
    assert done["output"]["text"] == "답 없음"


def test_timeout_branch_without_edge_fails_with_clear_text(client: TestClient, team: Team) -> None:
    g = branch_graph(on_timeout="branch")
    g["edges"] = g["edges"][:3]  # 시간 초과 길을 잇지 않았다
    g["nodes"] = g["nodes"][:4]
    app_id = make_app(client, team, g)
    d = start(client, team, app_id, {"message": "x"})
    sweep_at(3)
    done = run_detail(client, team, d["id"])
    assert done["status"] == "failed" and "시간 초과" in done["error"]


# ---------------- 질문: 정해 둔 값·반려·올리기 ----------------
def test_ask_continue_uses_default_values(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, ask_graph(on_timeout="continue", timeout_default={"price": 0}))
    d = start(client, team, app_id, {"item": "노트북"})
    assert d["status"] == "waiting_approval"
    sweep_at(5)
    done = run_detail(client, team, d["id"])
    assert done["status"] == "succeeded" and done["output"]["text"] == "금액=0 초과=True"
    q = next(s for s in done["steps"] if s["node_id"] == "q1")
    assert "정해 둔 값으로" in q["summary"]


def test_ask_reject_fails_run(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, ask_graph(on_timeout="reject"))
    d = start(client, team, app_id, {"item": "x"})
    sweep_at(5)
    done = run_detail(client, team, d["id"])
    assert done["status"] == "failed" and "정해 둔 시간 안에 처리되지 않아" in done["error"]
    q = next(s for s in done["steps"] if s["node_id"] == "q1")
    assert q["status"] == "failed" and "처리되지 않아 흐름이 멈췄어요" in q["summary"]


def test_escalate_once_then_final_reject(client: TestClient, team: Team) -> None:
    app_id = make_app(
        client, team, ask_graph(on_timeout="escalate", timeout_escalate_to="admin", due_hours=4)
    )
    assert validate(client, team, app_id)["valid"]
    d = start(client, team, app_id, {"item": "x"})
    t0 = open_tasks(app_id)[0]
    assert t0.assignee_role == "operator"
    first = sweep_at(5)
    assert first["timed_out"] == [t0.id] and first["resume"] == []
    t1 = task_row(t0.id)
    assert t1.status == "open" and t1.assignee_role == "admin" and t1.assignee_user_id is None
    assert t1.rules["escalated"] is True
    assert t1.history[-1]["via"] == "timeout" and t1.history[-1]["by_name"] == "시스템"
    assert t1.due_at is not None
    due = t1.due_at.replace(tzinfo=UTC) if t1.due_at.tzinfo is None else t1.due_at
    assert due > datetime.now(UTC) + timedelta(hours=3)  # 기한이 같은 만큼 늘었다
    assert run_detail(client, team, d["id"])["status"] == "waiting_approval"
    # 관리자 담당 일이 되어 운영자는 더 처리할 수 없다
    assert (
        client.post(
            f"/api/v1/workspaces/{team.ws}/tasks/{t0.id}/complete",
            json={"values": {"price": 3}},
            headers=team.h("operator"),
        ).status_code
        == 403
    )
    # 올린 뒤에도 기한이 또 지나면 마지막으로 반려(멈춤)한다
    second = sweep_at(20)
    assert second["resume"] == [d["id"]]
    assert run_detail(client, team, d["id"])["status"] == "failed"


def test_escalate_to_missing_target_falls_back_to_reject(client: TestClient, team: Team) -> None:
    app_id = make_app(
        client,
        team,
        ask_graph(on_timeout="escalate", timeout_escalate_to="no-such-user-id", due_hours=1),
    )
    d = start(client, team, app_id, {"item": "x"})
    res = sweep_at(2)
    assert res["resume"] == [d["id"]]
    assert run_detail(client, team, d["id"])["status"] == "failed"


# ---------------- 다시 알리기 ----------------
def test_reminder_sent_once(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []

    def fake_send(db: Any, ws: str, notify: dict[str, Any], **kw: Any) -> list[str]:
        sent.append({"notify": notify, **kw})
        return ["보냈어요"]

    monkeypatch.setattr(notify_svc, "send", fake_send)
    app_id = make_app(
        client,
        team,
        approval_graph(due_hours=10, remind_before_hours=2, notify=SLACK_NOTIFY),
    )
    d = start(client, team, app_id, {"message": "x"})
    n_start = len(sent)  # 처음 요청 알림은 실행기가 보낸다(여기서는 가짜가 받는다)
    assert sweep_at(5)["reminded"] == []  # 아직 기한 2시간 전이 아니다
    res = sweep_at(8.5)
    assert len(res["reminded"]) == 1
    assert len(sent) == n_start + 1 and "기한 임박" in sent[-1]["title"]
    assert sweep_at(9)["reminded"] == [] and len(sent) == n_start + 1  # 한 번만
    assert run_detail(client, team, d["id"])["status"] == "waiting_approval"  # 알리기만 한다
    t = open_tasks(app_id)[0]
    assert t.rules["reminded"] is True


# ---------------- 병렬 갈래·일괄 실행 안에서 ----------------
def parallel_graph(second_timeout: str | None = None) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "n1", "type": "input", "data": {"fields": [{"key": "message"}]}},
        {
            "id": "ap",
            "type": "approval",
            "data": {"message": "첫째?", "due_hours": 1, "on_timeout": "approve"},
        },
        {"id": "fast", "type": "template", "data": {"template": "빠른 갈래"}},
        {
            "id": "out",
            "type": "output",
            "data": {"template": "{{fast.output}}/{{ap.approved}}"},
        },
    ]
    edges = [
        {"id": "e1", "source": "n1", "target": "ap"},
        {"id": "e3", "source": "n1", "target": "fast"},
        {"id": "e4", "source": "ap", "target": "out"},
        {"id": "e6", "source": "fast", "target": "out"},
    ]
    if second_timeout:
        nodes.append(
            {
                "id": "ap2",
                "type": "approval",
                "data": {"message": "둘째?", "due_hours": 1, "on_timeout": second_timeout},
            }
        )
        nodes[3]["data"]["template"] = "{{fast.output}}/{{ap.approved}}/{{ap2.approved}}"
        edges += [
            {"id": "e2", "source": "n1", "target": "ap2"},
            {"id": "e5", "source": "ap2", "target": "out"},
        ]
    return {"nodes": nodes, "edges": edges}


def test_timeout_inside_parallel_branch_resumes_like_a_human(
    client: TestClient, team: Team
) -> None:
    app_id = make_app(client, team, parallel_graph())
    assert validate(client, team, app_id)["valid"]
    d = start(client, team, app_id, {"message": "x"})
    assert d["status"] == "waiting_approval"
    assert next(s for s in d["steps"] if s["node_id"] == "fast")["status"] == "succeeded"
    sweep_at(2)
    done = run_detail(client, team, d["id"])
    assert done["status"] == "succeeded" and done["output"]["text"] == "빠른 갈래/True"
    assert [s["node_id"] for s in done["steps"]].count("out") == 1


def test_two_timeouts_in_parallel_branches_open_one_at_a_time(
    client: TestClient, team: Team
) -> None:
    app_id = make_app(client, team, parallel_graph(second_timeout="reject"))
    d = start(client, team, app_id, {"message": "x"})
    waiting = run_detail(client, team, d["id"])
    assert waiting["status"] == "waiting_approval"
    assert len(open_tasks(app_id)) == 1  # 사람 일은 한 번에 하나만 열린다
    first = sweep_at(2)
    assert first["resume"] == [d["id"]]
    mid = run_detail(client, team, d["id"])
    assert mid["status"] == "waiting_approval"  # 두 번째 일이 이어서 열렸다
    assert len(open_tasks(app_id)) == 1
    assert sweep_at(10)["resume"] == [d["id"]]
    assert run_detail(client, team, d["id"])["status"] == "failed"  # 둘째는 자동 반려


def test_timeout_resumes_rows_of_a_batch(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, approval_graph(due_hours=3, on_timeout="approve"))
    res = client.post(
        f"/api/v1/apps/{app_id}/batches",
        json={
            "rows": [{"row": 2, "values": {"message": "a"}}, {"row": 3, "values": {"message": "b"}}]
        },
        headers=team.h("builder"),
    )
    assert res.status_code == 201, res.text
    batch_id = res.json()["batch_id"]
    mid = client.get(f"/api/v1/apps/{app_id}/batches/{batch_id}", headers=team.h("builder")).json()
    assert mid["counts"]["waiting_approval"] == 2
    out = sweep_at(4)
    assert len(out["resume"]) == 2
    fin = client.get(f"/api/v1/apps/{app_id}/batches/{batch_id}", headers=team.h("builder")).json()
    assert fin["counts"]["succeeded"] == 2 and fin["counts"]["waiting_approval"] == 0


def test_worker_task_runs_sweep(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    from worker.tasks import sweep_human_tasks_task

    app_id = make_app(client, team, approval_graph(due_hours=2, on_timeout="approve"))
    d = start(client, team, app_id, {"message": "x"})
    later = datetime.now(UTC) + timedelta(hours=3)
    monkeypatch.setattr(tsvc, "now", lambda: later)
    counts = sweep_human_tasks_task()
    assert counts == {"resume": 1, "reminded": 0, "timed_out": 1}
    assert run_detail(client, team, d["id"])["status"] == "succeeded"


# ---------------- 검증 규칙 ----------------
def test_validator_rules_for_timeout_settings(client: TestClient, team: Team) -> None:
    def errors(graph: dict[str, Any]) -> list[str]:
        app = make_app(client, team, graph)
        return [e["message"] for e in validate(client, team, app)["errors"]]

    assert any("기한(시간)" in m for m in errors(approval_graph(on_timeout="reject")))
    assert any("올릴 곳" in m for m in errors(approval_graph(due_hours=2, on_timeout="escalate")))
    assert any(
        "기한보다 짧아야" in m for m in errors(approval_graph(due_hours=2, remind_before_hours=3))
    )
    assert any("먼저 정해" in m for m in errors(approval_graph(remind_before_hours=1)))
    # '시간 초과' 길은 '기한이 지나면'을 그 길로 보내기로 했을 때만 쓸 수 있다
    bad = branch_graph(on_timeout="reject")
    assert any("'시간 초과' 길을 쓰려면" in m for m in errors(bad))
    assert errors(branch_graph(on_timeout="branch")) == []
    twice = branch_graph(on_timeout="branch")
    twice["edges"].append({"id": "e9", "source": "ap", "target": "late", "sourceHandle": "timeout"})
    assert any("한 곳으로만" in m for m in errors(twice))


# ---------------- 전달 ----------------
def ask_with_notify() -> dict[str, Any]:
    return ask_graph(
        notify={"email": {"credential_id": "mail-1", "to": "boss@example.com"}, **SLACK_NOTIFY}
    )


def user_id(email: str) -> str:
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        assert u is not None
        return u.id


def forward(client: TestClient, team: Team, task_id: str, role: str, **body: Any) -> Any:
    return client.post(
        f"/api/v1/workspaces/{team.ws}/tasks/{task_id}/forward", json=body, headers=team.h(role)
    )


def test_forward_to_user_history_notify_and_permissions(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []

    def fake_send(db: Any, ws: str, notify: dict[str, Any], **kw: Any) -> list[str]:
        sent.append({"notify": notify, **kw})
        return ["보냈어요"]

    monkeypatch.setattr(notify_svc, "send", fake_send)
    app_id = make_app(client, team, ask_with_notify())
    start(client, team, app_id, {"item": "노트북"})
    task = open_tasks(app_id)[0]
    builder_id = team.users["builder"]
    before = len(sent)
    # 담당 역할(운영자)이 제작자 한 명에게 전달
    r = forward(client, team, task.id, "operator", to_user_id=builder_id, comment="이 건 부탁해요")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["assignee_user_id"] == builder_id and d["assignee_role"] is None
    assert (
        d["history"][-1]["to_name"] == "builder 사용자"
        and d["history"][-1]["comment"] == "이 건 부탁해요"
    )
    assert d["history"][-1]["by_name"] == "operator 사용자" and d["can_act"] is False
    # 전달받은 사람에게 알림: 이메일은 받는 사람이 그 사람 메일로 바뀌고 슬랙은 그대로
    note = sent[before]
    assert note["notify"]["email"]["to"] == ["builder@test.local"]
    assert note["notify"]["email"]["credential_id"] == "mail-1"
    assert note["notify"]["slack"]["channel"] == "#ops" and "[전달받음]" in note["title"]
    # 더는 운영자가 처리할 수 없고, 전달받은 제작자가 처리한다
    deny = client.post(
        f"/api/v1/workspaces/{team.ws}/tasks/{task.id}/complete",
        json={"values": {"price": 7}},
        headers=team.h("operator"),
    )
    assert deny.status_code == 403
    mine = client.get(
        f"/api/v1/workspaces/{team.ws}/tasks", params={"mine": True}, headers=team.h("builder")
    ).json()
    assert [t["id"] for t in mine] == [task.id]
    ok = client.post(
        f"/api/v1/workspaces/{team.ws}/tasks/{task.id}/complete",
        json={"values": {"price": 7}},
        headers=team.h("builder"),
    )
    assert ok.status_code == 200 and ok.json()["status"] == "done"
    # 처리된 일은 전달할 수 없다
    again = forward(client, team, task.id, "owner", to_role="admin")
    assert again.status_code == 409 and again.json()["detail"]["hint"]
    # 활동 기록
    with SessionLocal() as db:
        log = db.scalar(select(AuditLog).where(AuditLog.action == "task.forward"))
        assert (
            log is not None and log.target_id == task.id and log.user_id == team.users["operator"]
        )


def test_forward_permissions_and_validation(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, ask_graph())
    start(client, team, app_id, {"item": "x"})
    task = open_tasks(app_id)[0]  # 담당 역할: 운영자
    for role in ("member", "builder"):
        # 담당(운영자)이 아니고 소유자·관리자도 아니면 전달할 수 없다
        assert forward(client, team, task.id, role, to_role="admin").status_code == 403, role
    # 대상은 사람 또는 역할 중 하나만
    both = forward(
        client, team, task.id, "operator", to_role="admin", to_user_id=team.users["admin"]
    )
    assert both.status_code == 422 and both.json()["detail"]["hint"]
    none = forward(client, team, task.id, "operator")
    assert none.status_code == 422
    # 다른 워크스페이스(멤버 아님) 사람은 안 된다
    with SessionLocal() as db:
        from api.core.security import hash_password

        stranger = User(
            email="stranger@test.local", name="외부인", password_hash=hash_password("x" * 12)
        )
        db.add(stranger)
        db.commit()
        sid = stranger.id
    bad = forward(client, team, task.id, "operator", to_user_id=sid)
    assert bad.status_code == 422 and "멤버가 아니에요" in bad.json()["detail"]["message"]
    assert forward(client, team, task.id, "operator", to_user_id="no-such").status_code == 422
    # 이미 그 역할이 담당이면 409, 잘못된 역할 이름은 422
    assert forward(client, team, task.id, "operator", to_role="operator").status_code == 409
    assert forward(client, team, task.id, "operator", to_role="king").status_code == 422
    # 소유자·관리자는 담당이 아니어도 전달할 수 있다
    ok = forward(client, team, task.id, "admin", to_role="builder", comment="제작자가 봐 주세요")
    assert ok.status_code == 200 and ok.json()["assignee_role"] == "builder"
    assert [h["by_name"] for h in ok.json()["history"]] == ["admin 사용자"]
    # 이력은 쌓인다
    again = forward(client, team, task.id, "owner", to_user_id=team.users["member"])
    assert [h["to_name"] for h in again.json()["history"]] == ["제작자", "member 사용자"]
    # 로그인 없이 여는 링크 화면에는 전달 이력·내부 값이 보이지 않는다
    link = client.get(
        f"/api/v1/workspaces/{team.ws}/tasks/{task.id}", headers=team.h("owner")
    ).json()
    with SessionLocal() as db:
        token = db.get(HumanTask, task.id).token  # type: ignore[union-attr]
    pub = client.get(f"/api/v1/public/tasks/{token}").json()
    assert "history" not in pub and "assignee_user_id" not in pub and link["history"]


def test_forward_approval_to_role_lets_that_role_approve(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, approval_graph())
    d = start(client, team, app_id, {"message": "x"})
    task = open_tasks(app_id)[0]
    # 승인은 제작자·운영자가 할 수 있는데, 소유자가 사용자(member) 역할로 넘기면 사용자가 승인한다
    assert (
        client.post(
            f"/api/v1/workspaces/{team.ws}/tasks/{task.id}/complete",
            json={"approved": True},
            headers=team.h("member"),
        ).status_code
        == 403
    )
    r = forward(client, team, task.id, "owner", to_role="member")
    assert r.status_code == 200
    ok = client.post(
        f"/api/v1/workspaces/{team.ws}/tasks/{task.id}/complete",
        json={"approved": True},
        headers=team.h("member"),
    )
    assert ok.status_code == 200
    assert run_detail(client, team, d["id"])["status"] == "succeeded"
    # 이제 운영자는 승인할 수 없다(이미 끝남)
    assert forward(client, team, task.id, "owner", to_role="admin").status_code == 409


def test_forward_targets_roles_and_no_email_leak(client: TestClient, team: Team) -> None:
    for role in ROLES:
        r = client.get(f"/api/v1/workspaces/{team.ws}/tasks/forward-targets", headers=team.h(role))
        assert r.status_code == (200 if role != "member" else 403), role
    d = client.get(
        f"/api/v1/workspaces/{team.ws}/tasks/forward-targets", headers=team.h("operator")
    ).json()
    assert {u["role"] for u in d["users"]} == set(ROLES)
    assert "@" not in str(d) and [r["id"] for r in d["roles"]] == list(ROLES)
