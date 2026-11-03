"""워커 태스크: 흐름 실행, 문서 임베딩, 예약 실행(beat)."""

from api.db import SessionLocal
from api.engine.executor import execute_run
from api.services.knowledge import process_document
from api.services.limits import apply_retention, check_alerts
from api.services.memory import summarize_conversation
from api.services.tracing import send_run
from api.services.triggers import dispatch_schedules
from worker.celery_app import celery


@celery.task(name="genio.summarize_conversation")  # type: ignore[untyped-decorator]
def summarize_conversation_task(conversation_id: str) -> bool:
    """v0.6: 기억 창보다 오래된 대화를 요약해 둔다(요약을 켠 앱만)."""
    with SessionLocal() as db:
        return summarize_conversation(db, conversation_id)


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


@celery.task(name="genio.check_alerts")  # type: ignore[untyped-decorator]
def check_alerts_task() -> int:
    """실패·비용 알림 메일(워크스페이스 설정에 받는 사람·메일 연결 정보가 있을 때만)."""
    with SessionLocal() as db:
        return check_alerts(db)


@celery.task(name="genio.apply_retention")  # type: ignore[untyped-decorator]
def apply_retention_task() -> dict[str, int]:
    """보관 기간이 지난 실행 기록·대화를 지운다."""
    with SessionLocal() as db:
        return apply_retention(db)


@celery.task(name="genio.send_trace")  # type: ignore[untyped-decorator]
def send_trace_task(run_id: str) -> dict[str, str | None]:
    """v0.6 외부 추적: 끝난 실행을 Langfuse·LangSmith로 보낸다(실패해도 실행과 무관)."""
    with SessionLocal() as db:
        return send_run(db, run_id)
