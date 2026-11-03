"""Notion 커넥터(내부 통합 토큰). 플랫폼이 넘겨준 net으로만 api.notion.com에 접속한다."""

import re
from typing import Any

from nodes.spec import NodeError

API = "https://api.notion.com/v1"
ID_RE = re.compile(r"^[0-9a-fA-F-]{32,36}$")


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    token = str(secrets.get("token") or "")
    if not token:
        raise NodeError("노션 토큰이 비어 있어요. 연결 정보에 내부 통합 토큰을 넣어 주세요.")
    return {
        "Authorization": "Bearer " + token,
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _id(value: Any, what: str) -> str:
    raw = str(value or "").strip()
    # 노션 주소를 통째로 붙여 넣어도 끝의 32자리 id를 꺼낸다
    m = re.search(r"([0-9a-fA-F]{32})(?:\?|$)", raw.replace("-", ""))
    if m:
        return m.group(1)
    if ID_RE.match(raw):
        return raw
    raise NodeError(f"{what} id 형식이 맞지 않아요. 노션 주소 끝의 32자리 값을 넣어 주세요.")


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError(
            f"노션 인증에 실패했어요({status}). 토큰과 페이지 공유(연결 추가)를 확인하세요."
        )
    if status == 404:
        raise NodeError(
            "노션에서 대상을 찾지 못했어요(404). 통합을 그 페이지에 연결했는지 확인하세요."
        )
    if status == 429:
        raise NodeError("노션 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        raise NodeError(f"노션에서 {what}하지 못했어요({status}). 설정 값을 확인하세요.")
    return body if isinstance(body, dict) else {}


def _paragraphs(content: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for part in [p.strip() for p in content.split("\n\n") if p.strip()][:100]:
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": part[:2000]}}]},
            }
        )
    return blocks


def _title_of(page: dict[str, Any]) -> str:
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return "".join(str(t.get("plain_text", "")) for t in prop.get("title") or [])
    return ""


def create_page(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    title = str(params["title"])[:2000]
    title_rich = [{"type": "text", "text": {"content": title}}]
    if params.get("database_id"):
        prop = str(params.get("title_property") or "Name")
        body: dict[str, Any] = {
            "parent": {"database_id": _id(params["database_id"], "데이터베이스")},
            "properties": {prop: {"title": title_rich}},
        }
    elif params.get("parent_page_id"):
        body = {
            "parent": {"page_id": _id(params["parent_page_id"], "상위 페이지")},
            "properties": {"title": {"title": title_rich}},
        }
    else:
        raise NodeError(
            "어디에 만들지 정해 주세요. '데이터베이스 id'나 '상위 페이지 id' 중 하나를 넣으세요."
        )
    blocks = _paragraphs(str(params.get("content") or ""))
    if blocks:
        body["children"] = blocks
    res = net.http("POST", API + "/pages", headers=_headers(secrets), json=body)
    data = _check(res, "페이지를 만들")
    return {"page_id": str(data.get("id", "")), "url": str(data.get("url", ""))}


def query_database(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    db_id = _id(params["database_id"], "데이터베이스")
    size = max(1, min(int(params.get("page_size") or 10), 100))
    body: dict[str, Any] = {"page_size": size}
    if isinstance(params.get("filter"), dict) and params["filter"]:
        body["filter"] = params["filter"]
    res = net.http(
        "POST", API + "/databases/" + db_id + "/query", headers=_headers(secrets), json=body
    )
    data = _check(res, "데이터베이스를 읽")
    rows = [
        {"id": str(p.get("id", "")), "url": str(p.get("url", "")), "title": _title_of(p)}
        for p in data.get("results") or []
        if isinstance(p, dict)
    ]
    return {"count": len(rows), "results": rows, "text": "\n".join(r["title"] for r in rows)}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _check(net.http("GET", API + "/users/me", headers=_headers(secrets)), "연결을 확인")
    return {"message": "노션에 연결됐어요: " + str(data.get("name") or "통합")}
