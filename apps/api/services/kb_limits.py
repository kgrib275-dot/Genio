"""v0.8 지식 사용 한도: 워크스페이스마다 문서 수·전체 크기·분당 쓰기 횟수를 정해 둔다.

- 설정은 workspace.settings["knowledge_limits"]에 JSON으로 둔다(0 = 제한 없음).
- 문서를 올리거나(파일·웹 주소·질문·답 표) 가져올 때(웹사이트·Notion·Google) 늘 확인한다.
- '부드러운 한도'라서 이미 있는 문서는 건드리지 않는다. 한도를 넘는 새 문서만 막는다.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.core import ratelimit
from api.core.errors import AppError
from api.models import Document, KnowledgeBase, Workspace

DEFAULT_LIMITS: dict[str, int] = {
    "max_documents": 2000,
    "max_total_mb": 2048,
    "max_writes_per_min": 120,
}
UPPER: dict[str, int] = {
    "max_documents": 1_000_000,
    "max_total_mb": 1_000_000,
    "max_writes_per_min": 100_000,
}
LABEL = {
    "max_documents": "문서 수",
    "max_total_mb": "전체 크기(MB)",
    "max_writes_per_min": "분당 올리기 횟수",
}


def limits_of(ws: Workspace | None) -> dict[str, int]:
    """저장된 값 위에 기본값을 얹은 한도. 0은 제한 없음."""
    saved = ((ws.settings or {}).get("knowledge_limits") if ws else None) or {}
    out = dict(DEFAULT_LIMITS)
    for k in out:
        v = saved.get(k) if isinstance(saved, dict) else None
        if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= UPPER[k]:
            out[k] = v
    return out


def set_limits(ws: Workspace, patch: dict[str, int | None]) -> dict[str, int]:
    cur = dict(((ws.settings or {}).get("knowledge_limits")) or {})
    for k, v in patch.items():
        if k in DEFAULT_LIMITS and v is not None:
            cur[k] = max(0, min(int(v), UPPER[k]))
    ws.settings = {**(ws.settings or {}), "knowledge_limits": cur}
    return limits_of(ws)


def usage(db: Session, workspace_id: str) -> dict[str, int]:
    """지금 쓰는 양: 문서 수와 전체 크기(바이트)."""
    count, total = db.execute(
        select(func.count(Document.id), func.coalesce(func.sum(Document.size), 0))
        .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
        .where(KnowledgeBase.workspace_id == workspace_id)
    ).one()
    return {"documents": int(count or 0), "bytes": int(total or 0)}


def snapshot(db: Session, workspace_id: str) -> dict[str, Any]:
    ws = db.get(Workspace, workspace_id)
    return {"usage": usage(db, workspace_id), "limits": limits_of(ws)}


def check_write(db: Session, workspace_id: str, *, docs: int = 1, size: int = 0) -> None:
    """새 문서를 만들기 전에 한도를 확인한다. 넘으면 두 줄 오류."""
    ws = db.get(Workspace, workspace_id)
    lim = limits_of(ws)
    if lim["max_writes_per_min"] and not ratelimit.allow(
        f"kbw:{workspace_id}", lim["max_writes_per_min"], 60
    ):
        raise AppError(
            429,
            f"1분에 올릴 수 있는 횟수({lim['max_writes_per_min']}번)를 넘었어요.",
            "잠시 뒤 다시 하거나, 소유자·관리자에게 한도를 늘려 달라고 요청하세요.",
        )
    if not (lim["max_documents"] or lim["max_total_mb"]):
        return
    used = usage(db, workspace_id)
    if lim["max_documents"] and used["documents"] + docs > lim["max_documents"]:
        raise AppError(
            409,
            f"문서를 {lim['max_documents']}개까지만 둘 수 있어요(지금 {used['documents']}개).",
            "안 쓰는 문서를 지우거나, 소유자·관리자에게 한도를 늘려 달라고 요청하세요.",
        )
    cap = lim["max_total_mb"] * 1024 * 1024
    if lim["max_total_mb"] and used["bytes"] + size > cap:
        raise AppError(
            409,
            f"지식베이스 전체 크기가 한도({lim['max_total_mb']}MB)를 넘어요.",
            "큰 문서를 지우거나, 소유자·관리자에게 한도를 늘려 달라고 요청하세요.",
        )
