"""'이번 주 새로 나온 것': 새 MCP 서비스와 n8n 템플릿(최신·인기)을 하루 한 번 모아 저장해 둔다(ADR 0020).

공개 목록을 화면을 열 때마다 부르지 않고, scheduler가 하루 한 번 가져와 Redis(없으면 메모리)에 둔다.
저장본이 없거나 36시간이 지났으면 요청 때 한 번 새로 만든다(5분에 한 번만).
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from api.config import get_settings
from api.core import ratelimit
from api.services import catalog
from nodes import NodeError

log = logging.getLogger("genio.trends")

KEY = "genio:trends:v1"
MAX_AGE_SECONDS = 36 * 3600
MCP_DAYS = 7
MCP_LIMIT = 30
N8N_LIMIT = 12
_memory: dict[str, Any] = {}


def _redis() -> Any:
    url = get_settings().redis_url
    if not url:
        return None
    try:
        import redis

        return redis.Redis.from_url(url, socket_timeout=1.5, socket_connect_timeout=1.5)
    except Exception:
        return None


def _load() -> dict[str, Any] | None:
    r = _redis()
    if r is not None:
        try:
            raw = r.get(KEY)
            if raw:
                data = json.loads(raw)
                return data if isinstance(data, dict) else None
        except Exception as exc:
            log.warning("트렌드 저장본을 읽지 못했어요: %s", type(exc).__name__)
    return dict(_memory) or None


def _save(data: dict[str, Any]) -> None:
    _memory.clear()
    _memory.update(data)
    r = _redis()
    if r is None:
        return
    try:
        r.set(KEY, json.dumps(data, ensure_ascii=False), ex=MAX_AGE_SECONDS * 3)
    except Exception as exc:
        log.warning("트렌드 저장본을 저장하지 못했어요: %s", type(exc).__name__)


def _within_hours(iso: str, hours: int, now: datetime) -> bool:
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return now - t <= timedelta(hours=hours)


def refresh(*, now: datetime | None = None) -> dict[str, Any]:
    """공개 목록에서 새로 가져와 저장한다. 한쪽이 실패해도 나머지는 저장한다."""
    now = now or datetime.now(UTC)
    since = (now - timedelta(days=MCP_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    errors: list[str] = []
    mcp_all: list[dict[str, Any]] = []
    new_n8n: list[dict[str, Any]] = []
    popular_n8n: list[dict[str, Any]] = []
    try:
        mcp_all = catalog.recent_mcp(since)
    except NodeError as exc:
        errors.append(f"MCP: {exc.message}")
    try:
        for page in (1, 2):
            new_n8n += catalog.search_n8n("", page, "createdAt:desc")["items"]
    except NodeError as exc:
        errors.append(f"n8n 최신: {exc.message}")
    try:
        for page in (1, 2):
            popular_n8n += catalog.search_n8n("", page, "views:desc")["items"]
    except NodeError as exc:
        errors.append(f"n8n 인기: {exc.message}")
    installable = [i for i in mcp_all if i["installable"]]
    previous = _load() or {}
    data: dict[str, Any] = {
        "updated_at": now.isoformat(),
        "mcp_new": installable[:MCP_LIMIT] or previous.get("mcp_new", []),
        "mcp_new_total": len(mcp_all),
        "mcp_new_today": sum(1 for i in installable if _within_hours(i["updated_at"], 24, now)),
        "n8n_new": new_n8n[:N8N_LIMIT] or previous.get("n8n_new", []),
        "n8n_popular": popular_n8n[:N8N_LIMIT] or previous.get("n8n_popular", []),
        "errors": errors,
    }
    if not (mcp_all or new_n8n or popular_n8n):
        # 전부 실패하면 예전 저장본을 지우지 않는다
        return previous or data
    _save(data)
    return data


def get() -> dict[str, Any]:
    """저장본을 돌려준다. 없거나 오래됐으면 새로 만든다(5분에 한 번만, 실패하면 있는 것을 돌려준다)."""
    data = _load()
    fresh = False
    if data:
        try:
            updated = datetime.fromisoformat(str(data["updated_at"]))
            fresh = (datetime.now(UTC) - updated).total_seconds() < MAX_AGE_SECONDS
        except (KeyError, ValueError):
            fresh = False
    if fresh and data:
        return data
    if ratelimit.allow("trends_refresh", 1, window=300):
        try:
            return refresh()
        except Exception as exc:
            log.warning("트렌드를 새로 만들지 못했어요: %s", type(exc).__name__)
    return data or {
        "updated_at": "",
        "mcp_new": [],
        "mcp_new_total": 0,
        "mcp_new_today": 0,
        "n8n_new": [],
        "n8n_popular": [],
        "errors": ["아직 목록을 모으지 못했어요. 잠시 후 다시 열어 주세요."],
    }
