"""쓸 수 있는 단계 제한: 관리자가 워크스페이스에서 쓰지 못하게 막을 단계 종류(예: 코드, 외부 호출).

흐름을 검사할 때(시험 실행·버전 저장·배포 전) 막힌 단계가 있으면 오류로 알리고, 빌더가 쓸 수 있는 단계
목록에서도 뺀다. 이미 배포된 버전은 그대로 돈다(바로 멈추면 서비스가 끊기므로). 시작·결과 단계는 막을 수 없다.
"""

from typing import Any

from sqlalchemy.orm import Session

from api.models import Workspace

NEVER_BLOCK = {"input", "output"}
MAX_BLOCKED = 60


def blocked_types(db: Session, workspace_id: str) -> set[str]:
    ws = db.get(Workspace, workspace_id)
    raw = (ws.settings or {}).get("blocked_node_types") if ws else None
    return {str(t) for t in raw if str(t) not in NEVER_BLOCK} if isinstance(raw, list) else set()


def save_blocked(db: Session, ws: Workspace, types: list[str], known: set[str]) -> list[str]:
    clean = sorted(
        {t.strip() for t in types if t.strip() in known and t.strip() not in NEVER_BLOCK}
    )
    ws.settings = {**(ws.settings or {}), "blocked_node_types": clean[:MAX_BLOCKED]}
    db.commit()
    return list(clean[:MAX_BLOCKED])


def view(db: Session, workspace_id: str, specs: list[Any]) -> dict[str, Any]:
    blocked = blocked_types(db, workspace_id)
    return {
        "blocked_types": sorted(blocked),
        "node_types": [
            {
                "type": s.type,
                "label": s.label,
                "category": s.category,
                "locked": s.type in NEVER_BLOCK,
            }
            for s in specs
        ],
    }
