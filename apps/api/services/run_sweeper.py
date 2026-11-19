"""멈춘 실행 정리: 큐가 잠깐 끊겨 대기 상태로 남은 실행은 다시 큐에 넣고, 워커가 죽어 '실행 중'으로
남은 실행은 실패로 표시한다. 워커 beat가 5분마다 부른다(`genio.sweep_stuck_runs`)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from api.models import Run

log = logging.getLogger("genio.sweeper")

# 큐에 넣고 이만큼 지나도 시작하지 않은 실행은 다시 큐에 넣는다(한도 때문에 기다리는 실행은 따로 본다)
REQUEUE_AFTER = timedelta(minutes=5)
MAX_REQUEUES = 3
# 이보다 오래 '실행 중'이면 워커가 죽은 것으로 본다(실행 제한 10분 + 여유)
STUCK_RUNNING_AFTER = timedelta(minutes=15)
STUCK_MESSAGE = "처리 중에 서버가 멈춰서 이 실행을 끝내지 못했어요. 다시 실행해 주세요."
MAX_PER_SWEEP = 200


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def sweep(db: Session, current: datetime | None = None) -> dict[str, list[str]]:
    """돌려주는 값: {"requeued": 다시 큐에 넣을 run id들, "failed": 실패로 표시한 run id들}"""
    cur = current or datetime.now(UTC)
    out: dict[str, list[str]] = {"requeued": [], "failed": []}

    stuck = list(
        db.scalars(
            select(Run)
            .where(
                Run.status == "running",
                Run.started_at.is_not(None),
                Run.started_at < cur - STUCK_RUNNING_AFTER,
            )
            .limit(MAX_PER_SWEEP)
        )
    )
    for run in stuck:
        # 그 사이 끝났을 수 있으니 상태가 아직 running일 때만 실패로 바꾼다(원자적)
        res = db.execute(
            update(Run)
            .where(Run.id == run.id, Run.status == "running")
            .values(status="failed", error=STUCK_MESSAGE, finished_at=cur)
        )
        if getattr(res, "rowcount", 0):
            out["failed"].append(run.id)
    db.commit()

    queued = list(
        db.scalars(
            select(Run)
            .where(Run.status == "queued", Run.created_at < cur - REQUEUE_AFTER)
            .order_by(Run.created_at)
            .limit(MAX_PER_SWEEP)
        )
    )
    for run in queued:
        ctx: dict[str, Any] = dict(run.context or {})
        # 한도 때문에 기다리는 실행은 스스로 다시 큐에 넣으니 건드리지 않는다
        if ctx.get("capacity_wait"):
            since = (
                _aware(datetime.fromisoformat(str(ctx["capacity_wait"].get("since"))))
                if ctx["capacity_wait"].get("since")
                else None
            )
            if since is None or since > cur - timedelta(minutes=45):
                continue
        count = int(ctx.get("requeued") or 0)
        last_raw = ctx.get("requeued_at")
        last = _aware(datetime.fromisoformat(str(last_raw))) if last_raw else None
        if last is not None and last > cur - REQUEUE_AFTER:
            continue
        if count >= MAX_REQUEUES:
            res = db.execute(
                update(Run)
                .where(Run.id == run.id, Run.status == "queued")
                .values(
                    status="failed",
                    error="실행을 시작하지 못했어요. 서버 상태를 확인한 뒤 다시 실행해 주세요.",
                    finished_at=cur,
                )
            )
            if getattr(res, "rowcount", 0):
                out["failed"].append(run.id)
            continue
        run.context = {**ctx, "requeued": count + 1, "requeued_at": cur.isoformat()}
        out["requeued"].append(run.id)
    db.commit()
    return out
