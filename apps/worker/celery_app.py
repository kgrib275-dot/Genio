"""Celery 워커. api 패키지를 그대로 재사용한다."""

import os

from celery import Celery

celery = Celery(
    "genio",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
    include=["worker.tasks"],
)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Seoul",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # 실행 10분 제한(설계서 §5) + 여유
    task_time_limit=11 * 60,
    # v0.4: 1분마다 예약 실행 확인(워커를 `-B`로 띄워 beat를 함께 돌린다. 워커가 여럿이면 하나만 -B)
    beat_schedule={
        "dispatch-schedules": {"task": "genio.dispatch_schedules", "schedule": 60.0},
    },
)


@celery.task(name="genio.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    return "pong"
