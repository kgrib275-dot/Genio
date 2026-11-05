"""v0.8 전체 검색창(권한별 결과), 스니펫(저장·정리·권한·검사), 공개 API 문서(OpenAPI) 시험."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.engine.validator import ValidationEnv, validate_graph
from api.tests.conftest import ROLES, Team, install
from api.tests.test_v05_connectors import cred
from nodes import registry


def _kinds(data: dict[str, Any]) -> dict[str, list[str]]:
    return {g["kind"]: [i["title"] for i in g["items"]] for g in data["groups"]}


def _search(client: TestClient, team: Team, role: str, q: str, **extra: Any) -> dict[str, Any]:
    r = client.get(
        f"/api/v1/workspaces/{team.ws}/search", params={"q": q, **extra}, headers=team.h(role)
    )
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


# ---------------- 전체 검색창 ----------------
def _seed(client: TestClient, team: Team) -> dict[str, str]:
    base = f"/api/v1/workspaces/{team.ws}"
    h = team.h("builder")
    pub = client.post(f"{base}/projects", json={"name": "휴가 프로젝트"}, headers=h).json()
    priv = client.post(
        f"{base}/projects", json={"name": "휴가 비밀 프로젝트", "visibility": "private"}, headers=h
    ).json()
    shown = client.post(
        f"{base}/apps", json={"name": "휴가 신청 봇", "project_id": pub["id"]}, headers=h
    ).json()
    hidden = client.post(
        f"{base}/apps", json={"name": "휴가 몰래 앱", "project_id": priv["id"]}, headers=h
    ).json()
    draft = client.post(f"{base}/apps", json={"name": "휴가 초안"}, headers=h).json()
    for a in (shown, hidden):
        client.put(
            f"/api/v1/apps/{a['id']}/draft",
            json={"graph": make_graph()},
            headers=h,
        )
        client.post(f"/api/v1/apps/{a['id']}/versions", json={}, headers=h)
        client.post(
            f"/api/v1/apps/{a['id']}/deployments",
            json={"channel": "share_link", "access": "public"},
            headers=h,
        )
    client.post(
        f"{base}/knowledge-bases",
        json={"name": "휴가 규정 문서", "project_id": priv["id"]},
        headers=h,
    )
    client.post(f"{base}/knowledge-bases", json={"name": "휴가 규정"}, headers=h)
    client.post(
        f"{base}/data-tables",
        json={"name": "휴가 기록", "columns": [{"key": "a", "type": "text"}]},
        headers=h,
    )
    install(client, team, "slack")
    cred(client, team, "slack", "휴가 알림 슬랙", {"bot_token": "xoxb-very-secret-token-1234"})
    return {"shown": shown["id"], "hidden": hidden["id"], "draft": draft["id"]}


def make_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "m"}]}},
            {"id": "n2", "type": "output", "data": {"template": "{{n1.m}}"}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
    }


def test_search_results_by_role(client: TestClient, team: Team) -> None:
    ids = _seed(client, team)
    own = _kinds(_search(client, team, "owner", "휴가"))
    assert set(own["apps"]) == {"휴가 신청 봇", "휴가 몰래 앱", "휴가 초안"}
    assert "휴가 알림 슬랙" in own["connections"] and "휴가 기록" in own["tables"]
    assert set(own["knowledge"]) == {"휴가 규정", "휴가 규정 문서"}
    # 제작자: 연결 정보·지식베이스를 본다. 비공개 프로젝트를 만든 사람이라 모두 보임
    b = _kinds(_search(client, team, "builder", "휴가"))
    assert "휴가 몰래 앱" in b["apps"] and "connections" in b
    # 운영자: 지식베이스는 보지만 연결 정보(제작자 전용)는 못 본다. 비공개 프로젝트 것은 안 보임
    op = _kinds(_search(client, team, "operator", "휴가"))
    assert "connections" not in op
    assert set(op["knowledge"]) == {"휴가 규정"} and "휴가 몰래 앱" not in op["apps"]
    assert "휴가 비밀 프로젝트" not in op.get("projects", [])
    # 사용자: 배포된 앱만, 지식베이스·연결 정보 없음, 비공개 프로젝트 것 없음
    mem = _search(client, team, "member", "휴가")
    kinds = _kinds(mem)
    assert kinds["apps"] == ["휴가 신청 봇"]  # 배포된 앱만, 초안·비공개 제외
    assert "knowledge" not in kinds and "connections" not in kinds
    item = next(i for g in mem["groups"] if g["kind"] == "apps" for i in g["items"])
    assert item["to"].startswith("/share/")
    assert ids["shown"] != ids["hidden"]
    # 비밀값은 결과 어디에도 없다
    assert "xoxb" not in str(own)


def test_search_pages_by_role_and_ranking(client: TestClient, team: Team) -> None:
    pages = {r: _kinds(_search(client, team, r, ""))["pages"] for r in ROLES}
    assert "관리" in pages["owner"] and "관리" in pages["admin"]
    for role in ("builder", "operator", "member"):
        assert not any(p.startswith("관리") for p in pages[role]), role
    assert "지식베이스" not in pages["member"] and "지식베이스" in pages["operator"]
    assert "연결 정보" in pages["builder"] and "연결 정보" not in pages["operator"]
    admin_tab = _kinds(_search(client, team, "owner", "ai 모델"))["pages"]
    assert admin_tab == ["관리 · AI 모델"]
    assert _kinds(_search(client, team, "member", "ai 모델")) == {}
    # 이름이 검색어로 시작하는 것이 앞에 온다
    base = f"/api/v1/workspaces/{team.ws}"
    for name in ("월간 휴가 보고", "휴가 신청"):
        client.post(f"{base}/apps", json={"name": name}, headers=team.h("builder"))
    assert _kinds(_search(client, team, "builder", "휴가"))["apps"][0] == "휴가 신청"


def test_search_limits_and_validation(client: TestClient, team: Team) -> None:
    base = f"/api/v1/workspaces/{team.ws}"
    for i in range(8):
        client.post(f"{base}/apps", json={"name": f"공통 앱 {i}"}, headers=team.h("builder"))
    assert len(_kinds(_search(client, team, "builder", "공통", limit=3))["apps"]) == 3
    url = f"{base}/search"
    assert client.get(url, params={"q": "x" * 101}, headers=team.h("builder")).status_code == 422
    assert client.get(url, params={"limit": 99}, headers=team.h("builder")).status_code == 422
    # % _ 같은 글자는 그대로 글자로 찾는다(전부 일치하지 않음)
    assert _kinds(_search(client, team, "builder", "%")).get("apps", []) == []


def test_search_requires_membership(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    url = f"/api/v1/workspaces/{team.ws}/search"
    assert client.get(url).status_code == 401
    assert client.get(url, params={"q": "a"}, headers=outsider).status_code == 404


# ---------------- 스니펫 ----------------
NODES: list[dict[str, Any]] = [
    {
        "id": "n3",
        "type": "http",
        "position": {"x": 10, "y": 20},
        "data": {
            "label": "환율 가져오기",
            "method": "GET",
            "url": "https://example.com/{{n1.currency}}",
            "auth": {"type": "http_credentials", "credential_id": "cred-1"},
        },
    },
    {
        "id": "n4",
        "type": "template",
        "position": {"x": 300, "y": 20},
        "data": {"label": "정리", "template": "{{n3.body}} / {{n9.x}} / {{input.q}}"},
    },
]
EDGES: list[dict[str, Any]] = [
    {"id": "e5", "source": "n3", "target": "n4"},
    {"id": "e6", "source": "n2", "target": "n3"},  # 바깥에서 들어오는 연결
    {"id": "e7", "source": "n4", "target": "n8"},  # 바깥으로 나가는 연결
]


def _snip_url(team: Team, tail: str = "") -> str:
    return f"/api/v1/workspaces/{team.ws}/snippets{tail}"


def test_snippet_save_cleans_graph(client: TestClient, team: Team) -> None:
    r = client.post(
        _snip_url(team),
        json={
            "name": "환율 정리",
            "description": "환율을 가져와 정리",
            "nodes": NODES,
            "edges": EDGES,
        },
        headers=team.h("builder"),
    )
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["node_count"] == 2 and s["node_types"] == ["http", "template"]
    g = s["graph"]
    assert [e["id"] for e in g["edges"]] == ["e5"]  # 바깥 연결은 버린다
    http = next(n for n in g["nodes"] if n["id"] == "n3")
    assert "credential_id" not in http["data"]["auth"]  # 고르는 값은 비운다
    assert http["data"]["url"].startswith("https://example.com/{{__outer.n1.currency}}")
    tmpl = next(n for n in g["nodes"] if n["id"] == "n4")["data"]["template"]
    assert tmpl == "{{n3.body}} / {{__outer.n9.x}} / {{input.q}}"  # 안쪽·예약 값은 그대로
    assert s["reselect"] == ["환율 가져오기: 연결 정보"]
    assert sorted(s["outer_refs"]) == ["정리", "환율 가져오기"]
    # 목록에는 그래프 없이, 하나 열면 그래프까지
    lst = client.get(_snip_url(team), headers=team.h("member")).json()
    assert [x["name"] for x in lst] == ["환율 정리"] and "graph" not in lst[0]
    one = client.get(_snip_url(team, f"/{s['id']}"), headers=team.h("member")).json()
    assert len(one["graph"]["nodes"]) == 2


def test_snippet_fragment_is_valid_after_reselect(client: TestClient, team: Team) -> None:
    """끼워 넣은 단계는 '다시 골라야 하는 칸'과 바깥 값 참조만 검사에서 지적된다."""
    s = client.post(
        _snip_url(team),
        json={"name": "조각", "nodes": NODES, "edges": EDGES},
        headers=team.h("builder"),
    ).json()
    frag = s["graph"]
    host = make_graph()
    host["nodes"] += frag["nodes"]
    host["edges"] += [{"id": "ex1", "source": "n1", "target": "n3"}, *frag["edges"]]
    host["edges"].append({"id": "ex2", "source": "n4", "target": "n2"})
    env = ValidationEnv(registry=registry)
    res = validate_graph(host, env)
    msgs = [e.message for e in res.errors]
    assert any("__outer" in m for m in msgs)  # 바깥 값은 조용히 이어지지 않고 드러난다
    # 단계 형식·필수 칸 오류는 없다(연결 정보를 고르는 칸은 서버 검사 환경에 따라 별개)
    assert not any("채워 주세요" in m and "주소" in m for m in msgs)


def test_snippet_rejects_bad_input(client: TestClient, team: Team) -> None:
    h = team.h("builder")
    url = _snip_url(team)
    empty = client.post(url, json={"name": "빈", "nodes": [], "edges": []}, headers=h)
    assert empty.status_code == 422 and empty.json()["detail"]["hint"]
    with_input = client.post(
        url,
        json={"name": "시작 포함", "nodes": [make_graph()["nodes"][0]], "edges": []},
        headers=h,
    )
    assert with_input.status_code == 422 and "시작" in with_input.json()["detail"]["message"]
    bad_shape = client.post(
        url, json={"name": "이상", "nodes": [{"id": "!!", "type": "x"}], "edges": []}, headers=h
    )
    assert bad_shape.status_code == 422
    dup = client.post(
        url, json={"name": "중복", "nodes": [NODES[0], NODES[0]], "edges": []}, headers=h
    )
    assert dup.status_code == 422
    many = [{"id": f"n{i}", "type": "template", "data": {"template": "x"}} for i in range(51)]
    assert (
        client.post(url, json={"name": "많음", "nodes": many, "edges": []}, headers=h).status_code
        == 422
    )


@pytest.mark.parametrize("role", ROLES)
def test_snippet_permissions(client: TestClient, team: Team, role: str) -> None:
    body = {"name": f"스니펫-{role}", "nodes": NODES[1:], "edges": []}
    made = client.post(_snip_url(team), json=body, headers=team.h(role))
    allowed = role in ("owner", "admin", "builder")
    assert (made.status_code == 201) == allowed, (role, made.status_code)
    sid = client.post(_snip_url(team), json=body, headers=team.h("builder")).json()["id"]
    # 읽기는 모든 멤버
    assert client.get(_snip_url(team), headers=team.h(role)).status_code == 200
    assert client.get(_snip_url(team, f"/{sid}"), headers=team.h(role)).status_code == 200
    patched = client.patch(
        _snip_url(team, f"/{sid}"), json={"name": "새 이름"}, headers=team.h(role)
    )
    assert (patched.status_code == 200) == allowed
    deleted = client.delete(_snip_url(team, f"/{sid}"), headers=team.h(role))
    assert (deleted.status_code == 204) == allowed


def test_snippet_workspace_isolation(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    sid = client.post(
        _snip_url(team),
        json={"name": "비공개", "nodes": NODES[1:], "edges": []},
        headers=team.h("builder"),
    ).json()["id"]
    assert client.get(_snip_url(team, f"/{sid}"), headers=outsider).status_code == 404
    assert client.get(_snip_url(team), headers=outsider).status_code == 404
    assert client.get(_snip_url(team, "/no-such"), headers=team.h("builder")).status_code == 404


# ---------------- 공개 API 문서 ----------------
def test_public_openapi_only_public_endpoints(client: TestClient) -> None:
    r = client.get("/api/v1/openapi-public.json")  # 로그인 없이 읽는다
    assert r.status_code == 200 and r.headers["cache-control"].startswith("public")
    doc = r.json()
    paths = doc["paths"]
    assert "/api/v1/public/apps/{token}/chat" in paths
    assert "/api/v1/service/workflows/run" in paths and "/api/v1/hooks/{token}" in paths
    assert "/api/v1/service/mcp" in paths
    allowed = ("/api/v1/public/apps/", "/api/v1/service/", "/api/v1/hooks/")
    leaked = [p for p in paths if not p.startswith(allowed)]
    assert leaked == []
    # 관리·내부·그림 경로는 없다
    text = r.text
    for forbidden in (
        "/workspaces/",
        "/auth/",
        "/admin",
        "/runs/{run_id}/approve",
        "share-image",
        "share-logo",
    ):
        assert forbidden not in "".join(paths), forbidden
    assert "password_hash" not in text
    tags = {t["name"] for t in doc["tags"]}
    assert tags == {
        "공유 링크 앱(챗·입력 폼)",
        "서비스 API(앱 API 키)",
        "외부에서 받기(웹훅)",
        "MCP 서버",
    }
    chat = paths["/api/v1/public/apps/{token}/chat"]["post"]
    assert chat["summary"] == "대화 보내기(SSE로 답을 받아요)" and chat["tags"] == [
        "공유 링크 앱(챗·입력 폼)"
    ]
    # 쓰는 스키마만 들어 있다
    for name in doc["components"]["schemas"]:
        assert name in text
    assert "UserOut" not in doc["components"]["schemas"]
