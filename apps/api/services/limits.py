"""워크스페이스 한도·알림·보관 기간(기능 정의서 §5·§6 P1, S8).

설정은 workspaces.settings["limits"]에 둔다(마이그레이션 없음):
  monthly_budget_usd   이번 달 비용이 이 값을 넘으면 새 실행을 막는다(None = 제한 없음)
  cost_alert_usd       이번 달 비용이 이 값을 넘으면 한 번 메일로 알린다
  (월 한도가 있으면 80%에 이를 때 한 번 미리 메일로 알린다)
  alert_on_failure     실행이 실패하면 메일로 알린다(5분마다 모아서)
  monthly_report       매달 1일(그 뒤 처음 확인 때) 지난달 효과 리포트를 같은 받는 사람에게 메일로 보낸다
  alert_emails         받는 사람
  alert_credential_id  메일을 보낼 'Email (SMTP)' 연결 정보
  retention_days       이보다 오래된 실행 기록·대화를 지운다(None = 계속 보관)
  운영 준비 1차(A9) — 넘으면 새 실행은 실패시키지 않고 잠시 기다렸다 시작한다(최대 CAPACITY_MAX_WAIT_SECONDS)
  max_concurrent_runs          워크스페이스 전체에서 동시에 도는 실행 수
  max_concurrent_runs_per_app  앱 하나가 동시에 돌릴 수 있는 실행 수
  max_runs_per_minute          1분 동안 새로 시작하는 실행 수
  max_file_storage_mb          올린 파일·만든 파일의 총 용량(넘으면 새 파일을 거절)
진행 상태(마지막 확인 시각 등)는 settings["limits_state"]에 둔다.
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from api.models import App, AppTrigger, Conversation, Message, Run, StoredFile, Workspace

log = logging.getLogger("genio.limits")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TERMINAL = ("succeeded", "failed", "cancelled")
DEFAULTS: dict[str, Any] = {
    "monthly_budget_usd": None,
    "cost_alert_usd": None,
    "alert_on_failure": False,
    "monthly_report": False,
    "alert_emails": [],
    "alert_credential_id": None,
    "retention_days": None,
    "max_concurrent_runs": None,
    "max_concurrent_runs_per_app": None,
    "max_runs_per_minute": None,
    "max_file_storage_mb": None,
}
# (설정 이름, 최소, 최대, 화면 이름)
CAPACITY_FIELDS: tuple[tuple[str, int, int, str], ...] = (
    ("max_concurrent_runs", 1, 1000, "동시 실행 수"),
    ("max_concurrent_runs_per_app", 1, 1000, "앱 하나당 동시 실행 수"),
    ("max_runs_per_minute", 1, 100_000, "분당 실행 수"),
    ("max_file_storage_mb", 1, 1_000_000, "파일 저장 용량(MB)"),
)
# 한도 때문에 기다린 실행을 이 시간이 지나면 실패로 끝낸다
CAPACITY_MAX_WAIT_SECONDS = 30 * 60
# 이보다 오래 '실행 중'인 기록은 멈춘 것으로 보고 동시 실행 수에서 뺀다(실행 제한 10분 + 여유)
STALE_RUNNING_SECONDS = 15 * 60


def now_utc() -> datetime:
    return datetime.now(UTC)


def month_start(now: datetime | None = None) -> datetime:
    n = now or now_utc()
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def get_limits(ws: Workspace) -> dict[str, Any]:
    saved = (ws.settings or {}).get("limits") or {}
    return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}


def _num(v: Any, lo: float, hi: float, what: str) -> float | None:
    from api.core.errors import AppError

    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise AppError(422, f"{what}는 숫자로 적어 주세요.", "예: 50 (달러)") from None
    if not (lo <= f <= hi):
        raise AppError(
            422, f"{what}는 {lo:g}~{hi:g} 사이로 적어 주세요.", "비워 두면 제한이 없어요."
        )
    return f


def clean_limits(patch: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    from api.core.errors import AppError

    out = {**current}
    if "monthly_budget_usd" in patch:
        out["monthly_budget_usd"] = _num(patch["monthly_budget_usd"], 0, 1_000_000, "월 한도")
    if "cost_alert_usd" in patch:
        out["cost_alert_usd"] = _num(patch["cost_alert_usd"], 0, 1_000_000, "비용 알림 기준")
    if "alert_on_failure" in patch:
        out["alert_on_failure"] = bool(patch["alert_on_failure"])
    if "monthly_report" in patch:
        out["monthly_report"] = bool(patch["monthly_report"])
    if "alert_emails" in patch:
        emails = [str(e).strip() for e in (patch["alert_emails"] or []) if str(e).strip()][:10]
        bad = [e for e in emails if not EMAIL_RE.match(e)]
        if bad:
            raise AppError(
                422, f"메일 주소 형식이 올바르지 않아요: {bad[0][:60]}", "예: ops@example.com"
            )
        out["alert_emails"] = emails
    if "alert_credential_id" in patch:
        out["alert_credential_id"] = str(patch["alert_credential_id"] or "") or None
    if "retention_days" in patch:
        rd = _num(patch["retention_days"], 7, 3650, "보관 기간(일)")
        out["retention_days"] = int(rd) if rd is not None else None
    for key, lo, hi, label in CAPACITY_FIELDS:
        if key in patch:
            v = _num(patch[key], lo, hi, label)
            out[key] = int(v) if v is not None else None
    return out


def month_cost(db: Session, workspace_id: str, now: datetime | None = None) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(Run.cost), 0))
        .join(App, App.id == Run.app_id)
        .where(App.workspace_id == workspace_id, Run.created_at >= month_start(now))
    )
    return Decimal(str(total or 0))


def check_run_allowed(db: Session, app: App) -> str | None:
    """새 실행을 시작해도 되는지. 막아야 하면 사람이 읽을 이유(두 줄: 문제 + 할 일)."""
    ws = db.get(Workspace, app.workspace_id)
    if ws is None:
        return None
    budget = get_limits(ws).get("monthly_budget_usd")
    if budget is None:
        return None
    used = month_cost(db, ws.id)
    if used >= Decimal(str(budget)):
        return (
            f"이번 달 AI 사용 한도(${float(budget):,.2f})를 다 썼어요(지금 ${float(used):,.2f}).\n"
            "관리자에게 관리 > 사용량에서 월 한도를 늘려 달라고 하세요."
        )
    return None


# ---------------- 운영 준비 1차(A9): 동시 실행·분당 실행·파일 용량 ----------------
def _running_since(now: datetime) -> datetime:
    return now - timedelta(seconds=STALE_RUNNING_SECONDS)


def running_counts(db: Session, workspace_id: str, app_id: str | None = None) -> tuple[int, int]:
    """(워크스페이스에서 지금 도는 실행 수, 그중 이 앱의 수). 멈춘 지 오래된 기록은 뺀다."""
    since = _running_since(now_utc())
    base = (
        select(func.count())
        .select_from(Run)
        .join(App, App.id == Run.app_id)
        .where(
            App.workspace_id == workspace_id,
            Run.status == "running",
            Run.started_at.is_not(None),
            Run.started_at >= since,
        )
    )
    total = int(db.scalar(base) or 0)
    per_app = int(db.scalar(base.where(Run.app_id == app_id)) or 0) if app_id else 0
    return total, per_app


def started_last_minute(db: Session, workspace_id: str) -> int:
    since = now_utc() - timedelta(seconds=60)
    return int(
        db.scalar(
            select(func.count())
            .select_from(Run)
            .join(App, App.id == Run.app_id)
            .where(
                App.workspace_id == workspace_id,
                Run.started_at.is_not(None),
                Run.started_at >= since,
            )
        )
        or 0
    )


def capacity_wait_reason(db: Session, app: App) -> str | None:
    """새 실행을 지금 시작하면 한도를 넘는지. 넘으면 기다리는 이유(짧은 한 줄), 아니면 None."""
    ws = db.get(Workspace, app.workspace_id)
    if ws is None:
        return None
    lim = get_limits(ws)
    total_cap = lim.get("max_concurrent_runs")
    app_cap = lim.get("max_concurrent_runs_per_app")
    rate_cap = lim.get("max_runs_per_minute")
    if total_cap or app_cap:
        total, per_app = running_counts(db, ws.id, app.id)
        if total_cap and total >= int(total_cap):
            return f"워크스페이스 동시 실행 한도({int(total_cap)}개)"
        if app_cap and per_app >= int(app_cap):
            return f"앱 하나당 동시 실행 한도({int(app_cap)}개)"
    if rate_cap and started_last_minute(db, ws.id) >= int(rate_cap):
        return f"분당 실행 한도({int(rate_cap)}개)"
    return None


def capacity_timeout_message(reason: str) -> str:
    return (
        f"{reason} 때문에 {CAPACITY_MAX_WAIT_SECONDS // 60}분 넘게 기다렸지만 시작하지 못했어요.\n"
        "잠시 후 다시 실행하거나, 관리자에게 관리 > 사용량에서 한도를 늘려 달라고 하세요."
    )


def file_storage_bytes(db: Session, workspace_id: str) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(StoredFile.size), 0)).where(
                StoredFile.workspace_id == workspace_id
            )
        )
        or 0
    )


def check_file_quota(db: Session, workspace_id: str, add_bytes: int) -> None:
    """파일을 더 저장하면 용량 한도를 넘는지. 넘으면 AppError(413)."""
    from api.core.errors import AppError

    ws = db.get(Workspace, workspace_id)
    if ws is None:
        return
    cap_mb = get_limits(ws).get("max_file_storage_mb")
    if not cap_mb:
        return
    used = file_storage_bytes(db, workspace_id)
    if used + add_bytes > int(cap_mb) * 1024 * 1024:
        raise AppError(
            413,
            f"파일 저장 용량 한도({int(cap_mb):,}MB)를 넘어 더 저장할 수 없어요"
            f"(지금 {used / 1048576:,.1f}MB).",
            "필요 없는 파일을 지우거나, 관리자에게 관리 > 사용량에서 한도를 늘려 달라고 하세요.",
        )


def capacity_usage(db: Session, ws: Workspace) -> dict[str, Any]:
    total, _ = running_counts(db, ws.id)
    return {
        "running_now": total,
        "started_last_minute": started_last_minute(db, ws.id),
        "file_storage_mb": round(file_storage_bytes(db, ws.id) / 1048576, 1),
    }


# ---------------- 알림(5분마다) ----------------
def _send_alert(db: Session, ws: Workspace, subject: str, body: str) -> bool:
    lim = get_limits(ws)
    to = lim.get("alert_emails") or []
    cred = lim.get("alert_credential_id")
    if not to or not cred:
        return False
    from api.connectors.runtime import run_connector
    from nodes import NodeError

    try:
        run_connector(
            db,
            ws.id,
            connector="email",
            credential_id=str(cred),
            action="send_email",
            params={"to": ", ".join(to), "subject": subject, "body": body},
        )
        return True
    except NodeError as exc:
        log.warning("알림 메일을 보내지 못했어요(ws=%s): %s", ws.id, exc.message)
        return False


def check_alerts(db: Session, now: datetime | None = None) -> int:
    """실패·비용 알림을 보낸다. 보낸 메일 수를 돌려준다."""
    n = now or now_utc()
    sent = 0
    for ws in db.scalars(select(Workspace)):
        lim = get_limits(ws)
        if not (lim["alert_emails"] and lim["alert_credential_id"]):
            continue
        state = dict((ws.settings or {}).get("limits_state") or {})
        since_raw = state.get("failures_checked_at")
        since = datetime.fromisoformat(since_raw) if since_raw else n - timedelta(minutes=5)
        if lim["alert_on_failure"]:
            rows = db.execute(
                select(Run, App.name)
                .join(App, App.id == Run.app_id)
                .where(
                    App.workspace_id == ws.id,
                    Run.status == "failed",
                    Run.finished_at >= since,
                    Run.finished_at < n,
                    Run.trigger.not_in(("test", "preview")),
                )
                .limit(50)
            ).all()
            if rows:
                lines = [f"- {name}: {(r.error or '')[:160]}" for r, name in rows]
                if _send_alert(db, ws, f"[Genio] 실행 실패 {len(rows)}건", "\n".join(lines)):
                    sent += 1
        state["failures_checked_at"] = n.isoformat()
        threshold = lim["cost_alert_usd"]
        month_key = n.strftime("%Y-%m")
        if threshold is not None and state.get("cost_alerted_month") != month_key:
            used = month_cost(db, ws.id, n)
            if used >= Decimal(str(threshold)):
                body = (
                    f"이번 달 AI 비용이 ${float(used):,.2f}로 알림 기준 ${float(threshold):,.2f}를 넘었어요.\n"
                    "관리 > 사용량에서 앱별·사람별 비용을 확인하세요."
                )
                if _send_alert(db, ws, "[Genio] 비용 알림", body):
                    sent += 1
                state["cost_alerted_month"] = month_key
        budget = lim["monthly_budget_usd"]
        if budget and state.get("budget_warned_month") != month_key:
            used_now = month_cost(db, ws.id, n)
            if used_now >= Decimal(str(budget)) * Decimal("0.8"):
                pct = int(used_now / Decimal(str(budget)) * 100)
                body = (
                    f"이번 달 AI 비용이 ${float(used_now):,.2f}로 월 한도 ${float(budget):,.2f}의 {pct}%예요.\n"
                    "한도를 넘으면 새 실행이 멈춰요. 관리 > 사용량에서 앱별 비용을 확인하거나 한도를 조정하세요."
                )
                if _send_alert(db, ws, "[Genio] 월 한도 80% 도달", body):
                    sent += 1
                state["budget_warned_month"] = month_key
        if lim["monthly_report"]:
            prev_start = (month_start(n) - timedelta(days=1)).replace(day=1)
            prev_key = prev_start.strftime("%Y-%m")
            if state.get("report_sent_month") != prev_key:
                subject, body = monthly_report_mail(db, ws, prev_start, month_start(n))
                if _send_alert(db, ws, subject, body):
                    sent += 1
                    state["report_sent_month"] = prev_key
        ws.settings = {**(ws.settings or {}), "limits_state": state}
    db.commit()
    return sent


def monthly_report_mail(
    db: Session, ws: Workspace, start: datetime, end: datetime
) -> tuple[str, str]:
    """지난달 효과 리포트 메일 글(추정값임을 밝힌다)"""
    from api.services import impact

    rep = impact.report(db, ws.id, start, end)
    failed = (
        db.scalar(
            select(func.count())
            .select_from(Run)
            .join(App, App.id == Run.app_id)
            .where(
                App.workspace_id == ws.id,
                Run.status == "failed",
                Run.created_at >= start,
                Run.created_at < end,
                Run.trigger.not_in(impact.NOT_COUNTED_TRIGGERS),
            )
        )
        or 0
    )
    label = f"{start.year}년 {start.month}월"
    lines = [
        f"{label} 제니오 이용 요약이에요.",
        "",
        f"- 성공한 실행: {rep['total_succeeded_runs']}건",
        f"- 실패한 실행: {int(failed)}건",
        f"- 아낀 시간(추정): 약 {rep['total_saved_hours']}시간",
    ]
    top = [r for r in rep["apps"] if r["succeeded_runs"]][:5]
    if top:
        lines += ["", "많이 쓴 앱"]
        lines += [
            f"- {r['app_name']}: {r['succeeded_runs']}건"
            + (f" (약 {round(r['saved_minutes'] / 60, 1)}시간 절약)" if r["saved_minutes"] else "")
            for r in top
        ]
    if rep["unset_apps"]:
        lines += [
            "",
            f"※ {rep['unset_apps']}개 앱은 '한 번에 아끼는 시간'이 비어 있어 시간에 넣지 못했어요.",
        ]
    lines += ["", "아낀 시간은 앱마다 정해 둔 '한 번에 아끼는 시간'으로 계산한 추정값이에요."]
    return f"[Genio] {label} 이용 요약", "\n".join(lines)


# ---------------- 보관 기간(매일) ----------------
def apply_retention(db: Session, now: datetime | None = None) -> dict[str, int]:
    """보관 기간이 지난 실행 기록(끝난 것만)·대화 메시지·받은 값을 지운다."""
    n = now or now_utc()
    removed = {"runs": 0, "messages": 0, "conversations": 0, "errors": 0}
    for ws in db.scalars(select(Workspace)):
        days = get_limits(ws).get("retention_days")
        if not days:
            continue
        cutoff = n - timedelta(days=int(days))
        app_ids = list(db.scalars(select(App.id).where(App.workspace_id == ws.id)))
        if not app_ids:
            continue
        r = db.execute(
            delete(Run).where(
                Run.app_id.in_(app_ids), Run.created_at < cutoff, Run.status.in_(TERMINAL)
            )
        )
        removed["runs"] += int(getattr(r, "rowcount", 0) or 0)
        conv_ids = list(db.scalars(select(Conversation.id).where(Conversation.app_id.in_(app_ids))))
        if conv_ids:
            m = db.execute(
                delete(Message).where(
                    Message.conversation_id.in_(conv_ids), Message.created_at < cutoff
                )
            )
            removed["messages"] += int(getattr(m, "rowcount", 0) or 0)
            empty = list(
                db.scalars(
                    select(Conversation.id)
                    .outerjoin(Message, Message.conversation_id == Conversation.id)
                    .where(Conversation.id.in_(conv_ids), Conversation.created_at < cutoff)
                    .group_by(Conversation.id)
                    .having(func.count(Message.id) == 0)
                )
            )
            if empty:
                c = db.execute(delete(Conversation).where(Conversation.id.in_(empty)))
                removed["conversations"] += int(getattr(c, "rowcount", 0) or 0)
        for t in db.scalars(select(AppTrigger).where(AppTrigger.app_id.in_(app_ids))):
            keep = [
                p
                for p in (t.last_payloads or [])
                if str(p.get("received_at", "")) >= cutoff.isoformat()
            ]
            if len(keep) != len(t.last_payloads or []):
                t.last_payloads = keep
    # 서버 오류 기록은 워크스페이스와 무관하게 30일 보관
    from api.services.error_log import purge_old

    removed["errors"] = purge_old(db, n)
    db.commit()
    return removed
