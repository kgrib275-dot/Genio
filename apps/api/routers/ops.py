"""운영 준비: 시스템 상태·서버 오류 기록(인스턴스 관리자), 활동 기록 CSV 내보내기(소유자·관리자)."""

import csv
import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from api.core.errors import AppError
from api.deps import MANAGE_MEMBERS, Ctx, CurrentUser, DbDep, require_role
from api.models import AuditLog, User
from api.services import error_log, system
from api.services.error_log import scrub
from api.services.status import system_status

router = APIRouter(tags=["ops"])
Managers = Annotated[Ctx, Depends(require_role(MANAGE_MEMBERS))]

EXPORT_MAX_ROWS = 50_000
# 활동 기록의 부가 정보 중 비밀처럼 보이는 키는 내보내지 않는다
_SECRET_KEYS = ("key", "token", "secret", "password", "credential")


def _instance_admin(db: DbDep, user: CurrentUser) -> None:
    if not system.is_instance_admin(db, user.id):
        raise AppError(
            403,
            "이 화면은 인스턴스 관리자만 볼 수 있어요.",
            "가장 먼저 만든 워크스페이스의 소유자에게 요청하세요.",
        )


@router.get("/admin/status")
def get_status(user: CurrentUser, db: DbDep) -> dict[str, Any]:
    _instance_admin(db, user)
    return system_status(db)


@router.get("/admin/errors")
def list_errors(
    user: CurrentUser, db: DbDep, limit: int = Query(default=500, ge=1, le=2000)
) -> list[dict[str, Any]]:
    _instance_admin(db, user)
    return error_log.recent(db, limit)


def _csv_safe(value: str) -> str:
    """엑셀에서 =,+,-,@로 시작하는 칸을 수식으로 실행하지 않게 앞에 '를 붙인다."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", chr(9), chr(13)) else value


def _clean_meta(meta: Any) -> str:
    if not isinstance(meta, dict):
        return ""
    safe = {
        k: ("****" if any(s in str(k).lower() for s in _SECRET_KEYS) else v)
        for k, v in meta.items()
    }
    return scrub(json.dumps(safe, ensure_ascii=False, default=str))


@router.get("/workspaces/{ws}/audit-logs/export")
def export_audit(
    ws: str,
    ctx: Managers,
    area: str = Query(default="", max_length=60),
    action: str = Query(default="", max_length=100),
    user: str = Query(default="", max_length=320),
    days: int = Query(default=0, ge=0, le=3650),
    q: str = Query(default="", max_length=200),
) -> StreamingResponse:
    """활동 기록을 CSV로(화면의 필터 그대로, 최대 5만 줄). 엑셀에서 한글이 깨지지 않게 BOM을 붙인다."""
    stmt = (
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.workspace_id == ws)
    )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    elif area:
        stmt = stmt.where(AuditLog.action.like(f"{area}.%"))
    if user == "(시스템)":
        stmt = stmt.where(AuditLog.user_id.is_(None))
    elif user:
        stmt = stmt.where(User.email == user)
    if days:
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=days - 1
        )
        stmt = stmt.where(AuditLog.created_at >= start)
    rows = ctx.db.execute(stmt.order_by(AuditLog.created_at.desc()).limit(EXPORT_MAX_ROWS)).all()
    needle = q.strip().lower()

    def gen() -> Iterator[str]:
        buf = io.StringIO()
        w = csv.writer(buf)
        buf.write("﻿")
        w.writerow(["때(UTC)", "누가", "한 일", "대상 종류", "대상 id", "내용"])
        for a, email in rows:
            meta = _clean_meta(a.meta)
            line = [
                a.created_at.isoformat() if a.created_at else "",
                email or "(시스템)",
                a.action,
                a.target_type,
                a.target_id or "",
                meta,
            ]
            if needle and needle not in " ".join(line).lower():
                continue
            w.writerow([_csv_safe(c) for c in line])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
        rest = buf.getvalue()
        if rest:
            yield rest

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        gen(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="audit-{stamp}.csv"'},
    )
