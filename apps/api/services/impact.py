"""효과 리포트: 앱마다 '한 번 성공할 때 아끼는 시간(분)'을 정해 두면 기간 안 성공 횟수로 아낀 시간을 계산한다.

추정값이다(실제로 잰 시간이 아니다). 시험·미리 보기·다시 실행·실패 알림·하위 실행은 세지 않는다.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models import App, Run
from api.services.app_config import merged_features

NOT_COUNTED_TRIGGERS = ("test", "preview", "rerun", "on_failure", "subflow", "tool")
MAX_MINUTES_PER_RUN = 24 * 60


def minutes_per_run(features: dict[str, Any] | None) -> int:
    raw = merged_features(features).get("time_saved", {}).get("minutes_per_run")
    try:
        return max(0, min(int(raw or 0), MAX_MINUTES_PER_RUN))
    except (TypeError, ValueError):
        return 0


def report(
    db: Session, workspace_id: str, start: datetime | None, end: datetime | None
) -> dict[str, Any]:
    q = (
        select(Run.app_id, func.count())
        .join(App, App.id == Run.app_id)
        .where(
            App.workspace_id == workspace_id,
            Run.status == "succeeded",
            Run.trigger.not_in(NOT_COUNTED_TRIGGERS),
        )
        .group_by(Run.app_id)
    )
    if start:
        q = q.where(Run.created_at >= start)
    if end:
        q = q.where(Run.created_at <= end)
    counts = {app_id: int(n) for app_id, n in db.execute(q).all()}
    apps = list(db.scalars(select(App).where(App.workspace_id == workspace_id)))
    rows: list[dict[str, Any]] = []
    total_min = 0
    total_runs = 0
    for a in apps:
        n = counts.get(a.id, 0)
        per = minutes_per_run(a.features)
        saved = n * per
        total_runs += n
        total_min += saved
        if n or per:
            rows.append(
                {
                    "app_id": a.id,
                    "app_name": a.name,
                    "succeeded_runs": n,
                    "minutes_per_run": per,
                    "saved_minutes": saved,
                }
            )
    rows.sort(key=lambda r: (r["saved_minutes"], r["succeeded_runs"]), reverse=True)
    return {
        "apps": rows,
        "total_succeeded_runs": total_runs,
        "total_saved_minutes": total_min,
        "total_saved_hours": round(total_min / 60, 1),
        "unset_apps": sum(1 for r in rows if r["minutes_per_run"] == 0 and r["succeeded_runs"]),
        "estimate": True,
    }
