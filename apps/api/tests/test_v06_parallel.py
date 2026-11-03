"""v0.6 병렬 분기(ADR 0010): 갈래 동시 실행, 합치는 단계 대기, 안 간 갈래 건너뛰기,
갈래 안 실패·승인 대기, 이 단계부터 다시, 빌더 툴의 parallel 옵션."""

import time
from typing import Any

from fastapi.testclient import TestClient

from api.tests.conftest import Team
from api.tests.test_v05_engine import make_app, start, validate


def _fan(wait: int = 1) -> dict[str, Any]:
    """입력 → (갈래 A: 기다리기→값, 갈래 B: 기다리기→값) → 합치기 → 결과."""
    return {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "name"}]}},
            {"id": "wa", "type": "wait", "data": {"label": "A 기다리기", "seconds": wait}},
            {"id": "wb", "type": "wait", "data": {"label": "B 기다리기", "seconds": wait}},
            {"id": "ta", "type": "template", "data": {"template": "A:{{n1.name}}"}},
            {"id": "tb", "type": "template", "data": {"template": "B:{{n1.name}}"}},
            {"id": "j", "type": "template", "data": {"template": "{{ta.output}}+{{tb.output}}"}},
            {"id": "out", "type": "output", "data": {"template": "{{j.output}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "wa"},
            {"id": "e2", "source": "n1", "target": "wb"},
            {"id": "e3", "source": "wa", "target": "ta"},
            {"id": "e4", "source": "wb", "target": "tb"},
            {"id": "e5", "source": "ta", "target": "j"},
            {"id": "e6", "source": "tb", "target": "j"},
            {"id": "e7", "source": "j", "target": "out"},
        ],
    }


def test_fan_out_runs_concurrently_and_join_waits(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, _fan(1))
    v = validate(client, team, app_id)
    assert v["valid"], v["errors"]
    t0 = time.monotonic()
    d = start(client, team, app_id, {"name": "김"})
    elapsed = time.monotonic() - t0
    assert d["status"] == "succeeded", d["error"]
    assert d["output"]["text"] == "A:김+B:김"
    # 1초씩 두 갈래가 동시에 돌았으니 2초보다 확실히 짧다
    assert elapsed < 1.8, elapsed
    order = [s["node_id"] for s in d["steps"]]
    assert d["steps"][order.index("j")]["status"] == "succeeded"
    # 합치는 단계는 두 갈래가 끝난 뒤에 실행됐다
    assert order.index("j") > order.index("ta") and order.index("j") > order.index("tb")
    assert [s["node_id"] for s in d["steps"]].count("j") == 1


def test_untaken_branch_does_not_block_join(client: TestClient, team: Team) -> None:
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "x"}]}},
            {
                "id": "c",
                "type": "condition",
                "data": {"cases": [{"id": "big", "when": "{{n1.x}} > 10"}], "else": "small"},
            },
            {"id": "a", "type": "template", "data": {"template": "큰 수"}},
            {"id": "b", "type": "template", "data": {"template": "작은 수"}},
            {"id": "side", "type": "template", "data": {"template": "옆 갈래"}},
            {
                "id": "out",
                "type": "output",
                "data": {"template": "{{a.output}}{{b.output}}/{{side.output}}"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "c"},
            {"id": "e1b", "source": "n1", "target": "side"},
            {"id": "e2", "source": "c", "target": "a", "sourceHandle": "big"},
            {"id": "e3", "source": "c", "target": "b", "sourceHandle": "small"},
            {"id": "e4", "source": "a", "target": "out"},
            {"id": "e5", "source": "b", "target": "out"},
            {"id": "e6", "source": "side", "target": "out"},
        ],
    }
    app_id = make_app(client, team, graph)
    assert validate(client, team, app_id)["valid"]
    d = start(client, team, app_id, {"x": 3})
    assert d["status"] == "succeeded", d["error"]
    assert d["output"]["text"] == "작은 수/옆 갈래"
    ran = {s["node_id"] for s in d["steps"]}
    assert "a" not in ran and {"b", "side", "out"} <= ran


def test_branch_failure_stops_run_after_siblings(client: TestClient, team: Team) -> None:
    graph = _fan(1)
    graph["nodes"][4] = {"id": "tb", "type": "template", "data": {"template": "{{ nope | bad }}"}}
    app_id = make_app(client, team, graph)
    d = start(client, team, app_id, {"name": "김"})
    assert d["status"] == "failed"
    by = {s["node_id"]: s for s in d["steps"]}
    assert by["tb"]["status"] == "failed"
    assert by["ta"]["status"] == "succeeded"  # 옆 갈래는 끝까지 돌았다
    assert "j" not in by


def test_fail_route_in_parallel(client: TestClient, team: Team) -> None:
    graph = _fan(1)
    graph["nodes"][4] = {
        "id": "tb",
        "type": "template",
        "data": {
            "template": "{{ nope | bad }}",
            "_on_error": "default",
            "_default": {"output": "B 대신"},
        },
    }
    app_id = make_app(client, team, graph)
    d = start(client, team, app_id, {"name": "김"})
    assert d["status"] == "succeeded", d["error"]
    assert d["output"]["text"] == "A:김+B 대신"


def test_approval_in_one_branch_pauses_after_others(client: TestClient, team: Team) -> None:
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "name"}]}},
            {"id": "ap", "type": "approval", "data": {"message": "{{n1.name}} 승인?"}},
            {"id": "ap2", "type": "approval", "data": {"message": "두 번째 승인?"}},
            {"id": "fast", "type": "template", "data": {"template": "빠른 갈래"}},
            {
                "id": "out",
                "type": "output",
                "data": {"template": "{{fast.output}}/{{ap.approved}}/{{ap2.approved}}"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "ap"},
            {"id": "e2", "source": "n1", "target": "ap2"},
            {"id": "e3", "source": "n1", "target": "fast"},
            {"id": "e4", "source": "ap", "target": "out"},
            {"id": "e5", "source": "ap2", "target": "out"},
            {"id": "e6", "source": "fast", "target": "out"},
        ],
    }
    app_id = make_app(client, team, graph)
    assert validate(client, team, app_id)["valid"]
    d = start(client, team, app_id, {"name": "김"})
    assert d["status"] == "waiting_approval"
    by = {s["node_id"]: s for s in d["steps"]}
    assert by["fast"]["status"] == "succeeded"  # 사람을 기다리는 동안 옆 갈래는 끝났다
    first = d["approval"]["node_id"]
    assert first in ("ap", "ap2")
    h = team.h("operator")
    r = client.post(
        f"/api/v1/runs/{d['id']}/approve", json={"approved": True, "comment": "ok"}, headers=h
    )
    assert r.status_code == 200, r.text
    d = client.get(f"/api/v1/runs/{d['id']}", headers=h).json()
    # 두 번째 승인이 이어서 열린다
    assert d["status"] == "waiting_approval"
    second = d["approval"]["node_id"]
    assert second != first and second in ("ap", "ap2")
    r = client.post(
        f"/api/v1/runs/{d['id']}/approve", json={"approved": True, "comment": "ok"}, headers=h
    )
    assert r.status_code == 200, r.text
    d = client.get(f"/api/v1/runs/{d['id']}", headers=h).json()
    assert d["status"] == "succeeded", d["error"]
    assert d["output"]["text"] == "빠른 갈래/True/True"
    assert [s["node_id"] for s in d["steps"]].count("out") == 1


def test_rerun_from_branch_step(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, _fan(1))
    d = start(client, team, app_id, {"name": "김"})
    assert d["status"] == "succeeded"
    r = client.post(
        f"/api/v1/runs/{d['id']}/rerun", json={"from_node": "tb"}, headers=team.h("builder")
    )
    assert r.status_code in (200, 201), r.text
    d2 = client.get(f"/api/v1/runs/{r.json()['id']}", headers=team.h("builder")).json()
    assert d2["status"] == "succeeded", d2["error"]
    assert d2["output"]["text"] == "A:김+B:김"
    assert {s["node_id"] for s in d2["steps"]} == {"tb", "j", "out"}


def test_builder_parallel_tools(client: TestClient, team: Team) -> None:
    from api.builder.tools import BuilderToolbox
    from api.db import SessionLocal
    from api.models import App

    app_id = make_app(
        client,
        team,
        {
            "nodes": [
                {"id": "n1", "type": "input", "data": {"fields": [{"key": "m"}]}},
                {"id": "n2", "type": "output", "data": {"template": "{{n1.m}}"}},
            ],
            "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
        },
    )
    with SessionLocal() as db:
        app = db.get(App, app_id)
        assert app is not None
        tools = BuilderToolbox(db, app, team.users["builder"])
        a = tools.t_add_node(
            "template", {"label": "번역", "template": "A"}, after="n1", parallel=True
        )
        b = tools.t_add_node(
            "template", {"label": "요약", "template": "B"}, after="n1", parallel=True
        )
        na, nb = a.result["node_id"], b.result["node_id"]
        tools.t_connect(na, "n2", parallel=True)
        tools.t_connect(nb, "n2", parallel=True)
        g = tools.graph()
        outs = [e.target for e in g.edges if e.source == "n1"]
        assert sorted(outs) == sorted(["n2", na, nb])
        ins = [e.source for e in g.edges if e.target == "n2"]
        assert sorted(ins) == sorted(["n1", na, nb])
