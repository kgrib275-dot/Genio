"""v0.8 지식 데이터 소스: 웹사이트 크롤링·Notion 동기화·공개 Google 문서(가짜 서버로 확인)."""

import json
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.db import SessionLocal
from api.engine import safe_http
from api.models import Document
from api.services import kb_crawl, kb_google, kb_notion, kb_sources
from api.tests.conftest import Team, add_llm, install
from api.tests.fakes import FakeAdapter
from nodes import NodeError


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "genio_crawl_delay_seconds", 0.0)


def html(title: str, body: str, *links: str, canonical: str | None = None) -> str:
    anchors = "".join(f'<a href="{u}">링크</a>' for u in links)
    canon = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    return (
        f"<html><head><title>{title}</title>{canon}</head>"
        f"<body><p>{body}</p>{anchors}</body></html>"
    )


BASE = "https://docs.example.com"
BODY = "이 쪽에는 지식베이스에 넣을 만큼 충분히 긴 설명 글이 들어 있어요. "


def make_site(
    extra: dict[str, tuple[int, str, str]] | None = None,
) -> dict[str, tuple[int, str, str]]:
    site: dict[str, tuple[int, str, str]] = {
        f"{BASE}/robots.txt": (200, "User-agent: *\nDisallow: /private\n", "text/plain"),
        f"{BASE}/": (
            200,
            html(
                "홈",
                BODY + "홈 쪽",
                "/a",
                "/b?utm_source=mail",
                "/a/",
                "/private/x",
                "https://other.example.com/z",
                "/file.pdf",
                "/dup",
                "mailto:me@example.com",
            ),
            "text/html; charset=utf-8",
        ),
        f"{BASE}/a": (200, html("A 쪽", BODY + "A 쪽 내용", "/c"), "text/html"),
        f"{BASE}/b": (200, html("B 쪽", BODY + "B 쪽 내용"), "text/html"),
        f"{BASE}/c": (200, html("C 쪽", BODY + "C 쪽 내용"), "text/html"),
        f"{BASE}/dup": (
            200,
            html("A 복사본", BODY + "같은 쪽", canonical="/a"),
            "text/html",
        ),
        f"{BASE}/private/x": (200, html("비공개", BODY + "보면 안 돼요"), "text/html"),
    }
    site.update(extra or {})
    return site


def install_site(
    monkeypatch: pytest.MonkeyPatch, site: dict[str, tuple[int, str, str]]
) -> list[str]:
    calls: list[str] = []

    def fake(method: str, url: str, **kw: Any) -> dict[str, Any]:
        calls.append(url)
        hit = site.get(url)
        if hit is None:
            return {"status": 404, "body": "없음", "headers": {"content-type": "text/html"}}
        status, text, ctype = hit
        return {"status": status, "body": text, "headers": {"content-type": ctype}}

    monkeypatch.setattr(safe_http, "request", fake)
    real_check = safe_http.check_url

    def fake_check(url: str, *, allowed_domains: list[str] | None = None) -> str:
        # 시험용 가짜 사이트(example.com)만 DNS 없이 통과시키고, 내부 주소는 진짜 규칙으로 막는다
        host = urlsplit(url).hostname or ""
        if host == "example.com" or host.endswith(".example.com"):
            return host
        return real_check(url, allowed_domains=allowed_domains)

    monkeypatch.setattr(safe_http, "check_url", fake_check)
    return calls


def make_kb(client: TestClient, team: Team, name: str = "자료") -> str:
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": name},
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text
    return str(r.json()["id"])


# ---------------- 크롤러(단위) ----------------
def test_canonical_urls() -> None:
    assert kb_crawl.canonical("HTTPS://Docs.Example.com:443/a/?utm_source=x&b=2&a=1#top") == (
        "https://docs.example.com/a?a=1&b=2"
    )
    assert kb_crawl.canonical("/x//y/", "https://e.com/base") == "https://e.com/x/y"
    assert kb_crawl.canonical("https://e.com") == "https://e.com/"
    assert kb_crawl.allowed("https://e.com/docs/a", ["/docs"], [])
    assert not kb_crawl.allowed("https://e.com/blog/a", ["/docs"], [])
    assert not kb_crawl.allowed("https://e.com/docs/old/a", ["/docs/*"], ["old"])


def test_crawl_depth_robots_dedupe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_site(monkeypatch, make_site())
    res = kb_crawl.crawl(BASE, depth=1, max_pages=20, delay=0)
    urls = sorted(p.url for p in res.pages)
    # 홈·A·B만(C는 깊이 2, 복사본은 정규 주소가 A라 중복, 비공개는 robots가 막음)
    assert urls == [f"{BASE}/", f"{BASE}/a", f"{BASE}/b"]
    assert res.skipped_robots == 1
    assert f"{BASE}/c" not in calls and f"{BASE}/private/x" not in calls
    assert not any("other.example.com" in c or c.endswith(".pdf") for c in calls)
    deep = kb_crawl.crawl(BASE, depth=2, max_pages=20, delay=0)
    assert f"{BASE}/c" in {p.url for p in deep.pages}
    assert kb_crawl.crawl(BASE, depth=0, max_pages=20, delay=0).pages[0].url == f"{BASE}/"


def test_crawl_page_cap_and_patterns(monkeypatch: pytest.MonkeyPatch) -> None:
    install_site(monkeypatch, make_site())
    capped = kb_crawl.crawl(BASE, depth=2, max_pages=2, delay=0)
    assert len(capped.pages) == 2 and capped.reached_limit
    # 상한(50쪽·깊이 2)은 큰 값을 줘도 넘지 않는다
    assert kb_crawl.crawl(BASE, depth=9, max_pages=999, delay=0).pages
    only_a = kb_crawl.crawl(BASE, depth=2, max_pages=20, include=["/a"], delay=0)
    assert sorted(p.url for p in only_a.pages) == [f"{BASE}/", f"{BASE}/a"]
    no_b = kb_crawl.crawl(BASE, depth=1, max_pages=20, exclude=["/b"], delay=0)
    assert f"{BASE}/b" not in {p.url for p in no_b.pages}


def test_crawl_blocks_private_addresses_for_real() -> None:
    """모의 서버 없이 진짜 safe_http: 내부 주소는 가져오지 못한다."""
    res = kb_crawl.crawl("http://localhost:9/", depth=0, max_pages=1, delay=0)
    assert not res.pages and res.failed and "내부 주소" in res.failed[0][1]
    with pytest.raises(NodeError):
        kb_crawl.validate_start("http://127.0.0.1/")


# ---------------- 웹 소스 흐름 ----------------
def add_web(client: TestClient, team: Team, kb: str, **cfg: Any) -> dict[str, Any]:
    r = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources",
        json={"type": "web", "config": {"url": BASE, "depth": 1, "max_pages": 20, **cfg}},
        headers=team.h("builder"),
    )
    assert r.status_code == 201, r.text
    out: dict[str, Any] = r.json()
    return out


def test_web_source_sync_dedupe_and_update(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    site = make_site()
    install_site(monkeypatch, site)
    kb = make_kb(client, team)
    src = add_web(client, team, kb)
    assert src["last_status"] == "ok" and src["last_summary"]["added"] == 3
    assert src["running"] is False
    docs = client.get(f"/api/v1/knowledge-bases/{kb}/documents", headers=team.h("builder")).json()
    assert len(docs) == 3 and {d["source"] for d in docs} == {"web"}
    assert all(d["status"] == "ready" and d["chunk_count"] >= 1 for d in docs)
    # 가져오기 기록(밑줄 키)은 화면에 보이지 않고, 출처 주소만 보인다
    assert all(not any(k.startswith("_") for k in d["metadata"]) for d in docs)
    assert {d["metadata"].get("source_url") for d in docs} == {BASE + "/", BASE + "/a", BASE + "/b"}

    # 다시 가져오면 문서가 늘지 않는다
    again = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources/{src['id']}/sync", headers=team.h("builder")
    )
    assert again.status_code == 202, again.text
    s = again.json()["last_summary"]
    assert (s["added"], s["updated"], s["unchanged"]) == (0, 0, 3)
    # 한 쪽이 바뀌면 그 쪽만 고친다(중복 없음)
    site[f"{BASE}/b"] = (200, html("B 쪽", BODY + "B 쪽이 새 내용으로 바뀌었어요"), "text/html")
    s = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources/{src['id']}/sync", headers=team.h("builder")
    ).json()["last_summary"]
    assert (s["added"], s["updated"], s["unchanged"]) == (0, 1, 2)
    docs = client.get(f"/api/v1/knowledge-bases/{kb}/documents", headers=team.h("builder")).json()
    assert len(docs) == 3
    with SessionLocal() as db:
        b = next(d for d in db.query(Document).all() if d.filename == "B 쪽.txt")
        assert b.content is not None and "새 내용" in b.content.decode()

    # 사람이 꼬리표를 고쳐도 가져오기 기록은 남아, 다음 동기화에서 문서가 새로 생기지 않는다
    bid = next(d["id"] for d in docs if d["filename"] == "B 쪽.txt")
    r = client.patch(
        f"/api/v1/documents/{bid}", json={"metadata": {"부서": "인사"}}, headers=team.h("builder")
    )
    assert r.status_code == 200 and r.json()["metadata"] == {"부서": "인사"}
    site[f"{BASE}/b"] = (200, html("B 쪽", BODY + "한 번 더 바뀜"), "text/html")
    client.post(f"/api/v1/knowledge-bases/{kb}/sources/{src['id']}/sync", headers=team.h("builder"))
    assert (
        len(client.get(f"/api/v1/knowledge-bases/{kb}/documents", headers=team.h("builder")).json())
        == 3
    )

    # 소스를 지울 때 문서도 같이 지울 수 있다
    r = client.delete(
        f"/api/v1/knowledge-bases/{kb}/sources/{src['id']}?delete_documents=true",
        headers=team.h("builder"),
    )
    assert r.status_code == 204
    assert (
        client.get(f"/api/v1/knowledge-bases/{kb}/documents", headers=team.h("builder")).json()
        == []
    )
    assert (
        client.get(f"/api/v1/knowledge-bases/{kb}/sources", headers=team.h("builder")).json() == []
    )


def test_web_source_validation_and_failures(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_site(monkeypatch, make_site({f"{BASE}/empty": (200, html("빈", "짧음"), "text/html")}))
    kb = make_kb(client, team)
    h = team.h("builder")
    bad = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources",
        json={"type": "web", "config": {"url": "http://127.0.0.1/"}},
        headers=h,
    )
    assert bad.status_code == 400
    assert bad.json()["detail"]["message"] and bad.json()["detail"]["hint"]
    assert (
        client.post(
            f"/api/v1/knowledge-bases/{kb}/sources",
            json={"type": "web", "config": {"url": "ftp://x"}},
            headers=h,
        ).status_code
        == 400
    )
    # 글이 거의 없는 사이트는 실패로 남고 이유를 두 줄로 알려 준다
    r = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources",
        json={"type": "web", "config": {"url": f"{BASE}/empty", "depth": 0}},
        headers=h,
    )
    assert r.status_code == 201
    assert r.json()["last_status"] == "failed" and r.json()["last_error"]
    # 알 수 없는 소스 종류는 거절
    assert (
        client.post(
            f"/api/v1/knowledge-bases/{kb}/sources", json={"type": "ftp", "config": {}}, headers=h
        ).status_code
        == 422
    )


def test_already_running_returns_409(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_site(monkeypatch, make_site())
    kb = make_kb(client, team)
    src = add_web(client, team, kb)
    with SessionLocal() as db:
        kb_sources.update_source(
            db, kb, src["id"], {"running": True, "running_since": kb_sources._iso(kb_sources.now())}
        )
    r = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources/{src['id']}/sync", headers=team.h("builder")
    )
    assert r.status_code == 409 and r.json()["detail"]["hint"]


# ---------------- Notion ----------------
TOKEN = "secret_notion_token_value_1234"  # noqa: S105
PAGE_ID = "1234567890abcdef1234567890abcdef"
OTHER_ID = "fedcba0987654321fedcba0987654321"
DB_ID = "aaaaaaaabbbbbbbbccccccccdddddddd"


def dash(i: str) -> str:
    return f"{i[:8]}-{i[8:12]}-{i[12:16]}-{i[16:20]}-{i[20:]}"


def rt(text: str) -> list[dict[str, str]]:
    return [{"plain_text": text}]


def page_obj(pid: str, title: str, edited: str) -> dict[str, Any]:
    return {
        "id": dash(pid),
        "last_edited_time": edited,
        "url": f"https://www.notion.so/{title}-{pid}",
        "properties": {"이름": {"type": "title", "title": rt(title)}},
    }


class FakeNotion:
    def __init__(self) -> None:
        self.pages: dict[str, dict[str, Any]] = {
            PAGE_ID: page_obj(PAGE_ID, "휴가 규정", "2026-11-01T00:00:00.000Z"),
        }
        self.dbs: dict[str, list[str]] = {DB_ID: [OTHER_ID]}
        self.pages[OTHER_ID] = page_obj(OTHER_ID, "복지 안내", "2026-11-02T00:00:00.000Z")
        self.children: dict[str, list[dict[str, Any]]] = {
            PAGE_ID: [
                {"id": "b1", "type": "heading_2", "heading_2": {"rich_text": rt("연차")}},
                {
                    "id": "b2",
                    "type": "paragraph",
                    "paragraph": {"rich_text": rt("입사 1년 뒤 15일")},
                },
                {
                    "id": "b3",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": rt("반차 가능")},
                    "has_children": True,
                },
                {
                    "id": "b4",
                    "type": "to_do",
                    "to_do": {"rich_text": rt("신청서 쓰기"), "checked": True},
                },
                {
                    "id": "b5",
                    "type": "code",
                    "code": {"rich_text": rt("print(1)"), "language": "python"},
                },
                {"id": "b6", "type": "table", "table": {}, "has_children": True},
            ],
            "b3": [
                {"id": "b3a", "type": "paragraph", "paragraph": {"rich_text": rt("오전·오후 선택")}}
            ],
            "b6": [
                {"id": "r1", "type": "table_row", "table_row": {"cells": [rt("종류"), rt("일수")]}},
                {"id": "r2", "type": "table_row", "table_row": {"cells": [rt("연차"), rt("15")]}},
            ],
            OTHER_ID: [
                {
                    "id": "o1",
                    "type": "paragraph",
                    "paragraph": {"rich_text": rt("복지 포인트는 연 100만 점")},
                }
            ],
        }
        self.block_calls = 0
        self.seen_headers: list[dict[str, str]] = []
        self.status_override: dict[str, int] = {}

    def __call__(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        assert url.startswith("https://api.notion.com/v1")
        assert kw.get("allowed_domains") == ["api.notion.com"]
        self.seen_headers.append(dict(kw.get("headers") or {}))
        path = url.removeprefix("https://api.notion.com/v1").split("?")[0]
        for key, code in self.status_override.items():
            if path.startswith(key):
                return {"status": code, "body": {"message": "x"}, "headers": {}}
        parts = path.strip("/").split("/")
        if parts[0] == "pages":
            page = self.pages.get(parts[1])
            return {"status": 200, "body": page, "headers": {}} if page else self._nf()
        if parts[0] == "databases" and len(parts) == 2:
            return (
                {"status": 200, "body": {"id": dash(parts[1])}, "headers": {}}
                if parts[1] in self.dbs
                else self._nf()
            )
        if parts[0] == "databases" and parts[2] == "query":
            items = [self.pages[i] for i in self.dbs[parts[1]]]
            return {"status": 200, "body": {"results": items, "has_more": False}, "headers": {}}
        if parts[0] == "blocks":
            self.block_calls += 1
            return {
                "status": 200,
                "body": {"results": self.children.get(parts[1], []), "has_more": False},
                "headers": {},
            }
        return self._nf()

    @staticmethod
    def _nf() -> dict[str, Any]:
        return {"status": 404, "body": {"message": "not found"}, "headers": {}}


def notion_cred(client: TestClient, team: Team, token: str = TOKEN) -> str:
    install(client, team, "notion")
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={"connector_key": "notion", "name": "노션", "secrets": {"token": token}},
        headers=team.h("owner"),
    )
    assert r.status_code == 200, r.text
    return str(r.json()["id"])


def test_notion_markdown_conversion() -> None:
    fake = FakeNotion()
    md = kb_notion.blocks_to_markdown(
        fake.children[PAGE_ID],
        lambda bid: fake.children.get(bid, []),
    )
    assert "## 연차" in md and "입사 1년 뒤 15일" in md
    assert "- 반차 가능" in md and "  오전·오후 선택" not in md.splitlines()[0]
    assert "- [x] 신청서 쓰기" in md and "```python\nprint(1)\n```" in md
    assert "| 종류 | 일수 |" in md and "| 연차 | 15 |" in md
    assert kb_notion.parse_target("https://www.notion.so/ws/휴가-" + PAGE_ID + "?v=1") == PAGE_ID
    assert kb_notion.parse_target(dash(PAGE_ID)) == PAGE_ID
    assert kb_notion.parse_target("이상한 값") is None


def test_notion_sync_incremental_and_secrets(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    fake = FakeNotion()
    monkeypatch.setattr(safe_http, "request", fake)
    cid = notion_cred(client, team)
    kb = make_kb(client, team, "노션 자료")
    r = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources",
        json={
            "type": "notion",
            "name": "사내 위키",
            "schedule": "daily",
            "config": {"credential_id": cid, "targets": [PAGE_ID, DB_ID]},
        },
        headers=team.h("builder"),
    )
    assert r.status_code == 201, r.text
    src = r.json()
    assert src["last_status"] == "ok" and src["last_summary"]["added"] == 2
    assert src["schedule"] == "daily"
    assert all(h.get("Authorization") == f"Bearer {TOKEN}" for h in fake.seen_headers)
    assert all(h.get("Notion-Version") for h in fake.seen_headers)
    docs = client.get(f"/api/v1/knowledge-bases/{kb}/documents", headers=team.h("builder")).json()
    names = sorted(d["filename"] for d in docs)
    assert names == ["복지 안내.md", "휴가 규정.md"]
    assert all(d["source"] == "notion" and d["status"] == "ready" for d in docs)
    # 토큰은 어디에도 나오지 않는다
    assert TOKEN not in json.dumps(src) and TOKEN not in json.dumps(docs)
    kb_json = client.get(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases", headers=team.h("builder")
    ).text
    assert TOKEN not in kb_json

    # 안 바뀐 쪽은 블록을 다시 읽지 않는다
    before = fake.block_calls
    s = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources/{src['id']}/sync", headers=team.h("builder")
    ).json()["last_summary"]
    assert (s["added"], s["updated"], s["unchanged"]) == (0, 0, 2)
    # 데이터베이스에서 나온 쪽(OTHER)은 질의 결과의 last_edited_time으로 건너뛴다
    assert fake.block_calls == before
    # 바뀐 쪽만 다시 가져온다
    fake.pages[PAGE_ID]["last_edited_time"] = "2026-11-03T00:00:00.000Z"
    fake.children[PAGE_ID][1]["paragraph"]["rich_text"] = rt("입사 1년 뒤 16일로 늘었어요")
    s = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources/{src['id']}/sync", headers=team.h("builder")
    ).json()["last_summary"]
    assert (s["added"], s["updated"], s["unchanged"]) == (0, 1, 1)
    with SessionLocal() as db:
        doc = next(d for d in db.query(Document).all() if d.filename == "휴가 규정.md")
        assert doc.content is not None and "16일" in doc.content.decode()
        assert doc.url and doc.url.startswith("https://www.notion.so/")


def test_notion_errors_are_two_lines(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeNotion()
    monkeypatch.setattr(safe_http, "request", fake)
    cid = notion_cred(client, team)
    kb = make_kb(client, team)
    h = team.h("builder")
    # 연결 정보 없음·다른 종류·주소 형식 오류·빈 목록
    for cfg in (
        {"targets": [PAGE_ID]},
        {"credential_id": "nope", "targets": [PAGE_ID]},
        {"credential_id": cid, "targets": ["그냥 글"]},
        {"credential_id": cid, "targets": []},
    ):
        r = client.post(
            f"/api/v1/knowledge-bases/{kb}/sources",
            json={"type": "notion", "config": cfg},
            headers=h,
        )
        assert r.status_code == 422, (cfg, r.text)
        assert r.json()["detail"]["message"] and r.json()["detail"]["hint"]
    install(client, team, "http_credentials")
    other = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={"connector_key": "http_credentials", "name": "x", "secrets": {"token": "t"}},
        headers=team.h("owner"),
    ).json()["id"]
    assert (
        client.post(
            f"/api/v1/knowledge-bases/{kb}/sources",
            json={"type": "notion", "config": {"credential_id": other, "targets": [PAGE_ID]}},
            headers=h,
        ).status_code
        == 422
    )
    # 통합을 초대하지 않은 페이지(404)·잘못된 토큰(401)은 안내 문장과 함께 실패
    r = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources",
        json={
            "type": "notion",
            "config": {"credential_id": cid, "targets": ["0123456789abcdef0123456789abcdef"]},
        },
        headers=h,
    )
    assert r.status_code == 201
    assert r.json()["last_status"] == "failed" and "연결 추가" in r.json()["last_error"]
    fake.status_override["/pages"] = 401
    r = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources",
        json={"type": "notion", "config": {"credential_id": cid, "targets": [PAGE_ID]}},
        headers=h,
    )
    assert r.json()["last_status"] == "failed" and "토큰" in r.json()["last_error"]
    assert TOKEN not in r.text


# ---------------- 공개 Google 문서 ----------------
GID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


def fake_raw_factory(responses: dict[str, tuple[int, bytes, dict[str, str]]]) -> Any:
    seen: list[str] = []

    def fake(
        url: str, *, max_bytes: int, allowed_domains: list[str] | None = None, headers: Any = None
    ) -> dict[str, Any]:
        seen.append(url)
        assert allowed_domains and "google.com" in allowed_domains
        for needle, (status, body, hdr) in responses.items():
            if needle in url:
                return {"status": status, "body": body, "headers": hdr}
        return {"status": 404, "body": b"", "headers": {}}

    fake.seen = seen  # type: ignore[attr-defined]
    return fake


def test_google_parse_and_export_links() -> None:
    assert kb_google.parse_link(f"https://docs.google.com/document/d/{GID}/edit?usp=sharing")[
        :2
    ] == ("doc", GID)
    kind, i, gid = kb_google.parse_link(f"https://docs.google.com/spreadsheets/d/{GID}/edit#gid=77")
    assert (kind, i, gid) == ("sheet", GID, "77")
    assert kb_google.export_url("sheet", GID, "77").endswith("export?format=csv&gid=77")
    assert kb_google.export_url("doc", GID, None).endswith("/export?format=txt")
    assert kb_google.parse_link(f"https://docs.google.com/presentation/d/{GID}/edit")[0] == "slides"
    assert kb_google.parse_link(f"https://drive.google.com/file/d/{GID}/view")[0] == "file"
    assert kb_google.parse_link(f"https://drive.google.com/open?id={GID}")[0] == "file"
    for bad in (
        "https://example.com/document/d/" + GID,
        "https://docs.google.com/forms/d/" + GID,
        "abc",
    ):
        with pytest.raises(NodeError):
            kb_google.parse_link(bad)


def test_google_fetch_kinds_and_private(monkeypatch: pytest.MonkeyPatch) -> None:
    title = "%ED%9C%B4%EA%B0%80%20%EA%B7%9C%EC%A0%95.txt"
    fake = fake_raw_factory(
        {
            f"/document/d/{GID}/export": (
                200,
                "연차는 입사 1년 뒤 15일입니다.".encode(),
                {
                    "content-type": "text/plain; charset=utf-8",
                    "content-disposition": f"attachment; filename*=UTF-8''{title}",
                },
            ),
            f"/spreadsheets/d/{GID}/export": (
                200,
                "이름,부서,메모\n김철수,인사,\n박영희,재무,출장 많음\n".encode(),
                {"content-type": "text/csv"},
            ),
            "/presentation/d/PRIVATE": (
                200,
                b"<html>Sign in</html>",
                {"content-type": "text/html"},
            ),
            "drive.google.com/uc": (200, b"%PDF-1.4 fake", {"content-type": "application/pdf"}),
        }
    )
    monkeypatch.setattr(safe_http, "fetch_raw", fake)
    doc = kb_google.fetch(f"https://docs.google.com/document/d/{GID}/edit")
    assert doc.title == "휴가 규정" and doc.mime == "text/markdown"
    assert "연차는 입사 1년 뒤 15일" in doc.content.decode()
    sheet = kb_google.fetch(f"https://docs.google.com/spreadsheets/d/{GID}/edit")
    text = sheet.content.decode()
    assert "이름: 김철수 | 부서: 인사" in text and "메모: 출장 많음" in text
    pdf = kb_google.fetch(f"https://drive.google.com/file/d/{GID}/view")
    assert pdf.mime == "application/pdf" and pdf.filename.endswith(".pdf")
    with pytest.raises(NodeError) as exc:
        kb_google.fetch("https://docs.google.com/presentation/d/PRIVATE0000000000000/edit")
    assert "링크가 있는 모든 사용자" in exc.value.message
    monkeypatch.setattr(
        safe_http,
        "fetch_raw",
        fake_raw_factory({"/export": (403, b"", {"content-type": "text/html"})}),
    )
    with pytest.raises(NodeError) as exc2:
        kb_google.fetch(f"https://docs.google.com/document/d/{GID}/edit")
    assert "링크가 있는 모든 사용자" in exc2.value.message


def test_google_source_flow(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    fake = fake_raw_factory(
        {
            f"/document/d/{GID}/export": (
                200,
                "회의 규칙: 15분 안에 끝낸다. 안건은 미리 공유한다.".encode(),
                {"content-type": "text/plain"},
            ),
        }
    )
    monkeypatch.setattr(safe_http, "fetch_raw", fake)
    kb = make_kb(client, team)
    h = team.h("builder")
    r = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources",
        json={
            "type": "google",
            "name": "회의 규칙",
            "config": {
                "urls": [f"https://docs.google.com/document/d/{GID}/edit"],
                "name": "회의 규칙",
            },
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["last_summary"]["added"] == 1
    docs = client.get(f"/api/v1/knowledge-bases/{kb}/documents", headers=h).json()
    assert docs[0]["filename"] == "회의 규칙.md" and docs[0]["source"] == "google"
    again = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources/{r.json()['id']}/sync", headers=h
    ).json()
    assert again["last_summary"]["unchanged"] == 1 and again["last_summary"]["added"] == 0
    # 비공개 문서는 실패 사유를 알려 준다
    monkeypatch.setattr(
        safe_http,
        "fetch_raw",
        fake_raw_factory({"/export": (200, b"<html>login</html>", {"content-type": "text/html"})}),
    )
    r2 = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources",
        json={
            "type": "google",
            "config": {"urls": [f"https://docs.google.com/document/d/{GID}x/edit"]},
        },
        headers=h,
    )
    assert (
        r2.json()["last_status"] == "failed"
        and "링크가 있는 모든 사용자" in r2.json()["last_error"]
    )
    # 구글 주소가 아니면 만들 때 바로 거절
    assert (
        client.post(
            f"/api/v1/knowledge-bases/{kb}/sources",
            json={"type": "google", "config": {"urls": ["https://example.com/x"]}},
            headers=h,
        ).status_code
        == 422
    )


# ---------------- 예약 동기화·보호된 설정 ----------------
def test_daily_resync_task_and_protected_settings(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    from worker.tasks import sync_due_sources_task

    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    site = make_site()
    install_site(monkeypatch, site)
    kb = make_kb(client, team)
    h = team.h("builder")
    src = client.post(
        f"/api/v1/knowledge-bases/{kb}/sources",
        json={"type": "web", "schedule": "daily", "config": {"url": BASE, "depth": 0}},
        headers=h,
    ).json()
    # 방금 가져왔으니 아직 때가 아니다
    with SessionLocal() as db:
        assert kb_sources.due_sources(db) == []
    old = kb_sources._iso(kb_sources.now().replace(year=2020))
    with SessionLocal() as db:
        kb_sources.update_source(db, kb, src["id"], {"last_sync_at": old})
        assert kb_sources.due_sources(db) == [(kb, src["id"])]
    site[f"{BASE}/"] = (200, html("홈", BODY + "홈이 바뀌었어요"), "text/html")
    assert sync_due_sources_task() == 1
    got = client.get(f"/api/v1/knowledge-bases/{kb}/sources", headers=h).json()[0]
    assert got["last_summary"]["updated"] == 1 and got["running"] is False
    # 매일이 아닌 소스는 건드리지 않는다
    client.patch(
        f"/api/v1/knowledge-bases/{kb}/sources/{src['id']}", json={"schedule": "none"}, headers=h
    )
    with SessionLocal() as db:
        kb_sources.update_source(db, kb, src["id"], {"last_sync_at": old})
        assert kb_sources.due_sources(db) == []
    # 일반 설정 저장으로는 종류·외부·소스·튜닝을 바꿀 수 없다
    r = client.patch(
        f"/api/v1/knowledge-bases/{kb}",
        json={
            "settings": {
                "kind": "external",
                "external": {"endpoint": "https://evil.example.com", "knowledge_id": "x"},
                "sources": [],
                "tuning": {"questions": [{"question": "x"}]},
                "chunk_size": 500,
            }
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert s["kind"] == "internal" and s["external"] is None and s["chunk_size"] == 500
    assert len(s["sources"]) == 1 and s["tuning"]["questions"] == []
