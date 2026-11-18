"""운영 준비 1차 A2: 주기 작업은 beat가 둘 떠도 한 주기에 한 번만, 겹치지 않게 돈다."""

import time
from typing import Any

import pytest
import redis

from worker import singleton


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def set(self, k: str, v: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and k in self.data:
            return False
        self.data[k] = v.encode()
        return True

    def get(self, k: str) -> bytes | None:
        return self.data.get(k)

    def delete(self, k: str) -> int:
        return 1 if self.data.pop(k, None) is not None else 0


class DownRedis(FakeRedis):
    def set(self, k: str, v: str, nx: bool = False, ex: int | None = None) -> bool:
        raise redis.ConnectionError("down")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Any:
    def use(r: FakeRedis) -> FakeRedis:
        monkeypatch.setattr(singleton, "_redis", lambda: r)
        return r

    return use


def test_runs_without_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(singleton, "_redis", lambda: None)
    assert singleton.run_once("x", 60, lambda: 7) == 7
    assert singleton.run_once("x", 60, lambda: 8) == 8


def test_two_beats_same_period_run_once(fake: Any) -> None:
    r = fake(FakeRedis())
    calls: list[int] = []

    def job(n: int) -> int:
        calls.append(n)
        return n

    assert singleton.run_once("dispatch", 60, lambda: job(1)) == 1
    # 두 번째 beat가 같은 주기에 보낸 같은 작업
    assert singleton.run_once("dispatch", 60, lambda: job(2)) is None
    assert calls == [1]
    assert r.get(singleton.last_run_key("dispatch")) is not None
    assert "genio:lock:dispatch" not in r.data  # 끝나면 잠금을 푼다


def test_overlapping_run_skipped(fake: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    r = fake(FakeRedis())
    r.data["genio:lock:retention"] = b"someone-else"
    assert singleton.run_once("retention", 60, lambda: 1) is None
    # 남의 잠금은 지우지 않는다
    assert r.data["genio:lock:retention"] == b"someone-else"


def test_next_period_runs_again(fake: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    fake(FakeRedis())
    now = [1_000_000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    assert singleton.run_once("d", 60, lambda: 1) == 1
    now[0] += 61
    assert singleton.run_once("d", 60, lambda: 2) == 2


def test_redis_down_still_runs(fake: Any) -> None:
    fake(DownRedis())
    assert singleton.run_once("d", 60, lambda: 3) == 3


def test_failure_releases_lock(fake: Any) -> None:
    r = fake(FakeRedis())

    def boom() -> int:
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        singleton.run_once("f", 60, boom)
    assert "genio:lock:f" not in r.data


def test_beat_tasks_use_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    from worker import tasks

    seen: list[str] = []

    def spy(name: str, period: float, fn: Any, lock_seconds: float = 600) -> Any:
        seen.append(name)
        return None

    monkeypatch.setattr(tasks, "run_once", spy)
    assert tasks.dispatch_schedules_task.run() == 0
    assert tasks.check_alerts_task.run() == 0
    assert tasks.apply_retention_task.run() == {}
    assert tasks.sweep_human_tasks_task.run() == {}
    assert tasks.sync_due_sources_task.run() == 0
    assert seen == [
        "dispatch_schedules",
        "check_alerts",
        "apply_retention",
        "sweep_human_tasks",
        "sync_due_sources",
    ]
