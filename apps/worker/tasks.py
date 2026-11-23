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
from worker.singleton import run_once


@celery.task(name="genio.sync_kb_source")  # type: ignore[untyped-decorator]
def sync_kb_source_task(kb_id: str, source_id: str) -> dict[str, str]:
    """v0.8 지식 가져오기 소스(웹사이트·노션·Google 문서)를 동기화한다."""
    with SessionLocal() as db:
        res = sync_source(db, kb_id, source_id)
    return {"status": str(res.get("last_status", ""))}


@celery.task(name="genio.sync_due_sources")  # type: ignore[untyped-decorator]
def sync_due_sources_task() -> int:
    """'매일 동기화'로 정해 둔 소스 중 하루가 지난 것을 큐에 넣는다(beat가 한 시간마다 부름)."""
    return run_once("sync_due_sources", 3600, _sync_due_sources) or 0


def _sync_due_sources() -> int:
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
    return run_once("sweep_human_tasks", 300, _sweep_human_tasks) or {}


def _sweep_human_tasks() -> dict[str, int]:
    from api.services.queue import enqueue_run

    with SessionLocal() as db:
        res = sweep_human_tasks(db)
    for run_id in res["resume"]:
        enqueue_run(run_id)
    return {k: len(v) for k, v in res.items()}


@celery.task(name="genio.sweep_stuck_runs")  # type: ignore[untyped-decorator]
def sweep_stuck_runs_task() -> dict[str, int]:
    """큐가 끊겨 대기로 남은 실행은 다시 큐에 넣고, 워커가 죽어 실행 중으로 남은 실행은 실패로 표시한다."""
    return run_once("sweep_stuck_runs", 300, _sweep_stuck_runs) or {}


def _sweep_stuck_runs() -> dict[str, int]:
    from api.services.queue import enqueue_run
    from api.services.run_sweeper import sweep

    with SessionLocal() as db:
        res = sweep(db)
    for run_id in res["requeued"]:
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

    def go() -> int:
        with SessionLocal() as db:
            return len(dispatch_schedules(db))

    return run_once("dispatch_schedules", 60, go, lock_seconds=300) or 0


@celery.task(name="genio.check_alerts")  # type: ignore[untyped-decorator]
def check_alerts_task() -> int:
    """실패·비용 알림 메일(워크스페이스 설정에 받는 사람·메일 연결 정보가 있을 때만)."""

    def go() -> int:
        with SessionLocal() as db:
            return check_alerts(db)

    return run_once("check_alerts", 300, go) or 0


@celery.task(name="genio.apply_retention")  # type: ignore[untyped-decorator]
def apply_retention_task() -> dict[str, int]:
    """보관 기간이 지난 실행 기록·대화를 지운다."""

    def go() -> dict[str, int]:
        with SessionLocal() as db:
            return apply_retention(db)

    return run_once("apply_retention", 24 * 3600, go, lock_seconds=3600) or {}


@celery.task(name="genio.send_trace")  # type: ignore[untyped-decorator]
def send_trace_task(run_id: str) -> dict[str, str | None]:
    """v0.6 외부 추적: 끝난 실행을 Langfuse·LangSmith로 보낸다(실패해도 실행과 무관)."""
    with SessionLocal() as db:
        return send_run(db, run_id)


@celery.task(name="genio.refresh_trends")  # type: ignore[untyped-decorator]
def refresh_trends_task() -> dict[str, object]:
    """'이번 주 새로 나온 것' 목록을 공개 목록(MCP 레지스트리·n8n 템플릿)에서 모아 저장한다(하루 한 번)."""
    from api.services import trends

    def go() -> dict[str, object]:
        data = trends.refresh()
        return {
            "mcp_new": len(data.get("mcp_new", [])),
            "n8n_new": len(data.get("n8n_new", [])),
            "n8n_popular": len(data.get("n8n_popular", [])),
            "errors": len(data.get("errors", [])),
        }

    return run_once("refresh_trends", 24 * 3600, go, lock_seconds=600) or {}


@celery.task(name="genio.health_alert")  # type: ignore[untyped-decorator]
def health_alert_task() -> dict[str, object]:
    """서비스 이상 알림: 오류가 난 항목을 서비스 관리자에게 메일·웹훅으로 알린다(중복은 막는다)."""
    from api.services import health_alert

    def go() -> dict[str, object]:
        with SessionLocal() as db:
            return dict(health_alert.check(db))

    return run_once("health_alert", 300, go) or {}


@celery.task(name="genio.offsite_backup")  # type: ignore[untyped-decorator]
def offsite_backup_task() -> dict[str, object]:
    """운영 준비 1차(A3): 최근 DB 백업을 바깥 저장소에 올리고 오래된 것은 지운다(한 시간마다)."""
    from api.services import offsite_backup

    if not offsite_backup.enabled():
        return {"status": "off"}
    return run_once("offsite_backup", 3600, offsite_backup.sync, lock_seconds=3000) or {}
