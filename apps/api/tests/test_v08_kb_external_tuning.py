"""v0.8 지식베이스: 외부 지식베이스 연결, 검색 튜닝, 사용 한도, 새 API의 역할별 권한."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.engine import safe_http
from api.services import kb_tuning
from api.tests.conftest import ROLES, Team, add_llm, install
from api.tests.fakes import FakeAdapter
from api.tests.test_v05_engine import make_app, start

KEY = "tok-external-secret-9876"
ENDPOINT = "https://rag.example.com/api"


def make_kb(client: TestClient, team: Team, name: str = "자료") -> str:
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": name},
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text
    return str(r.json()["id"])


def http_cred(client: TestClient, team: Team, token: str = KEY) -> str:
    install(client, team, "http_credentials")
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={"connector_key": "http_credentials", "name": "RAG 키", "secrets": {"token": token}},
        headers=team.h("owner"),
    )
    assert r.status_code == 200, r.text
    return str(r.json()["id"])


class FakeRag:
    """고객의 검색 서비스(Dify External Knowledge API 모양)."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.status = 200
        self.records: list[dict[str, Any]] = [
            {
                "content": "연차는 입사 1년 뒤 15일입니다.",
                "score": 0.91,
                "title": "인사 규정",
                "metadata": {"부서": "인사"},
            },
            {
                "content": "재택근무는 주 2회 가능합니다.",
                "score": 0.62,
                "title": "근무 안내",
                "metadata": {},
            },
            {"content": "관련 없는 글", "score": 0.1, "title": "기타"},
        ]

    def __call__(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        self.requests.append(
            {"method": method, "url": url, "headers": kw.get("headers"), "body": kw.get("body")}
        )
        if self.status != 200:
            return {"status": self.status, "body": {"error": "x"}, "headers": {}}
        return {"status": 200, "body": {"records": self.records}, "headers": {}}


def make_external(client: TestClient, team: Team, cred: str | None = None) -> str:
    body: dict[str, Any] = {
        "name": "회사 RAG",
        "kind": "external",
        "external": {"endpoint": ENDPOINT + "/", "knowledge_id": "kb-77"},
    }
    if cred:
        body["external"]["credential_id"] = cred
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases", json=body, headers=team.h("builder")
    )
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "external"
    return str(r.json()["id"])


# ---------------- 외부 지식베이스 ----------------
def test_external_kb_request_shape_and_results(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    rag = FakeRag()
    monkeypatch.setattr(safe_http, "request", rag)
    cid = http_cred(client, team)
    kb = make_external(client, team, cid)
    h = team.h("builder")
    hits = client.post(
        f"/api/v1/knowledge-bases/{kb}/search", json={"query": "연차 며칠", "top_k": 2}, headers=h
    )
    assert hits.status_code == 200, hits.text
    out = hits.json()
    assert [x["filename"] for x in out] == ["인사 규정", "근무 안내"]
    assert out[0]["content"].startswith("연차는") and out[0]["score"] == 0.91
    assert out[0]["metadata"] == {"부서": "인사"} and out[0]["external"] is True
    req = rag.requests[-1]
    assert req["method"] == "POST" and req["url"] == ENDPOINT + "/retrieval"  # 꼬리 슬래시 정리
    assert req["body"] == {
        "knowledge_id": "kb-77",
        "query": "연차 며칠",
        "retrieval_setting": {"top_k": 2, "score_threshold": 0.0},
    }
    assert req["headers"]["Authorization"] == f"Bearer {KEY}"
    # 점수 기준을 올리면 낮은 점수는 빠진다
    out = client.post(
        f"/api/v1/knowledge-bases/{kb}/search",
        json={"query": "연차", "top_k": 5, "score_threshold": 0.7},
        headers=h,
    ).json()
    assert [x["filename"] for x in out] == ["인사 규정"]
    # API 키는 어떤 응답에도 나오지 않는다
    listing = client.get(f"/api/v1/workspaces/{team.ws}/knowledge-bases", headers=h)
    assert KEY not in listing.text and cid in listing.text
    # 문서를 올리거나 가져오는 기능은 막는다(두 줄 오류)
    for url, kw in (
        (
            f"/api/v1/knowledge-bases/{kb}/documents",
            {"files": {"file": ("a.txt", b"hello", "text/plain")}},
        ),
        (f"/api/v1/knowledge-bases/{kb}/documents/url", {"json": {"url": "https://example.com/a"}}),
        (f"/api/v1/knowledge-bases/{kb}/reprocess", {}),
        (
            f"/api/v1/knowledge-bases/{kb}/sources",
            {"json": {"type": "web", "config": {"url": "https://example.com"}}},
        ),
        (f"/api/v1/knowledge-bases/{kb}/tuning/questions", None),
    ):
        if kw is None:
            r = client.put(url, json={"questions": []}, headers=h)
        else:
            r = client.post(url, headers=h, **kw)
        assert r.status_code == 409, (url, r.status_code)
        assert r.json()["detail"]["message"] and r.json()["detail"]["hint"]
    assert client.get(f"/api/v1/knowledge-bases/{kb}/documents", headers=h).json() == []


def test_external_kb_validation_and_connection_test(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    rag = FakeRag()
    monkeypatch.setattr(safe_http, "request", rag)
    h = team.h("builder")
    url = f"/api/v1/workspaces/{team.ws}/knowledge-bases"
    for bad in (
        {"name": "x", "kind": "external"},
        {
            "name": "x",
            "kind": "external",
            "external": {"endpoint": "ftp://rag", "knowledge_id": "k"},
        },
        {
            "name": "x",
            "kind": "external",
            "external": {"endpoint": ENDPOINT, "knowledge_id": "k", "credential_id": "nope"},
        },
    ):
        r = client.post(url, json=bad, headers=h)
        assert r.status_code == 422, (bad, r.text)
        assert r.json()["detail"]["message"] and r.json()["detail"]["hint"]
    # 연결 시험: 저장 전 / 저장 후
    cid = http_cred(client, team)
    test_url = f"{url}/external/test"
    ok = client.post(
        test_url,
        json={"endpoint": ENDPOINT + "/retrieval", "knowledge_id": "kb-77", "credential_id": cid},
        headers=h,
    ).json()
    assert ok["ok"] is True and ok["records"] == 3 and ok["sample"][0]["title"] == "인사 규정"
    assert rag.requests[-1]["url"] == ENDPOINT + "/retrieval"  # /retrieval이 겹쳐 붙지 않는다
    kb = make_external(client, team, cid)
    saved = client.post(f"/api/v1/knowledge-bases/{kb}/external/test", headers=h).json()
    assert saved["ok"] is True
    for status, word in ((401, "API 키"), (404, "주소"), (500, "오류")):
        rag.status = status
        bad = client.post(f"/api/v1/knowledge-bases/{kb}/external/test", headers=h).json()
        assert bad["ok"] is False and word in bad["message"] and bad["hint"]
        assert KEY not in json.dumps(bad)
    rag.status = 200
    # 응답 형식이 다르면 안내
    monkeypatch.setattr(
        safe_http, "request", lambda *a, **k: {"status": 200, "body": {"data": []}, "headers": {}}
    )
    wrong = client.post(f"/api/v1/knowledge-bases/{kb}/external/test", headers=h).json()
    assert wrong["ok"] is False and "records" in wrong["message"]
    # 주소 바꾸기
    monkeypatch.setattr(safe_http, "request", rag)
    r = client.put(
        f"/api/v1/knowledge-bases/{kb}/external",
        json={"endpoint": "https://rag2.example.com", "knowledge_id": "kb-2"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["endpoint"] == "https://rag2.example.com"
    # 일반 지식베이스에는 외부 시험을 쓸 수 없다
    plain = make_kb(client, team)
    assert (
        client.post(f"/api/v1/knowledge-bases/{plain}/external/test", headers=h).status_code == 409
    )


def test_external_kb_in_knowledge_search_node(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    rag = FakeRag()
    monkeypatch.setattr(safe_http, "request", rag)
    kb = make_external(client, team, http_cred(client, team))
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "message"}]}},
            {
                "id": "n2",
                "type": "knowledge_search",
                "data": {"kb_id": kb, "query": "{{n1.message}}", "top_k": 2},
            },
            {"id": "n3", "type": "output", "data": {"template": "{{n2.context}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
        ],
    }
    app_id = make_app(client, team, graph)
    d = start(client, team, app_id, {"message": "연차는?"})
    assert d["status"] == "succeeded", d["error"]
    text = d["output"]["text"]
    assert "[1] 연차는 입사 1년 뒤 15일입니다." in text and "[2] 재택근무" in text
    step = next(s for s in d["steps"] if s["node_id"] == "n2")
    assert step["output"]["results"][0]["filename"] == "인사 규정"
    assert rag.requests[-1]["body"]["query"] == "연차는?"
    # 서비스가 오류를 내면 실행이 두 줄 안내로 실패한다
    rag.status = 401
    d = start(client, team, app_id, {"message": "연차는?"})
    assert d["status"] == "failed" and "API 키" in d["error"]


# ---------------- 검색 튜닝 ----------------
def put_doc(client: TestClient, team: Team, kb: str, name: str, text: str) -> str:
    r = client.post(
        f"/api/v1/knowledge-bases/{kb}/documents",
        files={"file": (name, text.encode(), "text/plain")},
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text
    return str(r.json()["id"])


def test_tuning_flow(client: TestClient, team: Team, fake_llm: FakeAdapter) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = make_kb(client, team)
    h = team.h("builder")
    put_doc(client, team, kb, "연차.txt", "연차는 입사 1년 뒤 15일입니다. 반차도 쓸 수 있어요.")
    remote = put_doc(
        client, team, kb, "재택.txt", "재택근무는 주 2회까지 가능합니다. 신청은 전날까지 해요."
    )
    base = f"/api/v1/knowledge-bases/{kb}/tuning"
    t = client.get(base, headers=h).json()
    assert t["questions"] == [] and t["max_questions"] == 30
    assert t["estimate"]["with_rerank"]["rerank_llm_calls"] == 0
    # 질문을 넣는다: 낱말로, 문서로
    saved = client.put(
        base + "/questions",
        json={
            "questions": [
                {"question": "연차는 며칠인가요?", "expect_keyword": "15일"},
                {"question": "재택근무 가능해요?", "expect_document_id": remote},
                {"question": "   "},
            ]
        },
        headers=h,
    )
    assert saved.status_code == 200, saved.text
    qs = saved.json()["questions"]
    assert len(qs) == 2 and qs[0]["id"] and saved.json()["estimate"]["questions"] == 2
    run = client.post(base + "/run", json={}, headers=h)
    assert run.status_code == 200, run.text
    res = run.json()
    assert res["questions"] == 2 and len(res["rows"]) == 9 and res["include_rerank"] is False
    assert {(r["method"], r["top_k"]) for r in res["rows"]} == {
        (m, k) for m in ("vector", "keyword", "hybrid") for k in (3, 5, 8)
    }
    assert sum(1 for r in res["rows"] if r["is_best"]) == 1
    assert res["best"]["hit_rate"] == 1.0  # 문서가 둘뿐이라 3개만 봐도 다 찾는다
    assert all("hit_scores" not in r for r in res["rows"])
    # 지금 설정(의미·4개)은 표 조합에 없어서, 같은 결과로 계산한 '현재 설정' 줄을 따로 준다
    assert not any(r["is_current"] for r in res["rows"])
    cur = res["current_row"]
    assert (cur["method"], cur["top_k"], cur["rerank"]) == ("vector", 4, False) and cur[
        "is_current"
    ]
    # 마지막 결과는 저장돼 다시 열어도 보인다
    again = client.get(base, headers=h).json()
    assert again["last_run"]["best"] == res["best"] and again["current"]["method"] == "vector"
    # 재정렬은 비용 확인이 있어야 하고, 켜면 12개 조합
    need = client.post(base + "/run", json={"include_rerank": True}, headers=h)
    assert (
        need.status_code == 422
        and "비용" in need.json()["detail"]["message"] + need.json()["detail"]["hint"]
    )
    with_rr = client.post(
        base + "/run", json={"include_rerank": True, "confirm_rerank": True}, headers=h
    )
    assert with_rr.status_code == 200, with_rr.text
    assert len(with_rr.json()["rows"]) == 12
    assert sum(1 for r in with_rr.json()["rows"] if r["rerank"]) == 3
    # 이 설정으로 적용: 기존 설정 저장(PATCH)을 그대로 쓴다
    best = res["best"]
    patched = client.patch(
        f"/api/v1/knowledge-bases/{kb}",
        json={
            "settings": {
                "retrieval": {
                    "method": best["method"],
                    "top_k": best["top_k"],
                    "rerank": best["rerank"],
                }
            }
        },
        headers=h,
    )
    assert patched.json()["settings"]["retrieval"]["top_k"] == best["top_k"]


def test_tuning_validation(client: TestClient, team: Team) -> None:
    kb = make_kb(client, team)
    h = team.h("builder")
    base = f"/api/v1/knowledge-bases/{kb}/tuning"
    # 정답 표시가 없으면 거절
    r = client.put(base + "/questions", json={"questions": [{"question": "연차?"}]}, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["hint"]
    # 없는 문서
    r = client.put(
        base + "/questions",
        json={"questions": [{"question": "연차?", "expect_document_id": "no-doc"}]},
        headers=h,
    )
    assert r.status_code == 422
    # 31개는 거절
    many = [{"question": f"질문 {i}", "expect_keyword": "x"} for i in range(31)]
    assert client.put(base + "/questions", json={"questions": many}, headers=h).status_code == 422
    # 질문이 없으면 실행할 수 없다
    r = client.post(base + "/run", json={}, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["message"] and r.json()["detail"]["hint"]


def test_tuning_math() -> None:
    """적중률·평균 점수·평균 시간 계산."""
    qs = [
        {"question": "q1", "expect_keyword": "정답", "expect_document_id": ""},
        {"question": "q2", "expect_keyword": "", "expect_document_id": "d2"},
        {"question": "q3", "expect_keyword": "없는말", "expect_document_id": ""},
    ]

    def res(content: str, score: float, doc: str = "d1") -> dict[str, Any]:
        return {
            "content": content,
            "matched": content,
            "filename": "f",
            "score": score,
            "document_id": doc,
        }

    runs = [
        ([res("딴 글", 0.9), res("여기에 정답이 있어요", 0.5)], 10.0),  # 2번째에서 적중
        (
            [res("글", 0.8, "d9"), res("글", 0.7, "d9"), res("글", 0.6, "d2")],
            30.0,
        ),  # 3번째에서 적중
        ([res("글", 0.4)], 20.0),  # 못 찾음
    ]
    top1 = kb_tuning._row("hybrid", 1, False, runs, qs)
    assert (top1["hits"], top1["hit_rate"]) == (0, 0.0)
    top2 = kb_tuning._row("hybrid", 2, False, runs, qs)
    assert top2["hits"] == 1 and top2["hit_rate"] == round(1 / 3, 4)
    top3 = kb_tuning._row("hybrid", 3, False, runs, qs)
    assert top3["hits"] == 2 and top3["hit_rate"] == round(2 / 3, 4)
    assert top3["avg_top_score"] == round((0.9 + 0.8 + 0.4) / 3, 4)
    assert top3["avg_ms"] == 20.0 and sorted(top3["hit_scores"]) == [0.5, 0.6]
    est = kb_tuning.estimate(10)
    assert est["combos"] == 9 and est["with_rerank"]["combos"] == 12
    assert est["with_rerank"]["rerank_llm_calls"] == 30


# ---------------- 사용 한도 ----------------
def test_limits_documents_size_and_rate(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = make_kb(client, team)
    owner, builder = team.h("owner"), team.h("builder")
    usage = client.get(f"/api/v1/workspaces/{team.ws}/knowledge/usage", headers=builder).json()
    assert usage["usage"] == {"documents": 0, "bytes": 0} and usage["can_edit"] is False
    assert usage["limits"]["max_documents"] == 2000  # 기본 한도
    lim_url = f"/api/v1/workspaces/{team.ws}/knowledge/limits"
    assert client.put(lim_url, json={"max_documents": 1}, headers=builder).status_code == 403
    r = client.put(lim_url, json={"max_documents": 1, "max_writes_per_min": 0}, headers=owner)
    assert r.status_code == 200 and r.json()["limits"]["max_documents"] == 1
    put_doc(client, team, kb, "a.txt", "첫 문서입니다. 충분히 긴 글이에요.")
    blocked = client.post(
        f"/api/v1/knowledge-bases/{kb}/documents",
        files={"file": ("b.txt", b"second doc", "text/plain")},
        headers=builder,
    )
    assert blocked.status_code == 409
    d = blocked.json()["detail"]
    assert "1개" in d["message"] and "한도" in d["hint"]
    # 웹 주소·질문답 표·소스 추가도 같은 한도를 지킨다
    r = client.post(
        f"/api/v1/knowledge-bases/{kb}/documents/qa",
        files={"file": ("qa.csv", "질문,답\n연차는?,15일\n".encode(), "text/csv")},
        headers=builder,
    )
    assert r.status_code == 409
    assert (
        client.post(
            f"/api/v1/knowledge-bases/{kb}/sources",
            json={
                "type": "google",
                "config": {"urls": ["https://docs.google.com/document/d/" + "A" * 20 + "/edit"]},
            },
            headers=builder,
        ).status_code
        == 409
    )
    usage = client.get(f"/api/v1/workspaces/{team.ws}/knowledge/usage", headers=owner).json()
    assert (
        usage["usage"]["documents"] == 1
        and usage["usage"]["bytes"] > 0
        and usage["can_edit"] is True
    )
    # 크기 한도
    client.put(lim_url, json={"max_documents": 0, "max_total_mb": 0}, headers=owner)
    assert client.put(lim_url, json={"max_total_mb": 1}, headers=owner).status_code == 200
    big = b"x" * (1024 * 1024)
    r = client.post(
        f"/api/v1/knowledge-bases/{kb}/documents",
        files={"file": ("big.txt", big, "text/plain")},
        headers=builder,
    )
    assert r.status_code == 409 and "1MB" in r.json()["detail"]["message"]
    # 분당 횟수
    client.put(lim_url, json={"max_total_mb": 0, "max_writes_per_min": 2}, headers=owner)
    codes = [
        client.post(
            f"/api/v1/knowledge-bases/{kb}/documents",
            files={"file": (f"r{i}.txt", f"문서 {i}번 내용입니다".encode(), "text/plain")},
            headers=builder,
        ).status_code
        for i in range(3)
    ]
    assert codes == [200, 200, 429]


def test_limit_values_are_validated(client: TestClient, team: Team) -> None:
    url = f"/api/v1/workspaces/{team.ws}/knowledge/limits"
    owner = team.h("owner")
    assert client.put(url, json={"max_documents": -1}, headers=owner).status_code == 422
    assert client.put(url, json={"max_total_mb": "많이"}, headers=owner).status_code == 422
    ok = client.put(url, json={"max_total_mb": 500}, headers=owner).json()
    assert ok["limits"]["max_total_mb"] == 500 and ok["limits"]["max_documents"] == 2000


# ---------------- 역할별 권한 ----------------
VIEW = {"owner", "admin", "builder", "operator"}
EDIT = {"owner", "admin", "builder"}
MANAGE = {"owner", "admin"}


@pytest.mark.parametrize("role", ROLES)
def test_new_endpoints_role_matrix(client: TestClient, team: Team, role: str) -> None:
    kb = make_kb(client, team)
    h = team.h(role)
    ws = f"/api/v1/workspaces/{team.ws}"
    cases: list[tuple[str, str, dict[str, Any] | None, set[str], int]] = [
        # (메서드, 주소, 본문, 허용 역할, 허용될 때 기대하는 상태)
        ("GET", f"/api/v1/knowledge-bases/{kb}/sources", None, VIEW, 200),
        (
            "POST",
            f"/api/v1/knowledge-bases/{kb}/sources",
            {"type": "web", "config": {"url": "http://127.0.0.1/"}},
            EDIT,
            400,
        ),
        ("PATCH", f"/api/v1/knowledge-bases/{kb}/sources/nope", {"name": "x"}, EDIT, 404),
        ("DELETE", f"/api/v1/knowledge-bases/{kb}/sources/nope", None, EDIT, 404),
        ("POST", f"/api/v1/knowledge-bases/{kb}/sources/nope/sync", None, EDIT, 404),
        ("GET", f"/api/v1/knowledge-bases/{kb}/tuning", None, VIEW, 200),
        ("PUT", f"/api/v1/knowledge-bases/{kb}/tuning/questions", {"questions": []}, EDIT, 200),
        ("POST", f"/api/v1/knowledge-bases/{kb}/tuning/run", {}, EDIT, 422),
        ("POST", f"/api/v1/knowledge-bases/{kb}/external/test", None, EDIT, 409),
        (
            "PUT",
            f"/api/v1/knowledge-bases/{kb}/external",
            {"endpoint": ENDPOINT, "knowledge_id": "k"},
            EDIT,
            409,
        ),
        (
            "POST",
            f"{ws}/knowledge-bases/external/test",
            {"endpoint": "ftp://x", "knowledge_id": "k"},
            EDIT,
            422,
        ),
        ("GET", f"{ws}/knowledge/usage", None, VIEW, 200),
        ("PUT", f"{ws}/knowledge/limits", {}, MANAGE, 200),
    ]
    for method, url, body, allowed, ok_status in cases:
        r = client.request(method, url, json=body, headers=h)
        want = ok_status if role in allowed else 403
        assert r.status_code == want, (role, method, url, r.status_code, r.text[:200])


def test_outsider_cannot_reach_other_workspace(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    kb = make_kb(client, team)
    for method, url in (
        ("GET", f"/api/v1/knowledge-bases/{kb}/sources"),
        ("GET", f"/api/v1/knowledge-bases/{kb}/tuning"),
        ("POST", f"/api/v1/knowledge-bases/{kb}/tuning/run"),
        ("GET", f"/api/v1/workspaces/{team.ws}/knowledge/usage"),
        ("PUT", f"/api/v1/workspaces/{team.ws}/knowledge/limits"),
    ):
        r = client.request(method, url, json={} if method != "GET" else None, headers=outsider)
        assert r.status_code == 404, (method, url, r.status_code)
