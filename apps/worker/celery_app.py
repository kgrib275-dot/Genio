"""Celery 워커. api 패키지를 그대로 재사용한다."""

import os

from celery import Celery

from api.core.observability import setup_logging
from api.core.sentry import init_sentry

init_sentry("worker")  # SENTRY_DSN이 있을 때만 켜진다(v0.8)
setup_logging("worker")  # 운영 준비 1차(A6): GENIO_LOG_FORMAT=json이면 JSON 한 줄 로그

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
    # 운영 준비 1차(A6): 로그 형식은 setup_logging이 정한다(Celery가 바꾸지 않게)
    worker_hijack_root_logger=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # 실행 10분 제한(설계서 §5) + 여유
    task_time_limit=11 * 60,
    # v0.4: 1분마다 예약 실행 확인. 운영 준비 1차(A2): beat는 compose의 `scheduler` 서비스 하나가 돌리고
    # 워커는 실행만 한다(워커를 늘려도 예약이 겹치지 않음). 겹쳐 떠도 worker/singleton.py가 한 번만 실행한다.
    beat_schedule={
        "dispatch-schedules": {"task": "genio.dispatch_schedules", "schedule": 60.0},
        # v0.5: 실패·비용 알림(5분), 보관 기간이 지난 기록 지우기(하루 한 번)
        "check-alerts": {"task": "genio.check_alerts", "schedule": 300.0},
        "apply-retention": {"task": "genio.apply_retention", "schedule": 24 * 3600.0},
        # v0.9: 기한이 지난 사람 단계 처리(자동 반려·승인·올리기·시간 초과 길)와 기한 전 다시 알림
        "sweep-human-tasks": {"task": "genio.sweep_human_tasks", "schedule": 300.0},
        # v0.8: '매일 동기화'로 정해 둔 지식 가져오기 소스(웹사이트·노션·Google 문서)
        "sync-due-kb-sources": {"task": "genio.sync_due_sources", "schedule": 3600.0},
    },
)


@celery.task(name="genio.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    return "pong"
