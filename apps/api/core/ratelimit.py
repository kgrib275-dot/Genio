"""공개 엔드포인트 속도 제한(IP당 분당 N회). Redis가 있으면 Redis, 없으면 프로세스 메모리."""

import threading
import time
from collections import defaultdict, deque

import redis

from api.config import get_settings
from api.engine.events import _client

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def allow(key: str, limit: int | None = None, window: int = 60) -> bool:
    limit = limit or get_settings().genio_public_rate_limit_per_minute
    client = _client()
    if client is not None:
        bucket = f"genio:rl:{key}:{int(time.time() // window)}"
        try:
            count = int(client.incr(bucket))
            if count == 1:
                client.expire(bucket, window + 5)
            return count <= limit
        except redis.RedisError:
            pass
    now = time.time()
    with _lock:
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
