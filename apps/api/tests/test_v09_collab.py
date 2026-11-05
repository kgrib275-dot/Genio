"""v0.9 동시 편집(접속 표시·작업본 번호·3자 합치기·알림 스트림)과 캔버스 댓글."""

import copy
import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.builder.tools import BuilderToolbox
from api.db import SessionLocal
from api.engine import app_bus
from api.models import App, AuditLog, DraftSnapshot
from api.routers import collab as collab_router
from api.services import mailer, presence
from api.services.graph_merge import merge_graphs
from api.tests.conftest import ROLES, Team
from api.tests.test_v05_engine import make_app

GRAPH: dict[str, Any] = {
    "version": 1,
    "nodes": [
        {"id": "n1", "type": "input", "position": {"x": 0, "y": 0}, "data": {"fields": []}},
        {
            "id": "n2",
            "type": "template",
            "position": {"x": 300, "y": 0},
            "data": {"label": "다듬기", "template": "A {{n1.message}}"},
        },
        {
            "id": "n3",
            "type": "output",
            "position": {"x": 600, "y": 0},
            "data": {"label": "결과", "template": "{{n2.output}}"},
        },
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ],
    "variables": {},
}


def _g(**changes: Any) -> dict[str, Any]:
    g = copy.deepcopy(GRAPH)
    for n in g["nodes"]:
        if n["id"] in changes:
            n["data"].update(changes[n["id"]])
    return g


@pytest.fixture(autouse=True)
def _clean_buses() -> None:
    app_bus.reset_local()
    presence.reset_local()


def _put(
    client: TestClient,
    team: Team,
    app_id: str,
    graph: dict[str, Any],
    role: str = "builder",
    **extra: Any,
) -> Any:
    return client.put(
        f"/api/v1/apps/{app_id}/draft", json={"graph": graph, **extra}, headers=team.h(role)
    )


def _rev(client: TestClient, team: Team, app_id: str) -> int:
    d = client.get(f"/api/v1/apps/{app_id}", headers=team.h("builder")).json()
    return int(d["draft_rev"])


# ---------------- 3자 합치기(순수 함수) ----------------
def test_merge_disjoint_nodes_and_fields() -> None:
    base = GRAPH
    mine = _g(n2={"template": "B {{n1.message}}"})
    theirs = _g(n3={"template": "끝 {{n2.output}}"})
    res = merge_graphs(base, mine, theirs)
    assert res.conflicts == [] and res.auto_merged
    nodes = {n["id"]: n for n in res.merged["nodes"]}
    assert nodes["n2"]["data"]["template"].startswith("B ")
    assert nodes["n3"]["data"]["template"].startswith("끝 ")

    # 같은 단계의 서로 다른 칸
    mine = _g(n2={"label": "내 이름"})
    theirs = _g(n2={"template": "상대 글"})
    res = merge_graphs(base, mine, theirs)
    n2 = next(n for n in res.merged["nodes"] if n["id"] == "n2")
    assert res.conflicts == []
    assert n2["data"]["label"] == "내 이름" and n2["data"]["template"] == "상대 글"


def test_merge_same_field_conflict_and_position_rule() -> None:
    mine = _g(n2={"template": "내 글"})
    theirs = _g(n2={"template": "상대 글"})
    res = merge_graphs(GRAPH, mine, theirs)
    assert len(res.conflicts) == 1
    c = res.conflicts[0]
    assert (c["node_id"], c["field"], c["mine"], c["theirs"]) == (
        "n2",
        "data.template",
        "내 글",
        "상대 글",
    )
    # 충돌 항목은 합친 결과에서 상대 값으로 둔다
    n2 = next(n for n in res.merged["nodes"] if n["id"] == "n2")
    assert n2["data"]["template"] == "상대 글"
    # 둘 다 옮기면 충돌이 아니라 내 위치
    mine = copy.deepcopy(GRAPH)
    theirs = copy.deepcopy(GRAPH)
    mine["nodes"][1]["position"] = {"x": 1, "y": 1}
    theirs["nodes"][1]["position"] = {"x": 9, "y": 9}
    res = merge_graphs(GRAPH, mine, theirs)
    assert res.conflicts == []
    assert res.merged["nodes"][1]["position"] == {"x": 1, "y": 1}


def test_merge_edges_add_remove_and_dangling() -> None:
    base = GRAPH
    # 나: n2 → n4 새 단계와 선을 더함 / 상대: 선 e2를 지움
    mine = copy.deepcopy(GRAPH)
    mine["nodes"].append(
        {"id": "n4", "type": "template", "position": {"x": 0, "y": 200}, "data": {"template": "x"}}
    )
    mine["edges"].append({"id": "e3", "source": "n2", "target": "n4"})
    theirs = copy.deepcopy(GRAPH)
    theirs["edges"] = [e for e in theirs["edges"] if e["id"] != "e2"]
    res = merge_graphs(base, mine, theirs)
    assert res.conflicts == []
    assert {e["id"] for e in res.merged["edges"]} == {"e1", "e3"}
    assert {n["id"] for n in res.merged["nodes"]} == {"n1", "n2", "n3", "n4"}
    # 내가 n3을 지우면 상대가 그대로 둔 선 e2는 끊어진 선이라 같이 사라진다
    mine = copy.deepcopy(GRAPH)
    mine["nodes"] = [n for n in mine["nodes"] if n["id"] != "n3"]
    mine["edges"] = [e for e in mine["edges"] if e["id"] != "e2"]
    theirs = copy.deepcopy(GRAPH)
    theirs["edges"].append({"id": "e9", "source": "n3", "target": "n1"})
    res = merge_graphs(base, mine, theirs)
    ids = {n["id"] for n in res.merged["nodes"]}
    assert "n3" not in ids
    assert all(e["source"] in ids and e["target"] in ids for e in res.merged["edges"])
    assert res.dropped_edges >= 1


def test_merge_deleted_vs_edited() -> None:
    mine = copy.deepcopy(GRAPH)
    mine["nodes"] = [n for n in mine["nodes"] if n["id"] != "n2"]
    mine["edges"] = []
    theirs = _g(n2={"template": "상대가 고침"})
    res = merge_graphs(GRAPH, mine, theirs)
    assert [(c["node_id"], c["field"], c["mine"]) for c in res.conflicts] == [("n2", "*", None)]
    # 반대로 상대가 지우고 내가 고침
    res = merge_graphs(GRAPH, theirs, mine)
    assert [(c["node_id"], c["field"], c["theirs"]) for c in res.conflicts] == [("n2", "*", None)]
    # 둘 다 지우면 충돌 없음
    res = merge_graphs(GRAPH, mine, copy.deepcopy(mine))
    assert res.conflicts == []


def test_merge_notes_and_variables() -> None:
    base = copy.deepcopy(GRAPH)
    base["notes"] = [{"id": "m1", "text": "메모", "position": {"x": 0, "y": 0}}]
    base["variables"] = {"a": 1}
    mine = copy.deepcopy(base)
    mine["notes"].append({"id": "m2", "text": "내 메모", "position": {"x": 1, "y": 1}})
    mine["variables"] = {"a": 1, "b": 2}
    theirs = copy.deepcopy(base)
    theirs["notes"][0]["text"] = "고친 메모"
    theirs["variables"] = {"a": 5}
    res = merge_graphs(base, mine, theirs)
    assert res.conflicts == []
    texts = {n["id"]: n["text"] for n in res.merged["notes"]}
    assert texts == {"m1": "고친 메모", "m2": "내 메모"}
    assert res.merged["variables"] == {"a": 5, "b": 2}
    theirs["variables"] = {"a": 5}
    mine["variables"] = {"a": 9}
    res = merge_graphs(base, mine, theirs)
    assert [(c["kind"], c["node_id"]) for c in res.conflicts] == [("variable", "a")]


# ---------------- 작업본 번호·저장 합치기 ----------------
def test_revision_increments_and_same_content_does_not(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    r1 = _rev(client, team, app_id)
    assert r1 >= 1
    out = _put(client, team, app_id, _g(n2={"template": "두 번째"})).json()
    assert out["draft_rev"] == r1 + 1 and out["merged"] is False
    same = _put(client, team, app_id, _g(n2={"template": "두 번째"})).json()
    assert same["draft_rev"] == r1 + 1  # 같은 내용은 번호를 올리지 않는다
    with SessionLocal() as db:
        app = db.get(App, app_id)
        assert app is not None and app.updated_by == team.users["builder"]


def test_base_rev_equal_merge_and_conflict_flow(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    base_rev = _rev(client, team, app_id)
    # 상대(관리자)가 n3을 고쳐 저장 → 번호가 올라간다
    other = _put(client, team, app_id, _g(n3={"template": "상대 결과"}), "admin").json()
    assert other["draft_rev"] == base_rev + 1
    # 나는 옛 번호 기준으로 n2를 고쳐 저장 → 겹치지 않으니 자동으로 합쳐진다
    mine = _put(client, team, app_id, _g(n2={"template": "내 글"}), base_rev=base_rev).json()
    assert mine["merged"] is True and mine["draft_rev"] == base_rev + 2
    nodes = {n["id"]: n for n in mine["draft_graph"]["nodes"]}
    assert nodes["n2"]["data"]["template"] == "내 글"
    assert nodes["n3"]["data"]["template"] == "상대 결과"
    # 이제 상대가 n2를 고치고, 나도 옛 번호로 n2의 같은 칸을 고치면 충돌(409)
    cur = _rev(client, team, app_id)
    _put(
        client,
        team,
        app_id,
        _g(n2={"template": "상대가 다시"}, n3={"template": "상대 결과"}),
        "admin",
    )
    res = _put(client, team, app_id, _g(n2={"template": "내가 다시"}), base_rev=cur)
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["message"] and detail["hint"]
    body = detail["conflict"]
    assert body["stale"] is False and body["rev"] == cur + 1
    assert [(c["node_id"], c["field"]) for c in body["conflicts"]] == [("n2", "data.template")]
    assert {"mine", "theirs", "base", "merged"} <= set(body)
    # 저장은 일어나지 않았다
    assert _rev(client, team, app_id) == cur + 1
    # 화면에서 고른 결과를 상대 번호 기준으로 다시 보내면 저장된다
    final = _g(n2={"template": "내가 다시"}, n3={"template": "상대 결과"})
    ok = _put(client, team, app_id, final, base_rev=body["rev"])
    assert ok.status_code == 200 and ok.json()["merged"] is False


def test_stale_base_cannot_merge(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    first = _rev(client, team, app_id)
    for i in range(25):
        _put(client, team, app_id, _g(n2={"template": f"버전 {i}"}), "admin")
    res = _put(client, team, app_id, _g(n3={"template": "x"}), base_rev=first)
    assert res.status_code == 409
    conflict = res.json()["detail"]["conflict"]
    assert conflict["stale"] is True and conflict["conflicts"] == []
    # 현재 번호를 기준으로 다시 보내면(내 것으로 덮어쓰기) 저장된다
    again = _put(client, team, app_id, _g(n3={"template": "x"}), base_rev=conflict["rev"])
    assert again.status_code == 200


def test_snapshot_history_is_capped_at_20(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    for i in range(24):
        _put(client, team, app_id, _g(n2={"template": f"버전 {i}"}))
    with SessionLocal() as db:
        revs = sorted(db.scalars(select(DraftSnapshot.rev).where(DraftSnapshot.app_id == app_id)))
        app = db.get(App, app_id)
        assert app is not None
        assert len(revs) == 20 and revs[-1] == app.draft_rev and revs[0] == app.draft_rev - 19


def test_old_clients_without_base_rev_still_overwrite(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    _put(client, team, app_id, _g(n2={"template": "상대"}), "admin")
    out = _put(client, team, app_id, _g(n2={"template": "옛 화면이 덮어씀"}))
    assert out.status_code == 200
    n2 = next(n for n in out.json()["draft_graph"]["nodes"] if n["id"] == "n2")
    assert n2["data"]["template"] == "옛 화면이 덮어씀"


def test_builder_agent_tools_bump_revision(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    before = _rev(client, team, app_id)
    with SessionLocal() as db:
        app = db.get(App, app_id)
        assert app is not None
        tools = BuilderToolbox(db, app, team.users["builder"])
        out = tools.t_add_node("template", {"label": "추가", "template": "x"}, after="n2")
        assert out.ok
    after = _rev(client, team, app_id)
    assert after > before
    with SessionLocal() as db:
        app = db.get(App, app_id)
        assert app is not None and app.updated_by == team.users["builder"]


def test_draft_changed_event_reaches_subscribers(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    sub = app_bus.subscribe(app_id)
    try:
        r = client.put(
            f"/api/v1/apps/{app_id}/draft",
            json={"graph": _g(n2={"template": "알림 시험"})},
            headers={**team.h("builder"), "X-Genio-Client": "tab-1"},
        )
        assert r.status_code == 200
        msg = sub.get(timeout=2)
        assert msg is not None and msg["event"] == "draft_changed"
        assert msg["data"]["rev"] == r.json()["draft_rev"]
        assert msg["data"]["client_id"] == "tab-1"
        assert msg["data"]["user_id"] == team.users["builder"]
        # 같은 내용을 다시 저장하면 알림이 없다
        client.put(
            f"/api/v1/apps/{app_id}/draft",
            json={"graph": _g(n2={"template": "알림 시험"})},
            headers=team.h("builder"),
        )
        assert sub.get(timeout=0.3) is None
    finally:
        sub.close()


# ---------------- 접속 표시 ----------------
def test_presence_expiry_unit() -> None:
    presence.touch("a1", "u1", "가나", node_id="n2", now=1000.0)
    presence.touch("a1", "u2", "다라", editing=True, now=1020.0)
    names = [e["name"] for e in presence.snapshot("a1", now=1025.0)]
    assert names == ["가나", "다라"]
    # 30초가 지난 사람은 빠진다
    assert [e["name"] for e in presence.snapshot("a1", now=1040.0)] == ["다라"]
    assert presence.snapshot("a1", now=1100.0) == []
    assert presence.color_of("u1") == presence.color_of("u1")


def test_presence_api_roles_and_isolation(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    app_id = make_app(client, team, GRAPH)
    url = f"/api/v1/apps/{app_id}/presence"
    r = client.post(url, json={"node_id": "n2", "editing": True}, headers=team.h("builder"))
    assert r.status_code == 200
    me = r.json()["users"][0]
    assert me["name"] == "builder 사용자" and me["node_id"] == "n2" and me["editing"] is True
    assert me["color"].startswith("#")
    # 운영자는 볼 수 있지만(고치는 중 표시는 못 켬), 사용자 역할과 외부인은 못 연다
    op = client.post(url, json={"editing": True}, headers=team.h("operator"))
    assert op.status_code == 200
    users = {u["name"]: u for u in op.json()["users"]}
    assert users["operator 사용자"]["editing"] is False and len(users) == 2
    assert client.get(url, headers=team.h("member")).status_code == 403
    assert client.post(url, json={}, headers=team.h("member")).status_code == 403
    assert client.get(url, headers=outsider).status_code == 404
    assert client.get(url).status_code == 401
    # 떠나면 목록에서 빠진다
    left = client.post(url, json={"leave": True}, headers=team.h("builder")).json()["users"]
    assert [u["name"] for u in left] == ["operator 사용자"]
    # 이름은 서버가 정한다(본문으로 속일 수 없다)
    spoof = client.post(
        url, json={"node_id": "n1", "name": "관리자 행세"}, headers=team.h("builder")
    )
    assert spoof.status_code == 200
    assert "관리자 행세" not in spoof.text


def test_presence_stream_delivers_events(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    frames: list[str] = []

    def reader() -> None:
        for f in collab_router._stream(app_id, 3.0):
            frames.append(f)

    t = threading.Thread(target=reader)
    t.start()
    time.sleep(0.4)
    client.post(
        f"/api/v1/apps/{app_id}/presence", json={"node_id": "n3"}, headers=team.h("builder")
    )
    _put(client, team, app_id, _g(n2={"template": "스트림 시험"}))
    client.post(
        f"/api/v1/apps/{app_id}/comments",
        json={"body": "스트림 댓글", "node_id": "n2"},
        headers=team.h("builder"),
    )
    t.join(timeout=8)
    text = "".join(frames)
    assert "event: hello" in text and "event: presence" in text
    assert "event: draft_changed" in text and "event: comment_changed" in text
    assert "builder 사용자" in text


def test_presence_stream_http_and_permissions(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    app_id = make_app(client, team, GRAPH)
    url = f"/api/v1/apps/{app_id}/presence/stream?max_seconds=0.6"
    with client.stream("GET", url, headers=team.h("builder")) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert "event: hello" in body and "event: presence" in body
    assert client.get(url, headers=team.h("member")).status_code == 403
    assert client.get(url, headers=outsider).status_code == 404


# ---------------- 댓글 ----------------
def _setup_mail(client: TestClient, team: Team) -> None:
    r = client.put(
        "/api/v1/admin/system/mail",
        json={
            "host": "smtp.example.com",
            "port": 587,
            "username": "noreply",
            "password": "smtp-pw-1234",
            "from_addr": "noreply@example.com",
            "security": "starttls",
        },
        headers=team.h("owner"),
    )
    assert r.status_code == 200, r.text


def _comment(
    client: TestClient, team: Team, app_id: str, role: str = "builder", **body: Any
) -> Any:
    payload = {"body": "여기 확인해 주세요", "node_id": "n2", **body}
    return client.post(f"/api/v1/apps/{app_id}/comments", json=payload, headers=team.h(role))


def test_comments_crud_and_threads(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    r = _comment(client, team, app_id)
    assert r.status_code == 201, r.text
    root = r.json()
    assert root["node_id"] == "n2" and root["resolved"] is False and root["replies"] == []
    assert root["author"]["name"] == "builder 사용자"
    # 답글: 위치·단계는 뿌리를 따른다
    rep = _comment(
        client, team, app_id, "admin", body="확인했어요", parent_id=root["id"], node_id="n9"
    )
    assert rep.status_code == 201
    thread = rep.json()
    assert thread["id"] == root["id"] and thread["replies"][0]["node_id"] == "n2"
    # 답글에 답글은 안 된다
    deep = _comment(client, team, app_id, body="더", parent_id=thread["replies"][0]["id"])
    assert deep.status_code == 422 and deep.json()["detail"]["hint"]
    # 자유 위치 핀
    pin = _comment(client, team, app_id, body="여긴 뭐죠", node_id=None, x=120.5, y=-30)
    assert pin.json()["x"] == 120.5 and pin.json()["node_id"] is None
    listing = client.get(f"/api/v1/apps/{app_id}/comments", headers=team.h("operator")).json()
    assert len(listing) == 2 and listing[0]["replies"][0]["body"] == "확인했어요"
    by_node = client.get(
        f"/api/v1/apps/{app_id}/comments?node_id=n2", headers=team.h("builder")
    ).json()
    assert [c["id"] for c in by_node] == [root["id"]]
    # 해결·다시 열기
    res = client.post(
        f"/api/v1/apps/{app_id}/comments/{root['id']}/resolve", headers=team.h("admin")
    )
    assert res.status_code == 200 and res.json()["resolved"] is True
    assert res.json()["resolved_by"] == "admin 사용자"
    open_ = client.get(
        f"/api/v1/apps/{app_id}/comments?status=open", headers=team.h("builder")
    ).json()
    done = client.get(
        f"/api/v1/apps/{app_id}/comments?status=resolved", headers=team.h("builder")
    ).json()
    assert [c["id"] for c in open_] == [pin.json()["id"]] and [c["id"] for c in done] == [
        root["id"]
    ]
    reopened = client.post(
        f"/api/v1/apps/{app_id}/comments/{root['id']}/reopen", headers=team.h("builder")
    )
    assert reopened.json()["resolved"] is False
    # 답글은 따로 해결할 수 없다
    bad = client.post(
        f"/api/v1/apps/{app_id}/comments/{thread['replies'][0]['id']}/resolve",
        headers=team.h("builder"),
    )
    assert bad.status_code == 422


def test_comment_edit_delete_rules(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    root = _comment(client, team, app_id).json()
    cid = root["id"]
    url = f"/api/v1/apps/{app_id}/comments/{cid}"
    # 남의 댓글은 고칠 수 없다(관리자도)
    assert client.patch(url, json={"body": "고침"}, headers=team.h("admin")).status_code == 403
    ok = client.patch(url, json={"body": "내가 고침"}, headers=team.h("builder"))
    assert ok.status_code == 200 and ok.json()["body"] == "내가 고침" and ok.json()["edited_at"]
    # 지우기: 쓴 사람 또는 소유자·관리자
    other = _comment(client, team, app_id, "builder", body="지워질 댓글").json()
    assert (
        client.delete(
            f"/api/v1/apps/{app_id}/comments/{other['id']}", headers=team.h("operator")
        ).status_code
        == 403
    )
    rep = _comment(client, team, app_id, "builder", body="답글", parent_id=cid).json()
    assert len(rep["replies"]) == 1
    assert client.delete(url, headers=team.h("admin")).status_code == 204
    left = client.get(f"/api/v1/apps/{app_id}/comments", headers=team.h("builder")).json()
    assert [c["id"] for c in left] == [other["id"]]  # 답글도 같이 사라졌다
    assert client.delete(url, headers=team.h("admin")).status_code == 404


@pytest.mark.parametrize("role", ROLES)
def test_comment_permissions_per_role(client: TestClient, team: Team, role: str) -> None:
    app_id = make_app(client, team, GRAPH)
    root = _comment(client, team, app_id).json()
    base = f"/api/v1/apps/{app_id}"
    read = client.get(f"{base}/comments", headers=team.h(role))
    assert (read.status_code == 200) == (role in ("owner", "admin", "builder", "operator"))
    write = client.post(f"{base}/comments", json={"body": "새 댓글"}, headers=team.h(role))
    assert (write.status_code == 201) == (role in ("owner", "admin", "builder"))
    resolve = client.post(f"{base}/comments/{root['id']}/resolve", headers=team.h(role))
    assert (resolve.status_code == 200) == (role in ("owner", "admin", "builder"))
    people = client.get(f"{base}/collaborators", headers=team.h(role))
    assert (people.status_code == 200) == (role in ("owner", "admin", "builder", "operator"))
    if people.status_code == 200:
        assert all(set(p) == {"id", "name", "role"} for p in people.json())
        assert {p["role"] for p in people.json()} <= {"owner", "admin", "builder", "operator"}


def test_comments_are_workspace_isolated(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    app_id = make_app(client, team, GRAPH)
    cid = _comment(client, team, app_id).json()["id"]
    base = f"/api/v1/apps/{app_id}/comments"
    assert client.get(base, headers=outsider).status_code == 404
    assert client.post(base, json={"body": "침입"}, headers=outsider).status_code == 404
    assert client.delete(f"{base}/{cid}", headers=outsider).status_code == 404
    assert client.get(base).status_code == 401
    # 다른 앱 주소로 이 댓글을 건드릴 수 없다
    other_app = make_app(client, team, GRAPH, name="다른 앱")
    assert (
        client.post(
            f"/api/v1/apps/{other_app}/comments/{cid}/resolve", headers=team.h("builder")
        ).status_code
        == 404
    )


def test_comment_validation(client: TestClient, team: Team) -> None:
    app_id = make_app(client, team, GRAPH)
    base = f"/api/v1/apps/{app_id}/comments"
    h = team.h("builder")
    assert client.post(base, json={"body": ""}, headers=h).status_code == 422
    assert client.post(base, json={"body": "   "}, headers=h).status_code == 422
    assert client.post(base, json={"body": "가" * 2001}, headers=h).status_code == 422
    assert client.post(base, json={"body": "x", "parent_id": "none"}, headers=h).status_code == 404


def test_mentions_audit_and_mail(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = make_app(client, team, GRAPH)
    box: list[dict[str, str]] = []
    monkeypatch.setattr(mailer, "OUTBOX", box)
    _setup_mail(client, team)
    admin_id, member_id = team.users["admin"], team.users["member"]
    r = _comment(
        client,
        team,
        app_id,
        body="@admin 사용자 확인 부탁",
        mentions=[admin_id, member_id, team.users["builder"], "no-such-user"],
    )
    assert r.status_code == 201
    # 빌더를 열 수 있는 사람만 인정(사용자 역할·없는 사람은 제외, 나 자신은 알리지 않음)
    assert [m["id"] for m in r.json()["mentions"]] == [admin_id, team.users["builder"]]
    with SessionLocal() as db:
        logs = list(db.scalars(select(AuditLog).where(AuditLog.action == "comment.mention")))
        assert [lg.target_id for lg in logs] == [admin_id]
        assert logs[0].meta["app_id"] == app_id
    assert len(box) == 1 and box[0]["to"] == "admin@test.local"
    assert f"/apps/{app_id}/builder" in box[0]["text"]
    assert "확인 부탁" in box[0]["text"]
    # 고칠 때 새로 넣은 사람만 알린다
    cid = r.json()["id"]
    client.patch(
        f"/api/v1/apps/{app_id}/comments/{cid}",
        json={"body": "다시 확인", "mentions": [admin_id, team.users["operator"]]},
        headers=team.h("builder"),
    )
    with SessionLocal() as db:
        targets = [
            lg.target_id
            for lg in db.scalars(select(AuditLog).where(AuditLog.action == "comment.mention"))
        ]
        assert targets == [admin_id, team.users["operator"]]


def test_mail_failure_never_blocks_comment(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = make_app(client, team, GRAPH)
    _setup_mail(client, team)

    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("SMTP 장애 smtp-secret-123")

    monkeypatch.setattr(mailer, "send", boom)
    r = _comment(client, team, app_id, mentions=[team.users["admin"]])
    assert r.status_code == 201
    assert "smtp-secret-123" not in r.text
