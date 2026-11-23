"""서비스 이상 알림: 시스템 상태 점검(services/status.py)에서 '오류'가 난 항목을 서비스 관리자에게 알린다.

- 5분마다 점검해서 새로 나빠진 항목은 바로, 계속 나쁜 항목은 6시간마다 다시 알리고, 좋아지면 '복구됨'을 알린다.
- 받는 곳: 서비스 관리자(첫 워크스페이스의 소유자) 메일, 그리고 GENIO_ALERT_WEBHOOK_URL(슬랙·팀즈 등 {"text": ...} 형식).
- 알림은 Redis에 마지막 상태를 남겨 중복을 막는다. Redis가 없으면 이 프로세스 메모리에 남긴다.
- 주의: 점검 자체가 scheduler(beat)가 보내는 작업이라, scheduler가 멈추면 이 알림도 멈춘다. 바깥에서 /api/v1/public-status를
  보는 감시(업타임 서비스)를 함께 두는 것을 권한다(docs/runbook.md).
"""

import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.engine import safe_http
from api.models import Membership, User
from api.services import mailer, status, system
from nodes import NodeError

log = logging.getLogger("genio.health_alert")

STATE_KEY = "genio:alert:state"
REPEAT_SECONDS = 6 * 3600
# 오류가 아니어도 '주의' 단계에서 알릴 항목(백업은 조용히 멈추기 쉽다)
WARN_LABEL_HINTS = ("백업", "복구 연습")
_memory: dict[str, float] = {}


def problems(report: dict[str, Any]) -> dict[str, str]:
    """{항목 이름: 설명}. 오류 항목과, 백업 관련 주의 항목."""
    out: dict[str, str] = {}
    for it in report.get("items", []):
        label = str(it.get("label") or "")
        st = it.get("status")
        if st == "error" or (st == "warn" and any(h in label for h in WARN_LABEL_HINTS)):
            out[label] = str(it.get("detail") or "")
    return out


def _redis() -> Any:
    url = get_settings().redis_url
    if not url:
        return None
    try:
        import redis

        return redis.Redis.from_url(url, socket_timeout=1.5, socket_connect_timeout=1.5)
    except Exception:
        return None


def _load(r: Any) -> dict[str, float]:
    if r is not None:
        try:
            raw = r.hgetall(STATE_KEY)
            return {k.decode(): float(v) for k, v in raw.items()}
        except Exception as exc:
            log.warning("이상 알림 상태를 읽지 못했어요: %s", type(exc).__name__)
    return dict(_memory)


def _save(r: Any, state: dict[str, float]) -> None:
    _memory.clear()
    _memory.update(state)
    if r is None:
        return
    try:
        pipe = r.pipeline()
        pipe.delete(STATE_KEY)
        if state:
            pipe.hset(STATE_KEY, mapping={k: str(v) for k, v in state.items()})
        pipe.execute()
    except Exception as exc:
        log.warning("이상 알림 상태를 저장하지 못했어요: %s", type(exc).__name__)


def recipients(db: Session) -> list[str]:
    ws = system.instance_workspace_id(db)
    if ws is None:
        return []
    rows = db.scalars(
        select(User.email)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == ws, Membership.role == "owner")
    )
    return [e for e in rows if e]


def _deliver(db: Session, subject: str, body: str) -> list[str]:
    """메일·웹훅으로 보내고 보낸 방법 이름을 돌려준다(주소·주소 값은 기록하지 않는다)."""
    sent: list[str] = []
    for to in recipients(db):
        try:
            mailer.send(db, to, subject, body)
            sent.append("mail")
        except Exception as exc:
            log.warning("이상 알림 메일을 보내지 못했어요: %s", type(exc).__name__)
    url = get_settings().genio_alert_webhook_url.strip()
    if url:
        try:
            safe_http.request("POST", url, body={"text": f"{subject}\n{body}"})
            sent.append("webhook")
        except (NodeError, Exception) as exc:
            log.warning("이상 알림 웹훅을 보내지 못했어요: %s", type(exc).__name__)
    return sent


def _web_hint() -> str:
    base = get_settings().genio_public_web_url.rstrip("/")
    return f"\n\n자세히 보기: {base}/admin?tab=system" if base else ""


def check(db: Session, *, now: float | None = None) -> dict[str, Any]:
    """점검하고 필요하면 알린다. {problems, alerted, recovered}를 돌려준다."""
    now = time.time() if now is None else now
    report = status.system_status(db)
    current = problems(report)
    r = _redis()
    state = _load(r)
    alerted: list[str] = []
    recovered: list[str] = []
    new_state: dict[str, float] = {}
    for label in current:
        last = state.get(label)
        if last is None or now - last >= REPEAT_SECONDS:
            alerted.append(label)
            new_state[label] = now
        else:
            new_state[label] = last
    recovered = [label for label in state if label not in current]
    if alerted:
        lines = "\n".join(f"- {label}: {current[label]}" for label in alerted)
        _deliver(
            db,
            f"[제니오] 서비스 이상 {len(alerted)}건",
            f"다음 항목에 문제가 있어요.\n{lines}{_web_hint()}",
        )
    if recovered:
        _deliver(
            db, "[제니오] 서비스 복구됨", "다음 항목이 다시 정상이에요: " + ", ".join(recovered)
        )
    _save(r, new_state)
    return {"problems": sorted(current), "alerted": alerted, "recovered": recovered}
