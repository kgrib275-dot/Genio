"""외부 카탈로그 조회(ADR 0020): 공식 MCP 레지스트리에서 서버를 찾는다. 읽기 전용, 5분 캐시."""

import json
import re
import time
from typing import Any
from urllib.parse import urlencode

from api.engine import safe_http
from nodes import NodeError

REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0/servers"
CACHE_SECONDS = 300
MAX_LIMIT = 20
_cache: dict[tuple[str, str, int], tuple[float, dict[str, Any]]] = {}


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _remotes(server: dict[str, Any]) -> list[dict[str, Any]]:
    """설치할 수 있는 원격 주소(streamable-http, 자리표시자 없음)만 추린다."""
    out: list[dict[str, Any]] = []
    for r in server.get("remotes") or []:
        if not isinstance(r, dict) or r.get("type") != "streamable-http":
            continue
        url = str(r.get("url") or "")
        if not url.lower().startswith("https://") or "{" in url:
            continue
        headers = [
            {
                "name": _text(h.get("name"), 64),
                "description": _text(h.get("description"), 200),
                "required": bool(h.get("isRequired")),
                "secret": bool(h.get("isSecret")),
            }
            for h in (r.get("headers") or [])
            if isinstance(h, dict) and h.get("name")
        ]
        out.append({"url": url[:500], "headers": headers})
    return out


def normalize(entry: dict[str, Any]) -> dict[str, Any] | None:
    raw_server = entry.get("server")
    server: dict[str, Any] = raw_server if isinstance(raw_server, dict) else entry
    name = _text(server.get("name"), 200)
    if not name:
        return None
    raw_meta = entry.get("_meta")
    official = (raw_meta if isinstance(raw_meta, dict) else {}).get(
        "io.modelcontextprotocol.registry/official"
    )
    meta: dict[str, Any] = official if isinstance(official, dict) else {}
    if meta.get("status") not in (None, "active"):
        return None
    raw_repo = server.get("repository")
    repo: dict[str, Any] = raw_repo if isinstance(raw_repo, dict) else {}
    remotes = _remotes(server)
    return {
        "name": name,
        "title": _text(server.get("title") or name.split("/")[-1], 100),
        "description": _text(server.get("description"), 400),
        "version": _text(server.get("version"), 40),
        "repository": _text(repo.get("url"), 300),
        "website": _text(server.get("websiteUrl"), 300),
        "installable": bool(remotes),
        "remotes": remotes,
        "updated_at": _text(meta.get("updatedAt"), 40),
    }


def _body(res: dict[str, Any]) -> dict[str, Any]:
    body = res.get("body")
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = None
    return body if isinstance(body, dict) else {}


def search_mcp(q: str, cursor: str = "", limit: int = MAX_LIMIT) -> dict[str, Any]:
    """{items, next_cursor}. 설치할 수 있는 것을 앞에 둔다."""
    q, cursor = q.strip()[:100], cursor.strip()[:200]
    limit = max(1, min(limit, MAX_LIMIT))
    key = (q, cursor, limit)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    params = {"limit": str(limit)}
    if q:
        params["search"] = q
    if cursor:
        params["cursor"] = cursor
    try:
        res = safe_http.request("GET", f"{REGISTRY_URL}?{urlencode(params)}")
    except NodeError:
        raise
    except Exception:
        raise NodeError("서비스 목록을 불러오지 못했어요. 잠시 후 다시 시도하세요.") from None
    if int(res.get("status") or 0) >= 400:
        raise NodeError("서비스 목록을 불러오지 못했어요. 잠시 후 다시 시도하세요.")
    data = _body(res)
    items = [n for e in data.get("servers") or [] if isinstance(e, dict) if (n := normalize(e))]
    items.sort(key=lambda i: not i["installable"])
    raw_page = data.get("metadata")
    page: dict[str, Any] = raw_page if isinstance(raw_page, dict) else {}
    result = {"items": items, "next_cursor": _text(page.get("nextCursor"), 200)}
    if len(_cache) > 200:
        _cache.clear()
    _cache[key] = (time.monotonic(), result)
    return result


def find_mcp(name: str) -> dict[str, Any] | None:
    """이름이 정확히 같은 서버 한 개(설치 때 주소를 서버가 다시 읽는 데 쓴다)."""
    for item in search_mcp(name, limit=MAX_LIMIT)["items"]:
        if item["name"] == name:
            found: dict[str, Any] = item
            return found
    return None


# ---------------- n8n 공개 템플릿 ----------------
N8N_URL = "https://api.n8n.io/templates"
N8N_ROWS = 10
_n8n_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
_TAG_RE = re.compile(r"<[^>]+>|[#*`>_]|!?\[([^\]]*)\]\([^)]*\)")


def _dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _plain(text: Any, limit: int) -> str:
    return _text(_TAG_RE.sub(lambda m: m.group(1) or "", str(text or "")), limit)


def _n8n_get(url: str) -> dict[str, Any]:
    try:
        res = safe_http.request("GET", url)
    except NodeError:
        raise
    except Exception:
        raise NodeError("n8n 템플릿 목록을 불러오지 못했어요. 잠시 후 다시 시도하세요.") from None
    if int(res.get("status") or 0) >= 400:
        raise NodeError("n8n 템플릿을 찾지 못했어요. 다른 템플릿을 골라 주세요.")
    return _body(res)


N8N_SORTS = ("views:desc", "createdAt:desc")


def _n8n_item(w: Any) -> dict[str, Any] | None:
    if not isinstance(w, dict) or not isinstance(w.get("id"), int) or w.get("price"):
        return None  # 유료 템플릿은 보여 주지 않는다
    user = _dict(w.get("user"))
    nodes = [
        _text(n.get("displayName") or n.get("name"), 40)
        for n in (w.get("nodes") or [])
        if isinstance(n, dict)
    ]
    return {
        "id": w["id"],
        "name": _text(w.get("name"), 150),
        "description": _plain(w.get("description"), 300),
        "views": int(w.get("totalViews") or 0),
        "author": _text(user.get("username") or user.get("name"), 60),
        "services": list(dict.fromkeys(nodes))[:8],
        "created_at": _text(w.get("createdAt"), 40),
        "url": f"https://n8n.io/workflows/{w['id']}",
    }


def search_n8n(q: str, page: int = 1, sort: str = "") -> dict[str, Any]:
    q, page = q.strip()[:100], max(1, min(page, 50))
    sort = sort if sort in N8N_SORTS else ""
    key = (f"{q}|{sort}", page)
    hit = _n8n_cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    params = {"rows": str(N8N_ROWS), "page": str(page)}
    if q:
        params["search"] = q
    if sort:
        params["sort"] = sort
    data = _n8n_get(f"{N8N_URL}/search?{urlencode(params)}")
    items = [i for w in data.get("workflows") or [] if (i := _n8n_item(w))]
    total = int(data.get("totalWorkflows") or 0)
    result = {"items": items, "total": total, "page": page, "has_more": page * N8N_ROWS < total}
    if len(_n8n_cache) > 200:
        _n8n_cache.clear()
    _n8n_cache[key] = (time.monotonic(), result)
    return result


def get_n8n(template_id: int) -> dict[str, Any]:
    """템플릿 한 개: {id, name, description, author, url, workflow(n8n JSON), paid}."""
    data = _n8n_get(f"{N8N_URL}/workflows/{int(template_id)}")
    w = _dict(data.get("workflow"))
    user = _dict(w.get("user"))
    return {
        "id": int(template_id),
        "name": _text(w.get("name"), 150),
        "description": _plain(w.get("description"), 1000),
        "author": _text(user.get("username") or user.get("name"), 60),
        "url": f"https://n8n.io/workflows/{int(template_id)}",
        "workflow": w,
        "paid": bool(w.get("price")),
    }


def recent_mcp(since_iso: str, *, max_pages: int = 5, page_size: int = 100) -> list[dict[str, Any]]:
    """since 이후에 올라오거나 갱신된 MCP 서버(최신 판만). 최근 갱신순."""
    out: dict[str, dict[str, Any]] = {}
    cursor = ""
    for _ in range(max_pages):
        params = {"limit": str(page_size), "updated_since": since_iso}
        if cursor:
            params["cursor"] = cursor
        try:
            res = safe_http.request("GET", f"{REGISTRY_URL}?{urlencode(params)}")
        except NodeError:
            raise
        except Exception:
            raise NodeError("서비스 목록을 불러오지 못했어요. 잠시 후 다시 시도하세요.") from None
        if int(res.get("status") or 0) >= 400:
            raise NodeError("서비스 목록을 불러오지 못했어요. 잠시 후 다시 시도하세요.")
        data = _body(res)
        for e in data.get("servers") or []:
            if not isinstance(e, dict):
                continue
            official = _dict(_dict(e.get("_meta")).get("io.modelcontextprotocol.registry/official"))
            if official.get("isLatest") is False:
                continue
            item = normalize(e)
            if item and item["name"] not in out:
                out[item["name"]] = item
        cursor = _text(_dict(data.get("metadata")).get("nextCursor"), 200)
        if not cursor:
            break
    return sorted(out.values(), key=lambda i: i["updated_at"], reverse=True)
