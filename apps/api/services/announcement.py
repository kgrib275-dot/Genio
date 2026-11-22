"""서비스 공지: 인스턴스 관리자가 올리면 모든 화면 위쪽에 띄우고 상태 페이지에도 보인다."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from api.core.errors import AppError
from api.models import SystemSetting

KEY = "announcement"
LEVELS = ("info", "warn", "maintenance")
MAX_MESSAGE = 300


def _parse(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        raise AppError(
            422, "끝나는 시각 형식이 올바르지 않아요.", "날짜와 시간을 다시 골라 주세요."
        ) from None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def get(db: Session, now: datetime | None = None) -> dict[str, Any]:
    """지금 보여 줄 공지(없거나 기간이 끝났으면 active=False)."""
    row = db.get(SystemSetting, KEY)
    raw = dict(row.value) if row and isinstance(row.value, dict) else {}
    until = _parse(raw.get("until"))
    n = now or datetime.now(UTC)
    active = bool(raw.get("message")) and (until is None or until > n)
    return {
        "active": active,
        "message": str(raw.get("message") or "") if active else "",
        "level": str(raw.get("level") or "info") if active else "info",
        "until": raw.get("until") if active else None,
    }


def save(db: Session, message: str, level: str, until: str | None) -> dict[str, Any]:
    message = message.strip()[:MAX_MESSAGE]
    if level not in LEVELS:
        raise AppError(422, "공지 종류가 올바르지 않아요.", "안내·주의·점검 중 하나를 고르세요.")
    _parse(until)  # 형식 검사
    value = {"message": message, "level": level, "until": until or None}
    row = db.get(SystemSetting, KEY)
    if not message:  # 비우면 공지를 내린다
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(SystemSetting(key=KEY, value=value))
    else:
        row.value = value
    db.commit()
    return get(db)
