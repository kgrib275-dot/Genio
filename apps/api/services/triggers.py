"""자동 실행(ADR 0008): 웹훅·예약. 웹훅 토큰은 비밀값처럼 다룬다(로그·오류에 남기지 않음)."""

import logging
import secrets
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadCronError, CroniterBadDateError, croniter
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.errors import AppError
from api.models import App, AppTrigger, Run, WorkflowVersion

log = logging.getLogger("genio.triggers")

DEFAULT_TZ = "Asia/Seoul"
KINDS = ("webhook", "schedule")
MIN_INTERVAL_SECONDS = 60
MAX_INPUT_BYTES = 64 * 1024


def now_utc() -> datetime:
    return datetime.now(UTC)


def new_token() -> str:
    return secrets.token_urlsafe(24)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def trigger_dict(t: AppTrigger, origin: str | None) -> dict[str, Any]:
    """origin이 None이면(보기 권한만 있는 사람) 웹훅 주소를 숨긴다."""
    url = None
    if t.kind == "webhook" and t.token and origin is not None:
        url = f"{origin.rstrip('/')}/api/v1/hooks/{t.token}"
    return {
        "id": t.id,
        "app_id": t.app_id,
        "kind": t.kind,
        "name": t.name,
        "enabled": t.enabled,
        "config": t.config or {},
        "url": url,
        "next_run_at": _aware(t.next_run_at),
        "last_run_at": _aware(t.last_run_at),
        "last_run_id": t.last_run_id,
        "last_status": t.last_status,
        "created_at": _aware(t.created_at),
    }


# ---------------- 예약(cron) ----------------
def _zone(name: Any) -> ZoneInfo:
    try:
        return ZoneInfo(str(name or DEFAULT_TZ))
    except (ZoneInfoNotFoundError, ValueError):
        raise AppError(
            422,
            f"시간대 '{str(name)[:40]}'를 알 수 없어요.",
            "Asia/Seoul 같은 시간대 이름을 쓰세요.",
        ) from None


def next_fire(cron: str, tz_name: str, after: datetime) -> datetime:
    """after 다음 실행 시각(UTC)."""
    tz = _zone(tz_name)
    base = (_aware(after) or now_utc()).astimezone(tz)
    nxt = croniter(cron, base).get_next(datetime)
    return nxt.astimezone(UTC)


def _bad_cron() -> AppError:
    return AppError(
        422,
        "예약 시간(cron)을 읽지 못했어요.",
        "'분 시 일 월 요일' 다섯 칸으로 적어 주세요. 예: 매일 오전 9시 = 0 9 * * *",
    )


def clean_schedule(config: dict[str, Any]) -> dict[str, Any]:
    cron = " ".join(str(config.get("cron") or "").split())
    if len(cron.split(" ")) != 5:
        raise _bad_cron()
    try:
        if not croniter.is_valid(cron):
            raise _bad_cron()
        tz_name = str(config.get("timezone") or DEFAULT_TZ)
        tz = _zone(tz_name)
        it = croniter(cron, datetime.now(tz))
        first = it.get_next(datetime)
        second = it.get_next(datetime)
    except (CroniterBadCronError, CroniterBadDateError, ValueError, KeyError):
        raise _bad_cron() from None
    if (second - first).total_seconds() < MIN_INTERVAL_SECONDS:
        raise AppError(
            422, "예약은 1분보다 자주 실행할 수 없어요.", "간격을 1분 이상으로 늘려 주세요."
        )
    inp = config.get("input") or {}
    if not isinstance(inp, dict):
        raise AppError(
            422, "예약 실행 입력은 '이름: 값' 묶음이어야 해요.", '예: {"message": "오늘 요약"}'
        )
    out: dict[str, Any] = {"cron": cron, "timezone": tz_name, "input": inp}
    if config.get("version") is not None:
        out["version"] = _version_number(config["version"])
    return out


def clean_webhook(config: dict[str, Any]) -> dict[str, Any]:
    mode = str(config.get("mode") or "async")
    if mode not in ("async", "sync"):
        raise AppError(
            422,
            "웹훅 응답 방식을 알 수 없어요.",
            "바로 응답(async) 또는 결과까지 기다림(sync)을 고르세요.",
        )
    out: dict[str, Any] = {"mode": mode}
    if config.get("version") is not None:
        out["version"] = _version_number(config["version"])
    return out


def _version_number(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise AppError(
            422, "버전 번호는 숫자여야 해요.", "비우면 저장한 최신 버전으로 실행해요."
        ) from None
    if n < 1:
        raise AppError(422, "버전 번호는 1 이상이에요.", "비우면 저장한 최신 버전으로 실행해요.")
    return n


def clean_config(kind: str, config: dict[str, Any] | None) -> dict[str, Any]:
    if kind == "schedule":
        return clean_schedule(config or {})
    return clean_webhook(config or {})


def refresh_next_run(t: AppTrigger, after: datetime | None = None) -> None:
    if t.kind == "schedule" and t.enabled:
        cfg = t.config or {}
        t.next_run_at = next_fire(
            str(cfg["cron"]), str(cfg.get("timezone") or DEFAULT_TZ), after or now_utc()
        )
    else:
        t.next_run_at = None


# ---------------- 실행 만들기 ----------------
def resolve_version(db: Session, app_id: str, version: Any) -> WorkflowVersion:
    q = select(WorkflowVersion).where(WorkflowVersion.app_id == app_id)
    if version is not None:
        v = db.scalar(q.where(WorkflowVersion.version == int(version)))
        if v is None:
            raise AppError(
                409,
                f"자동 실행에 정한 버전 {version}이(가) 없어요.",
                "자동 실행 설정에서 버전을 비우거나 있는 버전을 고르세요.",
            )
        return v
    v = db.scalar(q.order_by(WorkflowVersion.version.desc()).limit(1))
    if v is None:
        raise AppError(
            409,
            "저장한 버전이 없어 자동으로 실행할 수 없어요.",
            "빌더에서 '버전 저장'을 한 번 한 뒤 다시 시도하세요.",
        )
    return v


def create_trigger_run(
    db: Session, t: AppTrigger, run_input: dict[str, Any], *, created_by: str | None = None
) -> Run:
    """트리거로 실행을 만들고 기록을 남긴다(큐에 넣는 것은 부른 쪽)."""
    version = resolve_version(db, t.app_id, (t.config or {}).get("version"))
    clean = {k: v for k, v in run_input.items() if not str(k).startswith("__")}
    run = Run(
        app_id=t.app_id,
        version_id=version.id,
        trigger=t.kind,
        input=clean,
        created_by=created_by,
    )
    db.add(run)
    db.flush()
    t.last_run_at = now_utc()
    t.last_run_id = run.id
    t.last_status = "queued"
    db.commit()
    return run


def dispatch_schedules(db: Session, now: datetime | None = None) -> list[str]:
    """next_run_at이 지난 예약을 실행한다. 워커 beat가 1분마다 부른다. 만든 run id 목록."""
    from api.services.queue import enqueue_run

    current = now or now_utc()
    due = list(
        db.scalars(
            select(AppTrigger)
            .where(
                AppTrigger.kind == "schedule",
                AppTrigger.enabled.is_(True),
                AppTrigger.next_run_at.is_not(None),
                AppTrigger.next_run_at <= current,
            )
            .order_by(AppTrigger.next_run_at)
            .limit(200)
        )
    )
    started: list[str] = []
    for t in due:
        cfg = t.config or {}
        try:
            # 밀린 예약은 한 번만 실행하고 다음 시각부터 이어 간다
            t.next_run_at = next_fire(
                str(cfg.get("cron")), str(cfg.get("timezone") or DEFAULT_TZ), current
            )
        except AppError:
            t.enabled = False
            t.next_run_at = None
            t.last_status = "invalid"
            db.commit()
            continue
        app = db.get(App, t.app_id)
        if app is None:
            continue
        try:
            run = create_trigger_run(db, t, dict(cfg.get("input") or {}))
        except AppError as exc:
            t.last_run_at = current
            t.last_status = "no_version"
            db.commit()
            log.info("예약 실행 건너뜀(trigger=%s): %s", t.id, exc.message)
            continue
        started.append(run.id)
    for run_id in started:
        enqueue_run(run_id)
    return started


def sync_last_status(db: Session, run: Run) -> None:
    """실행이 끝나면 그 실행을 만든 트리거의 마지막 상태를 맞춘다."""
    if run.trigger not in KINDS:
        return
    t = db.scalar(select(AppTrigger).where(AppTrigger.last_run_id == run.id))
    if t is not None:
        t.last_status = run.status
