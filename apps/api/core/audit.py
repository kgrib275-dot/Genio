"""변경 행위 감사 로그."""

from typing import Any

from sqlalchemy.orm import Session

from api.models import AuditLog


def audit(
    db: Session,
    *,
    workspace_id: str | None,
    user_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    if db.info.get("support"):
        meta = {**(meta or {}), "via_support": True}
    if db.info.get("view_as"):
        meta = {**(meta or {}), "view_as": str(db.info["view_as"])}
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            meta=meta or {},
        )
    )
