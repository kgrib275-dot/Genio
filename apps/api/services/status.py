"""운영 준비: 시스템 상태(인스턴스 관리자 전용). 각 항목은 따로 확인하고, 하나가 실패해도 나머지는 보여 준다.

상태 값: ok(정상) | warn(주의) | error(문제) | unknown(확인 불가)
"""

import json
import os
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from api.config import get_settings
from api.models import ErrorEvent, Run, User, Workspace

# 백업이 이보다 오래되면 '주의'
BACKUP_STALE_HOURS = 30


def _item(status: str, label: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"status": status, "label": label, "detail": detail, **extra}


def _db(db: Session) -> dict[str, Any]:
    t = time.perf_counter()
    try:
        db.execute(text("select 1"))
    except Exception:
        return _item("error", "DB", "DB에 연결하지 못했어요.")
    ms = round((time.perf_counter() - t) * 1000, 1)
    return _item("ok" if ms < 200 else "warn", "DB", f"응답 {ms}ms", ms=ms)


def _redis() -> tuple[dict[str, Any], Any]:
    url = get_settings().redis_url
    if not url:
        return _item("unknown", "Redis", "설정되지 않았어요(시험·로컬 환경)."), None
    try:
        import redis

        r = redis.Redis.from_url(url, socket_timeout=1.5, socket_connect_timeout=1.5)
        t = time.perf_counter()
        r.ping()
        ms = round((time.perf_counter() - t) * 1000, 1)
        return _item("ok", "Redis", f"응답 {ms}ms", ms=ms), r
    except Exception:
        return _item("error", "Redis", "Redis에 연결하지 못했어요."), None


def _worker() -> dict[str, Any]:
    st = get_settings()
    if st.genio_run_inline:
        return _item("unknown", "실행 워커", "바로 실행 모드라 워커를 쓰지 않아요.")
    try:
        from api.services.queue import _client

        replies = _client().control.ping(timeout=1.5) or []
    except Exception:
        return _item("error", "실행 워커", "워커 상태를 묻지 못했어요(큐 연결 확인).")
    if not replies:
        return _item("error", "실행 워커", "응답하는 워커가 없어요. 흐름 실행·예약이 멈춰 있어요.")
    return _item("ok", "실행 워커", f"워커 {len(replies)}개 응답", workers=len(replies))


def _sandbox() -> dict[str, Any]:
    """코드 단계를 격리 서버에서 돌리는지, 응답은 하는지."""
    from api.engine import sandbox_client

    if not sandbox_client.enabled():
        return _item(
            "unknown",
            "코드 실행",
            "서버 안에서 실행해요(격리 서버를 쓰지 않음). 여러 사람이 쓰면 격리 서버를 켜는 것을 권해요.",
            mode="in-process",
        )
    ok, ms = sandbox_client.health()
    if not ok:
        return _item(
            "error",
            "코드 실행",
            "코드 실행 서버가 응답하지 않아요. 코드 단계가 실패하고 있어요.",
            mode="sandbox",
        )
    return _item(
        "ok" if ms < 500 else "warn", "코드 실행", f"격리 서버 응답 {ms}ms", mode="sandbox", ms=ms
    )


def _secret_key() -> dict[str, Any]:
    from api.config import secret_key_problem

    problem = secret_key_problem(get_settings())
    if problem:
        return _item("warn", "비밀 키", f"{problem}. .env에서 긴 무작위 값으로 바꿔 주세요.")
    return _item("ok", "비밀 키", "직접 정한 값을 쓰고 있어요.")


def _ratelimit(redis_ok: bool) -> dict[str, Any]:
    """속도 제한·로그인 시도 제한을 API 프로세스들이 함께 세는지(Redis) 따로 세는지(메모리)."""
    from api.core import ratelimit

    st = ratelimit.backend_state()
    if not st["configured"]:
        return _item(
            "unknown",
            "속도 제한",
            "프로세스마다 따로 세요(Redis 설정 없음, 시험·로컬 환경).",
            mode="memory",
        )
    if not redis_ok or st["degraded"]:
        return _item(
            "warn",
            "속도 제한",
            "Redis에 연결하지 못해 프로세스마다 따로 세고 있어요. 한도가 느슨해져요.",
            mode="memory",
        )
    return _item("ok", "속도 제한", "모든 API 프로세스가 Redis로 함께 세요.", mode="redis")


# 예약 실행(beat)이 마지막으로 돈 시각. worker/singleton.py의 last_run_key("dispatch_schedules")와 같은 키
BEAT_LAST_KEY = "genio:beat:last:dispatch_schedules"
BEAT_STALE_SECONDS = 300


def _scheduler(r: Any) -> dict[str, Any]:
    """scheduler 서비스(celery beat)가 1분마다 예약 실행을 확인하고 있는지."""
    st = get_settings()
    if st.genio_run_inline or r is None:
        return _item("unknown", "예약 실행", "확인할 수 없어요.")
    try:
        raw = r.get(BEAT_LAST_KEY)
    except Exception:
        return _item("unknown", "예약 실행", "확인할 수 없어요.")
    if not raw:
        return _item(
            "warn",
            "예약 실행",
            "예약 확인 기록이 없어요. scheduler 서비스가 떠 있는지 확인해 주세요.",
        )
    ago = int(time.time() - int(raw))
    if ago > BEAT_STALE_SECONDS:
        return _item(
            "error",
            "예약 실행",
            f"{ago // 60}분째 예약을 확인하지 않았어요. scheduler 서비스를 다시 시작해 주세요.",
            seconds_ago=ago,
        )
    return _item("ok", "예약 실행", f"{ago}초 전에 확인함", seconds_ago=ago)


def _queue() -> dict[str, Any]:
    st = get_settings()
    url = st.celery_broker_url or st.redis_url
    if st.genio_run_inline or not url.startswith("redis"):
        return _item("unknown", "대기 중인 작업", "확인할 수 없어요.")
    try:
        import redis

        r = redis.Redis.from_url(url, socket_timeout=1.5, socket_connect_timeout=1.5)
        n = int(r.llen("celery"))
    except Exception:
        return _item("unknown", "대기 중인 작업", "확인할 수 없어요.")
    status = "ok" if n < 100 else "warn" if n < 1000 else "error"
    return _item(status, "대기 중인 작업", f"{n}개", count=n)


def _backup(now: datetime) -> dict[str, Any]:
    path = Path(get_settings().genio_backup_dir) / "status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _item(
            "unknown",
            "자동 백업",
            "백업 기록을 찾지 못했어요(백업 서비스가 꺼져 있거나 아직 한 번도 돌지 않음).",
        )
    except Exception:
        return _item("unknown", "자동 백업", "백업 기록을 읽지 못했어요.")
    last_ok = str(data.get("last_success") or "")
    ok = data.get("status") == "ok"
    detail = f"마지막 성공 {last_ok or '없음'}"
    if data.get("file"):
        detail += f" · {data.get('file')} ({data.get('size_mb', '?')}MB)"
    status = "ok" if ok else "error"
    try:
        when = datetime.fromisoformat(last_ok.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if now - when > timedelta(hours=BACKUP_STALE_HOURS):
            status = "warn" if ok else "error"
            detail += " · 하루 넘게 새 백업이 없어요"
    except ValueError:
        if ok:
            status = "warn"
    if not ok and data.get("message"):
        detail += f" · {str(data.get('message'))[:200]}"
    return _item(
        status, "자동 백업", detail, last_success=last_ok or None, keep_days=data.get("keep_days")
    )


# 복구 연습이 이보다 오래되면 '주의'(매주 돌므로 여유를 둔다)
VERIFY_STALE_DAYS = 8


def _offsite() -> dict[str, Any]:
    """운영 준비 1차(A3): 바깥 저장소 백업."""
    from api.services import offsite_backup

    if not offsite_backup.enabled():
        return _item(
            "warn",
            "외부 백업",
            "백업이 이 PC에만 있어요. PC가 망가지면 함께 사라져요. "
            "GENIO_BACKUP_S3_BUCKET으로 바깥 저장소를 정해 주세요.",
            mode="off",
        )
    st = offsite_backup.load_state()
    if not st:
        return _item("unknown", "외부 백업", "아직 한 번도 올리지 않았어요(한 시간 안에 올려요).")
    if st.get("status") != "ok":
        return _item("error", "외부 백업", str(st.get("message") or "올리지 못했어요."))
    detail = f"마지막 확인 {st.get('last_success') or '없음'}"
    if st.get("last_file"):
        detail += f" · {st.get('last_file')}"
    return _item("ok", "외부 백업", detail, last_success=st.get("last_success"))


def _verify(now: datetime) -> dict[str, Any]:
    """운영 준비 1차(A3): 복구 연습(scripts/verify_backup.sh) 결과."""
    path = Path(get_settings().genio_backup_dir) / "verify.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _item(
            "unknown",
            "복구 연습",
            "아직 복구 연습을 하지 않았어요. 매주 일요일 백업 뒤에 자동으로 해요.",
        )
    except Exception:
        return _item("unknown", "복구 연습", "복구 연습 기록을 읽지 못했어요.")
    when_raw = str(data.get("checked_at") or "")
    if data.get("status") != "ok":
        return _item(
            "error",
            "복구 연습",
            f"{when_raw} 복구에 실패했어요. {data.get('message') or ''}".strip(),
        )
    detail = (
        f"{when_raw} {data.get('file', '')} 복구 성공 · 표 {data.get('tables', '?')}개 · "
        f"{data.get('seconds', '?')}초"
    )
    status = "ok"
    try:
        when = datetime.fromisoformat(when_raw.replace("Z", "+00:00"))
        if now - when > timedelta(days=VERIFY_STALE_DAYS):
            status = "warn"
            detail += " · 일주일 넘게 연습하지 않았어요"
    except ValueError:
        status = "warn"
    return _item(status, "복구 연습", detail, rows=data.get("rows") or {})


def _disk() -> dict[str, Any]:
    target = get_settings().genio_backup_dir
    path = target if os.path.isdir(target) else "/"
    try:
        u = shutil.disk_usage(path)
    except Exception:
        return _item("unknown", "디스크", "확인할 수 없어요.")
    free_gb = round(u.free / 1024**3, 1)
    pct = round(u.free / u.total * 100) if u.total else 0
    status = "ok" if pct >= 15 else "warn" if pct >= 5 else "error"
    return _item(
        status, "디스크 남은 공간", f"{free_gb}GB 남음({pct}%)", free_gb=free_gb, free_pct=pct
    )


def system_status(db: Session) -> dict[str, Any]:
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)
    redis_item, r = _redis()
    items = [
        _db(db),
        redis_item,
        _ratelimit(redis_item["status"] == "ok"),
        _worker(),
        _scheduler(r),
        _queue(),
        _sandbox(),
        _backup(now),
        _offsite(),
        _verify(now),
        _disk(),
        _secret_key(),
    ]
    runs_24h = db.scalar(select(func.count()).select_from(Run).where(Run.created_at >= since)) or 0
    failed_24h = (
        db.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.created_at >= since, Run.status == "failed")
        )
        or 0
    )
    errors_24h = (
        db.scalar(
            select(func.count()).select_from(ErrorEvent).where(ErrorEvent.created_at >= since)
        )
        or 0
    )
    counts = {
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
        "workspaces": db.scalar(select(func.count()).select_from(Workspace)) or 0,
        "runs_24h": runs_24h,
        "failed_runs_24h": failed_24h,
        "server_errors_24h": errors_24h,
    }
    worst = "ok"
    for it in items:
        if it["status"] == "error":
            worst = "error"
        elif it["status"] == "warn" and worst != "error":
            worst = "warn"
    version = get_settings().genio_version
    return {
        "checked_at": now.isoformat(),
        "overall": worst,
        "version": "개발" if version in ("", "dev") else version,
        "env": get_settings().genio_env,
        "items": items,
        "counts": counts,
    }
