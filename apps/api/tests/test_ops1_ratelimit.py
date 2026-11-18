"""운영 준비 1차 A1: 속도 제한을 여러 API 프로세스가 Redis로 함께 세는지, Redis가 끊기면 어떻게 되는지."""

import time
from typing import Any

import pytest
import redis

from api.config import get_settings
from api.core import ratelimit
from api.services import status as status_service


class FakeRedis:
    """여러 API 프로세스가 함께 쓰는 Redis 흉내(incr·expire nx·get·delete·pipeline)."""

    def __init__(self) -> None:
        self.data: dict[str, int] = {}
        self.ttl: dict[str, int] = {}
        self.calls = 0

    def incr(self, k: str) -> int:
        self.calls += 1
        self.data[k] = self.data.get(k, 0) + 1
        return self.data[k]

    def expire(self, k: str, sec: int, nx: bool = False) -> bool:
        if nx and k in self.ttl:
            return False
        self.ttl[k] = sec
        return True

    def get(self, k: str) -> bytes | None:
        self.calls += 1
        v = self.data.get(k)
        return None if v is None else str(v).encode()

    def delete(self, k: str) -> int:
        return 1 if self.data.pop(k, None) is not None else 0

    def pipeline(self) -> "FakePipe":
        return FakePipe(self)


class FakePipe:
    def __init__(self, r: FakeRedis) -> None:
        self.r = r
        self.ops: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def incr(self, k: str) -> None:
        self.ops.append(("incr", (k,), {}))

    def expire(self, k: str, sec: int, nx: bool = False) -> None:
        self.ops.append(("expire", (k, sec), {"nx": nx}))

    def execute(self) -> list[Any]:
        return [getattr(self.r, name)(*a, **kw) for name, a, kw in self.ops]


class BrokenRedis(FakeRedis):
    def incr(self, k: str) -> int:
        self.calls += 1
        raise redis.ConnectionError("down")

    def get(self, k: str) -> bytes | None:
        self.calls += 1
        raise redis.ConnectionError("down")

    def pipeline(self) -> "FakePipe":
        self.calls += 1
        raise redis.ConnectionError("down")


@pytest.fixture
def with_redis(monkeypatch: pytest.MonkeyPatch) -> Any:
    def use(client: FakeRedis) -> FakeRedis:
        monkeypatch.setattr(ratelimit, "_redis_client", lambda: client)
        monkeypatch.setattr(get_settings(), "redis_url", "redis://fake:6379/0")
        return client

    return use


def test_processes_share_one_limit(with_redis: Any) -> None:
    """프로세스 메모리가 아니라 Redis 한 곳에서 세므로, 메모리를 비워도(다른 프로세스) 한도가 이어진다."""
    with_redis(FakeRedis())
    for _ in range(3):
        assert ratelimit.allow("ip:1", 5)
        ratelimit._hits.clear()  # 다른 프로세스라면 메모리는 비어 있다
    assert ratelimit.allow("ip:1", 5)
    assert ratelimit.allow("ip:1", 5)
    assert not ratelimit.allow("ip:1", 5)
    assert not ratelimit._hits  # 메모리로는 세지 않았다


def test_expire_set_once_per_bucket(with_redis: Any) -> None:
    r = with_redis(FakeRedis())
    ratelimit.allow("ip:2", 5, window=60)
    first = dict(r.ttl)
    ratelimit.allow("ip:2", 5, window=60)
    assert r.ttl == first and list(first.values()) == [65]


def test_login_fails_shared(with_redis: Any) -> None:
    with_redis(FakeRedis())
    assert ratelimit.add_fail("login:a", 900) == 1
    ratelimit._fails.clear()
    assert ratelimit.add_fail("login:a", 900) == 2
    assert ratelimit.fail_count("login:a", 900) == 2
    ratelimit.clear_fails("login:a")
    assert ratelimit.fail_count("login:a", 900) == 0


def test_redis_down_falls_back_and_backs_off(with_redis: Any) -> None:
    r = with_redis(BrokenRedis())
    assert ratelimit.allow("ip:3", 2)
    calls = r.calls
    # 쉬는 동안은 Redis를 다시 부르지 않고 메모리로 센다(요청마다 연결을 기다리지 않음)
    assert ratelimit.allow("ip:3", 2)
    assert not ratelimit.allow("ip:3", 2)
    assert ratelimit.fail_count("x", 60) == 0
    assert r.calls == calls
    st = ratelimit.backend_state()
    assert st["configured"] and st["degraded"] and st["last_fallback"]
    item = status_service._ratelimit(redis_ok=True)
    assert item["status"] == "warn" and item["mode"] == "memory"


def test_redis_retried_after_backoff(with_redis: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    with_redis(BrokenRedis())
    ratelimit.allow("ip:4", 5)
    assert ratelimit.backend_state()["degraded"]
    good = with_redis(FakeRedis())
    monkeypatch.setattr(ratelimit, "BACKOFF_SECONDS", 0.0)
    ratelimit._state["skip_until"] = time.time() - 1
    assert ratelimit.allow("ip:4", 5)
    assert good.calls == 1
    assert not ratelimit.backend_state()["degraded"]
    assert status_service._ratelimit(redis_ok=True)["status"] == "ok"


def test_status_without_redis_config() -> None:
    item = status_service._ratelimit(redis_ok=False)
    assert item["status"] == "unknown" and item["label"] == "속도 제한"
