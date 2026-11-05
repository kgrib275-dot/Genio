"""서버 오류 기록(운영 준비): 처리되지 않은 API 오류와 실행 엔진 내부 오류를 error_events에 남긴다.

- 요청 본문·헤더는 남기지 않는다. 메시지에서는 토큰·키·비밀번호처럼 보이는 값을 가린다.
- 기록 실패가 원래 요청·실행을 깨면 안 되므로 모든 예외를 삼킨다(로그만 남김).
- 30일이 지나면 보관 기간 정리(services/limits.apply_retention)에서 지운다.
"""

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.models import ErrorEvent

log = logging.getLogger("genio.errors")
KEEP_DAYS = 30
MAX_MESSAGE = 500

_SECRET_PATTERNS = [
    # Authorization: Bearer xxx / Basic xxx
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 ****"),
    # key=value 꼴의 비밀(쿼리·설정)
    (
        re.compile(
            r"(?i)\b(api[_-]?key|apikey|token|secret|password|passwd|pwd|authorization|x-api-key)"
            r"(\s*[=:]\s*)(\"?)[^\s\"'&,;]{4,}"
        ),
        r"\1\2\3****",
    ),
    # 잘 알려진 키 모양(sk-, xoxb-, ghp_, AIza…)
    (re.compile(r"\b(sk|rk|pk)-[A-Za-z0-9_-]{8,}"), "****"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{8,}"), "****"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{12,}"), "****"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), "****"),
    # 연결 문자열 안의 비밀번호(postgresql://user:pw@host)
    (re.compile(r"(://[^:/\s@]+:)[^@\s]+@"), r"\1****@"),
    # JWT
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "****"),
]


def redact(text: str) -> str:
    """비밀처럼 보이는 값만 가린다(길이·공백은 그대로). Sentry 같은 외부 전송 전 정리에도 쓴다."""
    out = str(text or "")
    for pat, repl in _SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


def scrub(text: str) -> str:
    """비밀처럼 보이는 값을 가리고 길이를 줄인다."""
    out = " ".join(redact(text).split())
    return out[:MAX_MESSAGE]


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


_RID = re.compile(r"^[A-Za-z0-9._-]{6,64}$")


def clean_request_id(value: str | None) -> str:
    """앞단(프록시)이 준 X-Request-ID는 안전한 글자일 때만 그대로 쓴다."""
    if value and _RID.match(value):
        return value
    return new_request_id()


def record(
    *,
    source: str,
    where: str,
    exc: BaseException | None = None,
    error_type: str = "",
    message: str = "",
    request_id: str | None = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> None:
    """오류 한 건을 남긴다. 실패해도 조용히 넘어간다."""
    try:
        from api.db import SessionLocal

        etype = error_type or (type(exc).__name__ if exc is not None else "")
        msg = message or (str(exc) if exc is not None else "")
        with SessionLocal() as db:
            db.add(
                ErrorEvent(
                    source=source[:20],
                    where=scrub(where)[:300],
                    error_type=etype[:120],
                    message=scrub(msg),
                    request_id=(request_id or None),
                    user_id=(user_id or None),
                    workspace_id=(workspace_id or None),
                )
            )
            db.commit()
    except Exception:
        log.warning("오류 기록을 남기지 못함(source=%s)", source)


def recent(db: Session, limit: int = 500) -> list[dict[str, Any]]:
    rows = db.scalars(select(ErrorEvent).order_by(ErrorEvent.created_at.desc()).limit(limit))
    return [
        {
            "id": e.id,
            "created_at": e.created_at,
            "source": e.source,
            "where": e.where,
            "error_type": e.error_type,
            "message": e.message,
            "request_id": e.request_id,
            "user_id": e.user_id,
            "workspace_id": e.workspace_id,
        }
        for e in rows
    ]


def purge_old(db: Session, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=KEEP_DAYS)
    r = db.execute(delete(ErrorEvent).where(ErrorEvent.created_at < cutoff))
    return int(getattr(r, "rowcount", 0) or 0)
