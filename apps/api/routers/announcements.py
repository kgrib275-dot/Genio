"""서비스 공지와 공개 상태 페이지(로그인 없이 볼 수 있는 부분은 아주 좁게만 보여 준다)."""

import time
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.core.audit import audit
from api.core.errors import AppError
from api.deps import CurrentUser, DbDep
from api.services import announcement, system
from api.services.status import system_status

router = APIRouter(tags=["ops"])
_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
CACHE_SECONDS = 15


@router.get("/announcement")
def current_announcement(db: DbDep) -> dict[str, Any]:
    """로그인 없이: 지금 올라와 있는 공지(없으면 active=false)."""
    return announcement.get(db)


class AnnouncementIn(BaseModel):
    message: str = Field(default="", max_length=announcement.MAX_MESSAGE)
    level: Literal["info", "warn", "maintenance"] = "info"
    until: str | None = Field(default=None, max_length=40)


@router.put("/admin/announcement")
def put_announcement(body: AnnouncementIn, user: CurrentUser, db: DbDep) -> dict[str, Any]:
    if not system.is_instance_admin(db, user.id):
        raise AppError(
            403,
            "공지는 서비스 전체 관리자만 올릴 수 있어요.",
            "가장 먼저 만든 워크스페이스의 소유자에게 요청하세요.",
        )
    out = announcement.save(db, body.message, body.level, body.until)
    audit(
        db,
        workspace_id=None,
        user_id=user.id,
        action="system.announcement",
        target_type="system",
        target_id="announcement",
        meta={"active": out["active"], "level": body.level},
    )
    db.commit()
    return out


# 공개 상태 페이지에는 구성 요소의 '정상/지연/장애'만 보여 준다(주소·오류 내용·수치는 숨긴다)
_PUBLIC_PARTS = {"DB": "데이터베이스", "실행 워커": "작업 처리", "예약 실행": "예약 실행"}
_RANK = {"ok": 0, "unknown": 0, "warn": 1, "error": 2}


@router.get("/public-status")
def public_status(db: DbDep) -> dict[str, Any]:
    now = time.time()
    if _CACHE["data"] is None or now - float(_CACHE["at"]) > CACHE_SECONDS:
        items = system_status(db).get("items", [])
        parts = []
        for it in items:
            label = _PUBLIC_PARTS.get(str(it.get("label")))
            if label:
                st = str(it.get("status"))
                parts.append(
                    {
                        "name": label,
                        "status": "ok"
                        if _RANK.get(st, 0) == 0
                        else "degraded"
                        if st == "warn"
                        else "down",
                    }
                )
        worst = max(
            (0 if p["status"] == "ok" else 1 if p["status"] == "degraded" else 2 for p in parts),
            default=0,
        )
        _CACHE.update(
            at=now,
            data={
                "status": ["ok", "degraded", "down"][worst],
                "components": [{"name": "서비스", "status": "ok"}, *parts],
            },
        )
    return {**_CACHE["data"], "announcement": announcement.get(db)}
