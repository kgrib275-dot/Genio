"""작업 큐에 넣기. API는 상태를 갖지 않고 실행은 워커(Celery)가 한다.

GENIO_RUN_INLINE=true(테스트)이면 워커 없이 바로 실행한다.
"""

from functools import lru_cache

from celery import Celery

from api.config import get_settings

EXECUTE_RUN = "genio.execute_run"
PROCESS_DOCUMENT = "genio.process_document"


@lru_cache
def _client() -> Celery:
    s = get_settings()
    return Celery("genio-api", broker=s.celery_broker_url or s.redis_url or "memory://")


def enqueue_run(run_id: str) -> None:
    if get_settings().genio_run_inline:
        from api.engine.executor import execute_run

        execute_run(run_id)
        return
    _client().send_task(EXECUTE_RUN, args=[run_id])


def enqueue_document(document_id: str) -> None:
    if get_settings().genio_run_inline:
        from api.db import SessionLocal
        from api.services.knowledge import process_document

        with SessionLocal() as db:
            process_document(db, document_id)
        return
    _client().send_task(PROCESS_DOCUMENT, args=[document_id])
