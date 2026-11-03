"""워커 태스크: 흐름 실행, 문서 임베딩."""

from api.db import SessionLocal
from api.engine.executor import execute_run
from api.services.knowledge import process_document
from worker.celery_app import celery


@celery.task(name="genio.execute_run")  # type: ignore[untyped-decorator]
def execute_run_task(run_id: str) -> None:
    execute_run(run_id)


@celery.task(name="genio.process_document")  # type: ignore[untyped-decorator]
def process_document_task(document_id: str) -> None:
    with SessionLocal() as db:
        process_document(db, document_id)
