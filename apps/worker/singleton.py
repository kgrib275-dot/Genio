"""주기 작업(beat)이 여러 번 실행되지 않게 막는다(운영 준비 1차 A2).

예약 실행 등 주기 작업은 `scheduler` 서비스(celery beat) 하나가 보낸다. 그래도 실수로 beat가 둘 뜨거나
같은 작업이 겹쳐 돌 수 있으니 Redis에 두 가지 표시를 남긴다.
  genio:beat:{이름}:{주기 번호}  같은 주기 안에서 한 번만(주기 길이만큼 유지)
  genio:lock:{이름}              실행 중에는 다른 실행을 건너뛴다(끝나면 지움, 최대 lock_seconds)
Redis 설정이 없으면(시험·로컬) 그냥 실행한다. Redis가 잠시 끊겨도 작업은 실행한다(멈추는 것보다 낫다).
마지막 실행 시각은 genio:beat:last:{이름}에 남겨 관리 > 시스템 상태가 '예약 실행' 상태를 보여 준다.
"""

import logging
import time
import uuid
from collections.abc import Callable
from functools import lru_cache

import redis

from api.config import get_settings

log = logging.getLogger("genio.beat")


@lru_cache
def _redis() -> "redis.Redis[bytes] | None":
    url = get_settings().redis_url
    if not url:
        return None
    return redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)


def last_run_key(name: str) -> str:
    return f"genio:beat:last:{name}"


def run_once[T](
    name: str, period: float, fn: Callable[[], T], lock_seconds: float = 600
) -> T | None:
    """period초 주기에 한 번만, 그리고 겹치지 않게 fn을 실행한다. 건너뛰면 None."""
    client = _redis()
    if client is None:
        return fn()
    token = uuid.uuid4().hex
    bucket = f"genio:beat:{name}:{int(time.time() // period)}"
    lock = f"genio:lock:{name}"
    locked = False
    try:
        if not client.set(bucket, token, nx=True, ex=max(1, int(period))):
            log.info("주기 작업 %s: 이번 주기는 이미 실행돼 건너뜀", name)
            return None
        if not client.set(lock, token, nx=True, ex=max(1, int(lock_seconds))):
            log.info("주기 작업 %s: 아직 앞 실행이 도는 중이라 건너뜀", name)
            return None
        locked = True
    except redis.RedisError:
        log.warning("주기 작업 %s: Redis에 표시를 남기지 못해 그냥 실행", name)
    try:
        return fn()
    finally:
        try:
            client.set(last_run_key(name), str(int(time.time())), ex=7 * 24 * 3600)
            if locked and client.get(lock) == token.encode():
                client.delete(lock)
        except redis.RedisError:
            pass
