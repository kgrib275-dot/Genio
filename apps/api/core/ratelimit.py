"""속도 제한(IP당 분당 N회)과 로그인 실패 횟수.

API 프로세스가 여럿이어도 같은 한도를 공유하도록 Redis에 센다(키 genio:rl:*, genio:fail:*).
Redis가 없거나(시험·로컬) 끊기면 프로세스 메모리로 센다. 이때는 프로세스 수만큼 한도가 느슨해지므로
경고를 남기고 관리 > 시스템 상태의 '속도 제한' 항목에 표시한다.

Redis가 끊긴 동안 요청마다 연결을 기다리지 않도록, 오류가 나면 BACKOFF_SECONDS 동안 Redis를 건너뛴다.
"""

import contextlib
import logging
import threading
import time
from collections import defaultdict, deque
from functools import lru_cache
from typing import Any

import redis

from api.config import get_settings

log = logging.getLogger("genio.ratelimit")

# Redis 연결·응답을 기다리는 최대 시간(초). 속도 제한 때문에 요청이 느려지지 않게 짧게 둔다.
REDIS_TIMEOUT_SECONDS = 0.5
# Redis 오류 뒤 다시 시도하기까지 메모리로 세는 시간(초)
BACKOFF_SECONDS = 10.0
# 같은 경고를 이 간격(초)보다 자주 남기지 않는다
WARN_EVERY_SECONDS = 60.0

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)
_fails: dict[str, deque[float]] = defaultdict(deque)
_state: dict[str, float] = {"skip_until": 0.0, "last_fallback": 0.0, "last_warn": 0.0}


@lru_cache
def _redis_client() -> "redis.Redis[bytes] | None":
    url = get_settings().redis_url
    if not url:
        return None
    return redis.Redis.from_url(
        url,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
    )


def _client() -> "redis.Redis[bytes] | None":
    """지금 쓸 Redis. 설정이 없거나 최근에 오류가 나서 쉬는 중이면 None(메모리로 센다)."""
    client = _redis_client()
    if client is None:
        return None
    if time.time() < _state["skip_until"]:
        _state["last_fallback"] = time.time()
        return None
    return client


def _on_redis_error(exc: Exception) -> None:
    now = time.time()
    _state["skip_until"] = now + BACKOFF_SECONDS
    _state["last_fallback"] = now
    if now - _state["last_warn"] >= WARN_EVERY_SECONDS:
        _state["last_warn"] = now
        log.warning(
            "속도 제한을 Redis에 기록하지 못해 %s초 동안 프로세스 메모리로 셉니다(%s)",
            int(BACKOFF_SECONDS),
            type(exc).__name__,
        )


def backend_state() -> dict[str, Any]:
    """시스템 상태 화면용: 지금 어디에 세는지와 마지막으로 메모리로 넘어간 시각."""
    configured = bool(get_settings().redis_url)
    last = _state["last_fallback"]
    return {
        "configured": configured,
        "degraded": configured and time.time() < _state["skip_until"],
        "last_fallback": last or None,
    }


_last_purge = 0.0


def _purge(now: float, window: int) -> None:
    """메모리 폴백에서 오래 안 쓴 키를 지운다(주소를 바꿔 가며 찌르면 키가 끝없이 늘어나므로). 1분에 한 번."""
    global _last_purge
    if now - _last_purge < 60:
        return
    _last_purge = now
    for k in [k for k, q in _hits.items() if not q or q[-1] <= now - max(window, 60)]:
        del _hits[k]


def allow(key: str, limit: int | None = None, window: int = 60) -> bool:
    limit = limit or get_settings().genio_public_rate_limit_per_minute
    client = _client()
    if client is not None:
        bucket = f"genio:rl:{key}:{int(time.time() // window)}"
        try:
            pipe = client.pipeline()
            pipe.incr(bucket)
            pipe.expire(bucket, window + 5, nx=True)
            count = int(pipe.execute()[0])
            return count <= limit
        except redis.RedisError as e:
            _on_redis_error(e)
    now = time.time()
    with _lock:
        _purge(now, window)
        q = _hits[key]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def reset() -> None:
    with _lock:
        _hits.clear()
        _fails.clear()
    _state.update(skip_until=0.0, last_fallback=0.0, last_warn=0.0)


# ---------------- 실패 횟수(로그인 시도 제한) ----------------


def fail_count(key: str, window: int) -> int:
    client = _client()
    if client is not None:
        try:
            v = client.get(f"genio:fail:{key}")
            return int(v or 0)
        except redis.RedisError as e:
            _on_redis_error(e)
    now = time.time()
    with _lock:
        q = _fails[key]
        while q and q[0] <= now - window:
            q.popleft()
        return len(q)


def add_fail(key: str, window: int) -> int:
    """실패 한 번 더. 첫 실패부터 window초 동안 센다. 지금까지 횟수를 돌려준다."""
    client = _client()
    if client is not None:
        try:
            k = f"genio:fail:{key}"
            pipe = client.pipeline()
            pipe.incr(k)
            pipe.expire(k, window, nx=True)
            return int(pipe.execute()[0])
        except redis.RedisError as e:
            _on_redis_error(e)
    now = time.time()
    with _lock:
        q = _fails[key]
        while q and q[0] <= now - window:
            q.popleft()
        q.append(now)
        return len(q)


def clear_fails(key: str) -> None:
    client = _client()
    if client is not None:
        with contextlib.suppress(redis.RedisError):
            client.delete(f"genio:fail:{key}")
    with _lock:
        _fails.pop(key, None)
