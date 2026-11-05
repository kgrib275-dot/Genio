"""접속 표시(v0.9): 누가 이 앱 빌더를 열어 두었고 어떤 단계를 보고 있는지.

사용자가 10초마다 알려 주면(heartbeat) 30초 동안 '있는 것'으로 본다. 저장소는 Redis 해시이고,
Redis가 없으면 같은 프로세스 안의 사전을 쓴다. 이름은 서버가 로그인 정보에서 채워 속일 수 없다.
"""

import contextlib
import json
import logging
import threading
import time
from typing import Any

import redis

from api.engine import events

log = logging.getLogger("genio.presence")

TTL_SECONDS = 30.0
KEY_TTL = 600
COLORS = (
    "#6366f1",
    "#ec4899",
    "#10b981",
    "#f59e0b",
    "#0ea5e9",
    "#8b5cf6",
    "#ef4444",
    "#14b8a6",
)

_LOCAL: dict[str, dict[str, dict[str, Any]]] = {}
_LOCK = threading.Lock()


def _key(app_id: str) -> str:
    return f"genio:presence:{app_id}"


def color_of(user_id: str) -> str:
    """사용자마다 늘 같은 색(8가지 중 하나)."""
    return COLORS[sum(ord(c) for c in user_id) % len(COLORS)]


def touch(
    app_id: str,
    user_id: str,
    name: str,
    *,
    node_id: str | None = None,
    editing: bool = False,
    can_edit: bool = True,
    now: float | None = None,
) -> None:
    entry = {
        "user_id": user_id,
        "name": name,
        "color": color_of(user_id),
        "node_id": node_id,
        "editing": bool(editing and can_edit),
        "can_edit": can_edit,
        "seen": now if now is not None else time.time(),
    }
    client = events._client()
    if client is not None:
        try:
            client.hset(_key(app_id), user_id, json.dumps(entry, ensure_ascii=False))
            client.expire(_key(app_id), KEY_TTL)
            return
        except redis.RedisError:
            log.warning("접속 표시 저장 실패(app=%s) — 이 프로세스 안에만 둬요", app_id)
    with _LOCK:
        _LOCAL.setdefault(app_id, {})[user_id] = entry


def drop(app_id: str, user_id: str) -> None:
    client = events._client()
    if client is not None:
        with contextlib.suppress(redis.RedisError):
            client.hdel(_key(app_id), user_id)
    with _LOCK:
        _LOCAL.get(app_id, {}).pop(user_id, None)


def snapshot(app_id: str, *, now: float | None = None) -> list[dict[str, Any]]:
    """지금 있는 사람들(30초 안에 알려 온 사람). 이름순."""
    at = now if now is not None else time.time()
    entries: list[dict[str, Any]] = []
    client = events._client()
    if client is not None:
        try:
            raw = client.hgetall(_key(app_id))
            for v in raw.values():
                try:
                    entries.append(json.loads(v))
                except ValueError:
                    continue
        except redis.RedisError:
            log.warning("접속 표시 읽기 실패(app=%s)", app_id)
    with _LOCK:
        entries.extend(_LOCAL.get(app_id, {}).values())
    seen: dict[str, dict[str, Any]] = {}
    for e in entries:
        if at - float(e.get("seen", 0)) > TTL_SECONDS:
            continue
        old = seen.get(e["user_id"])
        if old is None or float(e["seen"]) >= float(old["seen"]):
            seen[e["user_id"]] = e
    return sorted(seen.values(), key=lambda e: (str(e.get("name", "")), e["user_id"]))


def public_view(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """화면에 보낼 값(시각 제외)."""
    keys = ("user_id", "name", "color", "node_id", "editing", "can_edit")
    return [{k: e.get(k) for k in keys} for e in entries]


def reset_local() -> None:
    with _LOCK:
        _LOCAL.clear()
