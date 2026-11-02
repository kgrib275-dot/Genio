"""Celery 앱 정의. 태스크는 2단계 이후 엔진 실행용으로 추가한다."""

import os

from celery import Celery

celery = Celery(
    "genio",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Seoul",
    task_track_started=True,
)


@celery.task(name="genio.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    return "pong"
