"""v0.8 일괄 실행: 양식·미리 보기(CSV·XLSX), 줄마다 실행, 동시 실행 한도, 취소, 결과 CSV,
공유 링크 한도·접근 권한, 역할별 권한."""

import io
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from api.engine.executor import execute_run
from api.services import queue
from api.tests.conftest import ROLES, Team

GRAPH: dict[str, Any] = {
    "nodes": [
        {
            "id": "n1",
            "type": "input",
            "data": {
                "label": "입력",
                "fields": [
                    {"key": "name", "label": "이름", "type": "text", "required": True},
                    {"key": "qty", "label": "수량", "type": "number", "required": False},
                ],
            },
        },
        {"id": "n2", "type": "template", "data": {"template": "{{n1.name}}: {{ 100 // n1.qty }}"}},
        {"id": "n3", "type": "output", "data": {"template": "{{n2.output}}"}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ],
}


def _make(
    client: TestClient, team: Team, graph: dict[str, Any] | None = None, *, kind: str = "workflow"
) -> str:
    h = team.h("builder")
    app_id: str = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "일괄 시험", "type": kind}, headers=h
    ).json()["id"]
    r = client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": graph or GRAPH}, headers=h)
    assert r.status_code == 200, r.text
    return app_id


def _share(client: TestClient, team: Team, app_id: str, access: str = "public") -> str:
    h = team.h("builder")
    assert client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=h).status_code == 201
    body: dict[str, Any] = {"channel": "share_link", "access": access}
    if access == "roles":
        body["allowed_roles"] = ["member"]
    r = client.post(f"/api/v1/apps/{app_id}/deployments", json=body, headers=h)
    assert r.status_code == 201, r.text
    return str(r.json()["public_token"])


def _csv(rows: list[str], header: str = "이름,수량") -> bytes:
    return ("﻿" + header + "\n" + "\n".join(rows) + "\n").encode("utf-8")


def _preview(
    client: TestClient, team: Team, app_id: str, data: bytes, name: str = "rows.csv"
) -> Any:
    return client.post(
        f"/api/v1/apps/{app_id}/batches/preview",
        files={"file": (name, io.BytesIO(data), "text/csv")},
        headers=team.h("builder"),
    )


def _rows(n: int) -> list[dict[str, Any]]:
    return [{"row": i + 2, "values": {"name": f"고객{i}", "qty": i + 1}} for i in range(n)]


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """큐에 넣는 것만 기록하고 실제로는 실행하지 않는다(동시 실행 한도·취소 시험용)."""
    sent: list[str] = []
    monkeypatch.setattr(queue, "enqueue_run", lambda run_id: sent.append(run_id))
    return sent


# ---------------- 양식·미리 보기 ----------------
def test_template_and_preview(client: TestClient, team: Team) -> None:
    app_id = _make(client, team)
    r = client.get(f"/api/v1/apps/{app_id}/batches/template.csv", headers=team.h("builder"))
    assert r.status_code == 200 and r.content.startswith(b"\xef\xbb\xbf")
    assert r.content.decode("utf-8-sig").strip() == "이름,수량"
    assert "attachment" in r.headers["content-disposition"]

    data = _csv(["김,5", ",3", "박,많이", "이,"], header="이름,수량,메모")
    p = _preview(client, team, app_id, data).json()
    assert p["total"] == 4 and p["ok_count"] == 2 and p["error_count"] == 2
    assert p["unmatched"] == ["메모"]
    by = {x["row"]: x for x in p["rows"]}
    assert by[2]["values"] == {"name": "김", "qty": 5} and not by[2]["errors"]
    e3 = by[3]["errors"][0]
    assert "이름" in e3["message"] and e3["hint"]
    e4 = by[4]["errors"][0]
    assert "숫자" in e4["message"] and e4["hint"]
    assert by[5]["values"] == {"name": "이"}  # 빈 선택 칸은 값 없음


def test_preview_xlsx_and_cp949(client: TestClient, team: Team) -> None:
    app_id = _make(client, team)
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["수량", "이름"])  # 열 순서가 달라도 머리글 이름으로 맞춘다
    ws.append([4, "최"])
    ws.append([None, None])  # 빈 줄은 건너뛴다
    buf = io.BytesIO()
    wb.save(buf)
    p = client.post(
        f"/api/v1/apps/{app_id}/batches/preview",
        files={"file": ("rows.xlsx", buf.getvalue(), "application/octet-stream")},
        headers=team.h("builder"),
    ).json()
    assert p["total"] == 1 and p["rows"][0]["values"] == {"name": "최", "qty": 4}
    kr = "이름,수량\n정,7\n".encode("cp949")  # 한국어 엑셀이 저장하는 CSV
    p2 = _preview(client, team, app_id, kr).json()
    assert p2["rows"][0]["values"] == {"name": "정", "qty": 7}


def test_preview_errors_are_two_lines(client: TestClient, team: Team) -> None:
    app_id = _make(client, team)
    for data, name, code in (
        (b"abc", "x.pdf", 415),
        (_csv([], header="이름,수량").replace(b"\n\n", b"\n"), "x.csv", 422),
        (_csv(["1"], header="번호"), "x.csv", 422),  # 필수 열 없음
        (_csv([f"a{i},1" for i in range(201)]), "x.csv", 422),  # 200줄 넘음
    ):
        r = _preview(client, team, app_id, data, name)
        assert r.status_code == code, r.text
        d = r.json()["detail"]
        assert d["message"] and d["hint"]


def test_chat_and_file_apps_rejected(client: TestClient, team: Team) -> None:
    chat = _make(client, team, kind="chat")
    r = client.get(f"/api/v1/apps/{chat}/batches/template.csv", headers=team.h("builder"))
    assert r.status_code == 422 and r.json()["detail"]["hint"]
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "f", "type": "file"}]}},
            {"id": "n2", "type": "output", "data": {"template": "끝"}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
    }
    app_id = _make(client, team, graph)
    r = client.get(f"/api/v1/apps/{app_id}/batches/template.csv", headers=team.h("builder"))
    assert r.status_code == 422 and "파일" in r.json()["detail"]["message"]


# ---------------- 실행·결과 ----------------
def test_run_batch_and_results(client: TestClient, team: Team) -> None:
    app_id = _make(client, team)
    rows = [*_rows(12), {"row": 99, "values": {"name": "=SUM(A1)", "qty": 4}}]
    r = client.post(
        f"/api/v1/apps/{app_id}/batches", json={"rows": rows}, headers=team.h("builder")
    )
    assert r.status_code == 201, r.text
    bid = r.json()["batch_id"]
    assert r.json()["total"] == 13
    st = client.get(f"/api/v1/apps/{app_id}/batches/{bid}", headers=team.h("operator")).json()
    assert st["done"] and st["total"] == 13 and st["counts"]["succeeded"] == 13
    assert st["rows"][0]["row"] == 2 and st["rows"][0]["text"] == "고객0: 100"
    assert st["rows"][0]["run_id"]
    csv_r = client.get(
        f"/api/v1/apps/{app_id}/batches/{bid}/results.csv", headers=team.h("operator")
    )
    text = csv_r.content.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0] == "줄,상태,이름,수량,결과,오류"
    assert lines[1].startswith("2,성공,고객0,1,고객0: 100")
    assert "'=SUM(A1)" in text  # 수식으로 실행되지 않게 앞에 작은따옴표
    assert csv_r.content.startswith(b"\xef\xbb\xbf")
    # 실행 목록에는 '일괄'로 남는다
    runs = client.get(f"/api/v1/apps/{app_id}/runs?limit=50", headers=team.h("builder")).json()
    assert {x["trigger"] for x in runs} == {"batch"}


def test_failed_row_does_not_stop_batch(client: TestClient, team: Team) -> None:
    app_id = _make(client, team)
    rows = [
        {"row": 2, "values": {"name": "가", "qty": 5}},
        {"row": 3, "values": {"name": "나", "qty": 0}},  # 0으로 나눠 실패
        {"row": 4, "values": {"name": "다", "qty": 4}},
    ]
    bid = client.post(
        f"/api/v1/apps/{app_id}/batches", json={"rows": rows}, headers=team.h("builder")
    ).json()["batch_id"]
    st = client.get(f"/api/v1/apps/{app_id}/batches/{bid}", headers=team.h("builder")).json()
    assert st["done"] and st["counts"]["succeeded"] == 2 and st["counts"]["failed"] == 1
    bad = next(x for x in st["rows"] if x["status"] == "failed")
    assert bad["row"] == 3 and bad["error"]["message"]
    csv_text = client.get(
        f"/api/v1/apps/{app_id}/batches/{bid}/results.csv", headers=team.h("builder")
    ).content.decode("utf-8-sig")
    assert "3,실패,나,0" in csv_text


def test_invalid_rows_rejected_or_skipped(client: TestClient, team: Team) -> None:
    app_id = _make(client, team)
    rows = [{"row": 2, "values": {"name": "가", "qty": 5}}, {"row": 3, "values": {"qty": 1}}]
    r = client.post(
        f"/api/v1/apps/{app_id}/batches", json={"rows": rows}, headers=team.h("builder")
    )
    assert r.status_code == 422 and r.json()["detail"]["hint"]
    r = client.post(
        f"/api/v1/apps/{app_id}/batches",
        json={"rows": rows, "skip_invalid": True},
        headers=team.h("builder"),
    )
    assert r.status_code == 201 and r.json()["total"] == 1


def test_concurrency_cap_and_progressive_dispatch(
    client: TestClient, team: Team, held: list[str]
) -> None:
    app_id = _make(client, team)
    bid = client.post(
        f"/api/v1/apps/{app_id}/batches", json={"rows": _rows(12)}, headers=team.h("builder")
    ).json()["batch_id"]
    assert len(held) == 5  # 한 번에 5줄만 큐에 넣는다
    st = client.get(f"/api/v1/apps/{app_id}/batches/{bid}", headers=team.h("builder")).json()
    assert st["counts"]["queued"] == 12 and not st["done"]
    assert len(held) == 5  # 상태를 물어도 한도를 넘기지 않는다
    execute_run(held[0])  # 한 줄이 끝나면
    assert len(held) == 6  # 다음 한 줄이 큐에 들어간다
    for rid in list(held[1:6]):
        execute_run(rid)
    assert len(held) == 11
    st = client.get(f"/api/v1/apps/{app_id}/batches/{bid}", headers=team.h("builder")).json()
    assert st["counts"]["succeeded"] == 6 and not st["done"]


def test_cancel_stops_unstarted_rows(client: TestClient, team: Team, held: list[str]) -> None:
    app_id = _make(client, team)
    bid = client.post(
        f"/api/v1/apps/{app_id}/batches", json={"rows": _rows(8)}, headers=team.h("builder")
    ).json()["batch_id"]
    r = client.post(f"/api/v1/apps/{app_id}/batches/{bid}/cancel", headers=team.h("builder"))
    assert r.status_code == 200 and r.json()["cancelled"] == 8  # 아직 시작한 줄이 없어 모두 취소
    st = client.get(f"/api/v1/apps/{app_id}/batches/{bid}", headers=team.h("builder")).json()
    assert st["cancelled"] and st["counts"]["cancelled"] == 8 and st["done"]
    assert len(held) == 5  # 취소한 뒤에는 더 넣지 않는다
    execute_run(held[0])  # 취소한 줄은 다시 시작되지 않는다
    assert len(held) == 5


def test_recovers_when_notification_is_missed(
    client: TestClient, team: Team, held: list[str]
) -> None:
    """줄이 끝났다는 알림을 놓쳐도 상태를 물을 때 다음 줄을 이어서 넣는다."""
    from api.db import SessionLocal
    from api.models import Run

    app_id = _make(client, team)
    bid = client.post(
        f"/api/v1/apps/{app_id}/batches", json={"rows": _rows(7)}, headers=team.h("builder")
    ).json()["batch_id"]
    with SessionLocal() as db:  # 알림 없이 두 줄을 끝낸 상태를 만든다
        for rid in held[:2]:
            run = db.get(Run, rid)
            assert run is not None
            run.status = "succeeded"
            run.output = {"text": "ok"}
        db.commit()
    client.get(f"/api/v1/apps/{app_id}/batches/{bid}", headers=team.h("builder"))
    assert len(held) == 7


# ---------------- 권한 ----------------
@pytest.mark.parametrize("role", ROLES)
def test_batch_permissions(client: TestClient, team: Team, role: str) -> None:
    app_id = _make(client, team)
    r = client.post(f"/api/v1/apps/{app_id}/batches", json={"rows": _rows(1)}, headers=team.h(role))
    assert (r.status_code == 201) == (role in ("owner", "admin", "builder")), (role, r.status_code)
    bid = client.post(
        f"/api/v1/apps/{app_id}/batches", json={"rows": _rows(1)}, headers=team.h("builder")
    ).json()["batch_id"]
    g = client.get(f"/api/v1/apps/{app_id}/batches/{bid}", headers=team.h(role))
    assert (g.status_code == 200) == (role in ("owner", "admin", "builder", "operator"))
    c = client.post(f"/api/v1/apps/{app_id}/batches/{bid}/cancel", headers=team.h(role))
    assert (c.status_code == 200) == (role in ("owner", "admin", "builder"))


def test_outsider_cannot_read_batch(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    app_id = _make(client, team)
    bid = client.post(
        f"/api/v1/apps/{app_id}/batches", json={"rows": _rows(1)}, headers=team.h("builder")
    ).json()["batch_id"]
    for path in (f"/batches/{bid}", f"/batches/{bid}/results.csv", "/batches/template.csv"):
        r = client.get(f"/api/v1/apps/{app_id}{path}", headers=outsider)
        assert r.status_code in (403, 404), path
    assert client.get(f"/api/v1/apps/{app_id}/batches/{bid}").status_code == 401


# ---------------- 공유 링크 ----------------
def test_public_batch_flow(client: TestClient, team: Team) -> None:
    app_id = _make(client, team)
    token = _share(client, team, app_id)
    base = f"/api/v1/public/apps/{token}/batches"
    t = client.get(f"{base}/template.csv")
    assert t.status_code == 200 and t.content.decode("utf-8-sig").strip() == "이름,수량"
    p = client.post(
        f"{base}/preview", files={"file": ("r.csv", _csv(["김,5", "박,0"]), "text/csv")}
    )
    assert p.status_code == 200 and p.json()["max_rows"] == 50 and p.json()["total"] == 2
    rows = [
        {"row": 2, "values": {"name": "김", "qty": 5}},
        {"row": 3, "values": {"name": "박", "qty": 0}},
    ]
    r = client.post(base, json={"rows": rows})
    assert r.status_code == 201, r.text
    bid = r.json()["batch_id"]
    st = client.get(f"{base}/{bid}").json()
    assert st["done"] and st["counts"]["succeeded"] == 1 and st["counts"]["failed"] == 1
    assert "run_id" not in st["rows"][0]
    bad = next(x for x in st["rows"] if x["status"] == "failed")
    assert "ZeroDivision" not in str(bad) and bad["error"]["hint"]  # 내부 오류 원문은 보내지 않는다
    res = client.get(f"{base}/{bid}/results.csv")
    assert res.status_code == 200 and "김: 20" in res.content.decode("utf-8-sig")


def test_public_limits(client: TestClient, team: Team, held: list[str]) -> None:
    app_id = _make(client, team)
    token = _share(client, team, app_id)
    base = f"/api/v1/public/apps/{token}/batches"
    too_many = [{"values": {"name": f"a{i}", "qty": 1}} for i in range(51)]
    r = client.post(base, json={"rows": too_many})
    assert r.status_code == 422 and "50" in r.json()["detail"]["message"]
    one = {"rows": [{"values": {"name": "a", "qty": 1}}]}
    for _ in range(3):
        assert client.post(base, json=one).status_code == 201
    r = client.post(base, json=one)  # 끝나지 않은 일괄 실행이 3개 → 더 못 만든다
    assert r.status_code == 429 and r.json()["detail"]["hint"]
    # 챗 앱은 공유 링크에서도 일괄 실행을 쓸 수 없다
    chat = _make(client, team, kind="chat")
    ctoken = _share(client, team, chat)
    r = client.get(f"/api/v1/public/apps/{ctoken}/batches/template.csv")
    assert r.status_code == 422


def test_public_rate_limit(client: TestClient, team: Team, held: list[str]) -> None:
    app_id = _make(client, team)
    token = _share(client, team, app_id)
    data = _csv(["김,5"])
    codes = [
        client.post(
            f"/api/v1/public/apps/{token}/batches/preview",
            files={"file": ("r.csv", data, "text/csv")},
        ).status_code
        for _ in range(8)
    ]
    assert codes[:6] == [200] * 6 and 429 in codes[6:]


def test_public_access_rules(client: TestClient, team: Team) -> None:
    app_id = _make(client, team)
    token = _share(client, team, app_id, access="roles")
    base = f"/api/v1/public/apps/{token}/batches"
    r = client.get(f"{base}/template.csv")
    assert r.status_code == 401 and r.json()["detail"]["hint"]  # 로그인한 멤버만
    r = client.get(f"{base}/template.csv", headers=team.h("member"))
    assert r.status_code == 200
    r = client.post(
        base, json={"rows": [{"values": {"name": "김", "qty": 1}}]}, headers=team.h("member")
    )
    assert r.status_code == 201


def test_batch_is_scoped_to_its_app(client: TestClient, team: Team) -> None:
    a = _make(client, team)
    b = _make(client, team)
    tb = _share(client, team, b)
    bid = client.post(
        f"/api/v1/apps/{a}/batches", json={"rows": _rows(1)}, headers=team.h("builder")
    ).json()["batch_id"]
    # 다른 앱의 공유 링크로는 그 일괄 실행을 볼 수 없다
    r = client.get(f"/api/v1/public/apps/{tb}/batches/{bid}")
    assert r.status_code == 404
    r = client.post(f"/api/v1/public/apps/{tb}/batches/{bid}/cancel")
    assert r.status_code == 404
    assert (
        client.get(f"/api/v1/apps/{b}/batches/{bid}", headers=team.h("builder")).status_code == 404
    )
