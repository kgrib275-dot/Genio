"""앱 한 줄 요약: 오늘·이번 주에 몇 건 처리하고 몇 건 실패했는지, 실패 이유는 무엇인지."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models import App, Run
from api.services import pii
from api.services.impact import NOT_COUNTED_TRIGGERS

KST = ZoneInfo("Asia/Seoul")


def _day_start(now: datetime) -> datetime:
    local = now.astimezone(KST)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def _counts(db: Session, app_id: str, since: datetime) -> dict[str, int]:
    rows = db.execute(
        select(Run.status, func.count())
        .where(
            Run.app_id == app_id,
            Run.created_at >= since,
            Run.trigger.not_in(NOT_COUNTED_TRIGGERS),
        )
        .group_by(Run.status)
    ).all()
    by = {str(s): int(n) for s, n in rows}
    return {
        "succeeded": by.get("succeeded", 0),
        "failed": by.get("failed", 0),
        "total": sum(by.values()),
    }


def _reason(error: str | None) -> str:
    first = (error or "원인을 알 수 없어요").strip().splitlines()[0]
    return first[:80]


def build(db: Session, app: App, now: datetime | None = None) -> dict[str, Any]:
    n = now or datetime.now(UTC)
    today_start = _day_start(n)
    week_start = _day_start(n - timedelta(days=6))
    today = _counts(db, app.id, today_start)
    week = _counts(db, app.id, week_start)
    errors = db.scalars(
        select(Run.error)
        .where(
            Run.app_id == app.id,
            Run.status == "failed",
            Run.created_at >= week_start,
            Run.trigger.not_in(NOT_COUNTED_TRIGGERS),
        )
        .order_by(Run.created_at.desc())
        .limit(200)
    )
    masked = pii.logs_masked(db, app.workspace_id)
    counter: Counter[str] = Counter(pii.mask(_reason(e)) if masked else _reason(e) for e in errors)
    reasons = [{"reason": r, "count": c} for r, c in counter.most_common(3)]
    if today["total"] == 0 and week["total"] == 0:
        headline = "이번 주에는 아직 실행된 적이 없어요."
    elif today["total"] == 0:
        headline = f"오늘은 아직 실행이 없어요. 이번 주에는 {week['succeeded']}건 처리했어요."
    else:
        headline = f"오늘 {today['succeeded']}건 처리"
        headline += f", {today['failed']}건 실패" if today["failed"] else ", 실패는 없어요"
    return {"today": today, "week": week, "failure_reasons": reasons, "headline": headline}
