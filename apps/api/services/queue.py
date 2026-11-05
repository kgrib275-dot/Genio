"""작업 큐에 넣기. API는 상태를 갖지 않고 실행은 워커(Celery)가 한다.

GENIO_RUN_INLINE=true(테스트)이면 워커 없이 바로 실행한다.
"""

from functools import lru_cache

from celery import Celery

from api.config import get_settings

EXECUTE_RUN = "genio.execute_run"
PROCESS_DOCUMENT = "genio.process_document"
SUMMARIZE_CONVERSATION = "genio.summarize_conversation"
SYNC_KB_SOURCE = "genio.sync_kb_source"


def enqueue_source_sync(kb_id: str, source_id: str) -> None:
    """v0.8 지식 가져오기 소스를 워커에서 동기화한다(시험에서는 바로 실행)."""
    if get_settings().genio_run_inline:
        from api.db import SessionLocal
        from api.services.kb_sources import sync_source

        with SessionLocal() as db:
            sync_source(db, kb_id, source_id)
        return
    _client().send_task(SYNC_KB_SOURCE, args=[kb_id, source_id])


def enqueue_summary(conversation_id: str) -> None:
    """v0.6 대화 기억 요약(요약을 켠 앱만 실제로 AI를 부른다). 실패해도 대화에는 영향이 없다."""
    if get_settings().genio_run_inline:
        from api.db import SessionLocal
        from api.services.memory import summarize_conversation

        with SessionLocal() as db:
            summarize_conversation(db, conversation_id)
        return
    try:
        _client().send_task(SUMMARIZE_CONVERSATION, args=[conversation_id])
    except Exception:  # 큐가 잠깐 안 돼도 답은 이미 저장됐다
        import logging

        logging.getLogger("genio.queue").warning("대화 요약 작업을 큐에 넣지 못함")


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
