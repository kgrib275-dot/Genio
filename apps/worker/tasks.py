"""워커 태스크: 흐름 실행, 문서 임베딩, 예약 실행(beat)."""

from api.core.errors import AppError
from api.db import SessionLocal
from api.engine.executor import execute_run
from api.models import KnowledgeBase
from api.services.kb_sources import begin_sync, due_sources, sync_source
from api.services.knowledge import process_document
from api.services.limits import apply_retention, check_alerts
from api.services.memory import summarize_conversation
from api.services.tasks import sweep as sweep_human_tasks
from api.services.tracing import send_run
from api.services.triggers import dispatch_schedules
from worker.celery_app import celery


@celery.task(name="genio.sync_kb_source")  # type: ignore[untyped-decorator]
def sync_kb_source_task(kb_id: str, source_id: str) -> dict[str, str]:
    """v0.8 지식 가져오기 소스(웹사이트·노션·Google 문서)를 동기화한다."""
    with SessionLocal() as db:
        res = sync_source(db, kb_id, source_id)
    return {"status": str(res.get("last_status", ""))}


@celery.task(name="genio.sync_due_sources")  # type: ignore[untyped-decorator]
def sync_due_sources_task() -> int:
    """'매일 동기화'로 정해 둔 소스 중 하루가 지난 것을 큐에 넣는다(beat가 한 시간마다 부름)."""
    from api.services.queue import enqueue_source_sync

    queued = 0
    with SessionLocal() as db:
        for kb_id, sid in due_sources(db):
            kb = db.get(KnowledgeBase, kb_id)
            if kb is None:
                continue
            try:
                begin_sync(db, kb, sid)
            except AppError:
                continue  # 이미 도는 중이면 다음 시간에
            enqueue_source_sync(kb_id, sid)
            queued += 1
    return queued


@celery.task(name="genio.sweep_human_tasks")  # type: ignore[untyped-decorator]
def sweep_human_tasks_task() -> dict[str, int]:
    """v0.9: 기한이 지난 사람 단계를 정해 둔 대로 처리하고, 기한 직전 일은 한 번 다시 알린다."""
    from api.services.queue import enqueue_run

    with SessionLocal() as db:
        res = sweep_human_tasks(db)
    for run_id in res["resume"]:
        enqueue_run(run_id)
    return {k: len(v) for k, v in res.items()}


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
