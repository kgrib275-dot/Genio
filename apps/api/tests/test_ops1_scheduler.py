"""운영 준비 1차 A2: 시스템 상태의 '예약 실행' 항목."""

import time
from typing import Any

import pytest

from api.config import get_settings
from api.services import status as status_service


class R:
    def __init__(self, v: Any = None, fail: bool = False) -> None:
        self.v, self.fail = v, fail

    def get(self, k: str) -> Any:
        assert k == status_service.BEAT_LAST_KEY
        if self.fail:
            raise RuntimeError("down")
        return self.v


@pytest.fixture(autouse=True)
def not_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "genio_run_inline", False)


def test_recent_beat_ok() -> None:
    it = status_service._scheduler(R(str(int(time.time()) - 30).encode()))
    assert it["status"] == "ok" and it["label"] == "예약 실행"


def test_stale_beat_error() -> None:
    it = status_service._scheduler(R(str(int(time.time()) - 900).encode()))
    assert it["status"] == "error" and "15분" in it["detail"]


def test_no_record_warn() -> None:
    assert status_service._scheduler(R(None))["status"] == "warn"


def test_unknown_without_redis() -> None:
    assert status_service._scheduler(None)["status"] == "unknown"
    assert status_service._scheduler(R(fail=True))["status"] == "unknown"


def test_worker_and_singleton_share_key() -> None:
    from worker.singleton import last_run_key

    assert last_run_key("dispatch_schedules") == status_service.BEAT_LAST_KEY
