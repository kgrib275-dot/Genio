"""워커 태스크: 흐름 실행, 문서 임베딩, 예약 실행(beat)."""

from api.db import SessionLocal
from api.engine.executor import execute_run
from api.services.knowledge import process_document
from api.services.triggers import dispatch_schedules
from worker.celery_app import celery


@celery.task(name="genio.execute_run")  # type: ignore[untyped-decorator]
def execute_run_task(run_id: str) -> None:
    execute_run(run_id)


@celery.task(name="genio.process_document")  # type: ignore[untyped-decorator]
def process_document_task(document_id: str) -> None:
    with SessionLocal() as db:
        process_document(db, document_id)


@celery.task(name="genio.dispatch_schedules")  # type: ignore[untyped-decorator]
def dispatch_schedules_task() -> int:
    """next_run_at이 지난 예약 자동 실행을 큐에 넣는다(beat가 1분마다 부름)."""
    with SessionLocal() as db:
        return len(dispatch_schedules(db))
