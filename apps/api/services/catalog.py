"""외부 카탈로그 조회(ADR 0020): 공식 MCP 레지스트리에서 서버를 찾는다. 읽기 전용, 5분 캐시."""

import json
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
