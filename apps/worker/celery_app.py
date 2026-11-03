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
)


@celery.task(name="genio.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    return "pong"
