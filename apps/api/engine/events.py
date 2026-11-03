"""실행 이벤트 알림(Redis pub/sub). SSE는 이 알림을 신호로 DB를 다시 읽는다.

Redis가 없으면(테스트·로컬) 알림 없이 주기적으로 DB를 확인한다.
"""

import json
import logging
from functools import lru_cache
from typing import Any

import redis

from api.config import get_settings

log = logging.getLogger("genio.events")


def channel(run_id: str) -> str:
    return f"genio:run:{run_id}"


@lru_cache
def _client() -> "redis.Redis[bytes] | None":
    url = get_settings().redis_url
    if not url:
        return None
    return redis.Redis.from_url(url)


def publish(run_id: str, payload: dict[str, Any]) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.publish(channel(run_id), json.dumps(payload, ensure_ascii=False, default=str))
    except redis.RedisError:
        log.warning("실행 이벤트 알림 실패(run=%s)", run_id)


def subscriber(run_id: str) -> "redis.client.PubSub | None":
    client = _client()
    if client is None:
        return None
    try:
        ps = client.pubsub(ignore_subscribe_messages=True)
        ps.subscribe(channel(run_id))
        return ps
    except redis.RedisError:
        return None
