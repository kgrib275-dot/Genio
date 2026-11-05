"""앱 단위 실시간 알림(v0.9): 같은 앱을 연 사람들에게 접속 표시·작업본 변경·댓글 변경을 알린다.

Redis pub/sub을 쓰고(서버가 여러 프로세스여도 Redis 하나를 같이 쓰면 닿는다), Redis가 없으면
같은 프로세스 안에서만 전달한다(테스트·로컬). 알림은 '신호'일 뿐이라 놓쳐도 화면이 다시 읽으면 된다.
"""

import contextlib
import json
import logging
import queue
import threading
from typing import Any

import redis

from api.engine import events

log = logging.getLogger("genio.appbus")

# Redis가 없을 때: app_id → 구독 큐 모음
_LOCAL: dict[str, set["queue.Queue[dict[str, Any]]"]] = {}
_LOCK = threading.Lock()
MAX_QUEUE = 200


def channel(app_id: str) -> str:
    return f"genio:app:{app_id}"


class Subscription:
    """get(timeout)으로 알림을 하나씩 읽고, 끝나면 close()."""

    def __init__(self, app_id: str) -> None:
        self.app_id = app_id
        self._pubsub: redis.client.PubSub | None = None
        self._queue: queue.Queue[dict[str, Any]] | None = None
        client = events._client()
        if client is not None:
            try:
                ps = client.pubsub(ignore_subscribe_messages=True)
                ps.subscribe(channel(app_id))
                self._pubsub = ps
                return
            except redis.RedisError:
                log.warning("앱 알림 구독 실패(app=%s) — 이 프로세스 안에서만 받아요", app_id)
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=MAX_QUEUE)
        self._queue = q
        with _LOCK:
            _LOCAL.setdefault(app_id, set()).add(q)

    def get(self, timeout: float) -> dict[str, Any] | None:
        if self._pubsub is not None:
            try:
                msg = self._pubsub.get_message(timeout=timeout)
            except redis.RedisError:
                return None
            if not msg:
                return None
            try:
                data = json.loads(msg["data"])
            except (ValueError, TypeError, KeyError):
                return None
            return data if isinstance(data, dict) else None
        if self._queue is None:
            return None
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        if self._pubsub is not None:
            with contextlib.suppress(redis.RedisError):
                self._pubsub.close()
            self._pubsub = None
        if self._queue is not None:
            with _LOCK:
                subs = _LOCAL.get(self.app_id)
                if subs is not None:
                    subs.discard(self._queue)
                    if not subs:
                        _LOCAL.pop(self.app_id, None)
            self._queue = None


def subscribe(app_id: str) -> Subscription:
    return Subscription(app_id)


def publish(app_id: str, event: str, data: dict[str, Any]) -> None:
    """알림을 보낸다. 실패해도 저장·요청은 막지 않는다."""
    payload = {"event": event, "data": data}
    try:
        client = events._client()
        if client is not None:
            client.publish(channel(app_id), json.dumps(payload, ensure_ascii=False, default=str))
            return
    except redis.RedisError:
        log.warning("앱 알림 보내기 실패(app=%s)", app_id)
        return
    with _LOCK:
        targets = list(_LOCAL.get(app_id, ()))
    for q in targets:
        with contextlib.suppress(queue.Full):
            q.put_nowait(payload)


def reset_local() -> None:
    """테스트용: 같은 프로세스 구독을 모두 지운다."""
    with _LOCK:
        _LOCAL.clear()
