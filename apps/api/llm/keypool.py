"""AI 연결 키 돌려쓰기(v0.9): 한 연결에 키를 여러 개 두고 나눠 쓰거나, 한도에 걸리면 다음 키로 넘어간다.

- 순서 정하기: failover(앞의 키부터) · round_robin(돌아가며) · weighted(비중대로).
- 한도(429·사용량 초과)나 키 오류가 나면 그 키를 잠시 쉬게 한다(cooldown). 한도는 60초, 키 오류는
  '연결 테스트'로 다시 확인할 때까지(1시간).
- 키별 호출 수·실패 수·마지막 오류·쉬는 시간은 Redis에 두고(프로세스가 여러 개여도 같이 본다),
  Redis가 없으면(시험·로컬) 프로세스 메모리에 둔다.
- 키 값은 이 모듈의 로그·상태에 남기지 않는다. 오류 글도 LlmError의 한국어 문장만 쓴다.
"""

import contextlib
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import redis

from api.engine.events import _client

COOLDOWN_RATE_LIMIT = 60.0
COOLDOWN_AUTH = 3600.0
STATE_TTL = 7 * 24 * 3600
MAX_KEYS = 10

# 시험에서 시계와 무작위를 바꿔 끼울 수 있게 모듈 값으로 둔다
clock: Callable[[], float] = time.time
rng: random.Random = random.Random()  # noqa: S311 - 키 순서 섞기용(보안 난수 아님)

_lock = threading.Lock()
_mem: dict[str, dict[str, Any]] = {}
_rr: dict[str, int] = {}


@dataclass(frozen=True)
class KeyRef:
    id: str
    label: str
    secret: str = field(repr=False)
    weight: int = 1
    position: int = 1  # 화면 목록의 몇 번째 키인지(1부터, 꺼 둔 키도 센다)


def reset() -> None:
    """시험용: 메모리 상태를 비운다."""
    with _lock:
        _mem.clear()
        _rr.clear()


def _key(conn_id: str, key_id: str) -> str:
    return f"genio:llmkey:{conn_id}:{key_id}"


def _blank() -> dict[str, Any]:
    return {"calls": 0, "errors": 0, "last_error": "", "last_used": 0.0, "cooldown_until": 0.0}


def state(conn_id: str, key_id: str) -> dict[str, Any]:
    """키의 호출 수·실패 수·마지막 오류·쉬는 시각."""
    client = _client()
    if client is not None:
        try:
            raw = client.hgetall(_key(conn_id, key_id))
            if raw:
                out = _blank()
                for k, v in raw.items():
                    name = k.decode() if isinstance(k, bytes) else str(k)
                    val = v.decode() if isinstance(v, bytes) else str(v)
                    if name in ("calls", "errors"):
                        out[name] = int(val or 0)
                    elif name in ("last_used", "cooldown_until"):
                        out[name] = float(val or 0)
                    elif name == "last_error":
                        out[name] = val
                return out
            return _blank()
        except redis.RedisError:
            pass
    with _lock:
        return {**_blank(), **_mem.get(_key(conn_id, key_id), {})}


def cooldown_left(conn_id: str, key_id: str) -> float:
    return max(0.0, float(state(conn_id, key_id)["cooldown_until"]) - clock())


def _update(conn_id: str, key_id: str, *, incr: dict[str, int], sets: dict[str, Any]) -> None:
    client = _client()
    if client is not None:
        try:
            k = _key(conn_id, key_id)
            pipe = client.pipeline()
            for name, n in incr.items():
                pipe.hincrby(k, name, n)
            if sets:
                pipe.hset(k, mapping={a: str(b) for a, b in sets.items()})
            pipe.expire(k, STATE_TTL)
            pipe.execute()
            return
        except redis.RedisError:
            pass
    with _lock:
        s = _mem.setdefault(_key(conn_id, key_id), _blank())
        for name, n in incr.items():
            s[name] = int(s.get(name, 0)) + n
        s.update(sets)


def record(conn_id: str, key_id: str, *, ok: bool, error: str = "") -> None:
    """한 번 불렀다는 기록(성공이면 마지막 오류를 비운다)."""
    if ok:
        _update(
            conn_id,
            key_id,
            incr={"calls": 1},
            sets={"last_used": clock(), "last_error": ""},
        )
    else:
        _update(
            conn_id,
            key_id,
            incr={"calls": 1, "errors": 1},
            sets={"last_used": clock(), "last_error": error[:200]},
        )


def set_cooldown(conn_id: str, key_id: str, seconds: float) -> None:
    _update(conn_id, key_id, incr={}, sets={"cooldown_until": clock() + seconds})


def clear_cooldown(conn_id: str, key_id: str) -> None:
    """'연결 테스트'가 성공했을 때: 쉬던 키를 바로 다시 쓴다."""
    _update(conn_id, key_id, incr={}, sets={"cooldown_until": 0.0, "last_error": ""})


def forget(conn_id: str, key_ids: list[str]) -> None:
    client = _client()
    for kid in key_ids:
        if client is not None:
            with contextlib.suppress(redis.RedisError):
                client.delete(_key(conn_id, kid))
        with _lock:
            _mem.pop(_key(conn_id, kid), None)


def _next_rr(conn_id: str) -> int:
    client = _client()
    if client is not None:
        try:
            n = int(client.incr(f"genio:llmkey:{conn_id}:rr"))
            client.expire(f"genio:llmkey:{conn_id}:rr", STATE_TTL)
            return n - 1
        except redis.RedisError:
            pass
    with _lock:
        n = _rr.get(conn_id, 0)
        _rr[conn_id] = n + 1
        return n


def _weighted_order(keys: list[KeyRef]) -> list[KeyRef]:
    """비중이 큰 키가 앞에 올 확률이 높은 순서(뽑은 키는 빼고 다시 뽑는다)."""
    left = list(keys)
    out: list[KeyRef] = []
    while left:
        pick = rng.choices(left, weights=[max(1, k.weight) for k in left], k=1)[0]
        out.append(pick)
        left.remove(pick)
    return out


def order(conn_id: str, keys: list[KeyRef], strategy: str) -> list[KeyRef]:
    """이번 호출에서 시도할 키 순서. 쉬는 중인 키는 맨 뒤(곧 풀리는 순)에 둔다."""
    now = clock()
    ready: list[KeyRef] = []
    cooling: list[tuple[float, KeyRef]] = []
    for k in keys:
        until = float(state(conn_id, k.id)["cooldown_until"])
        if until > now:
            cooling.append((until, k))
        else:
            ready.append(k)
    if len(ready) > 1:
        if strategy == "round_robin":
            start = _next_rr(conn_id) % len(ready)
            ready = ready[start:] + ready[:start]
        elif strategy == "weighted":
            ready = _weighted_order(ready)
    return ready + [k for _, k in sorted(cooling, key=lambda t: t[0])]
