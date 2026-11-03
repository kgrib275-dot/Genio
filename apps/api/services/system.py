"""인스턴스 설정(회원가입 허용·데모 계정 표시)과 인스턴스 관리자 판별."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.models import Membership, Organization, SystemSetting, Workspace


def defaults() -> dict[str, Any]:
    return {"allow_signup": True, "show_demo_accounts": get_settings().genio_seed_demo}


def get_system(db: Session) -> dict[str, Any]:
    out = defaults()
    for row in db.scalars(select(SystemSetting)):
        if row.key in out:
            out[row.key] = row.value
    return out


def set_system(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    allowed = defaults()
    for k, v in patch.items():
        if k not in allowed or v is None:
            continue
        row = db.get(SystemSetting, k)
        if row is None:
            db.add(SystemSetting(key=k, value=bool(v)))
        else:
            row.value = bool(v)
    db.commit()
    return get_system(db)


def instance_workspace_id(db: Session) -> str | None:
    """가장 먼저 만든 조직의 워크스페이스(인스턴스 관리 기준)."""
    row = db.execute(
        select(Workspace.id)
        .join(Organization, Organization.id == Workspace.org_id)
        .order_by(Organization.created_at)
        .limit(1)
    ).first()
    return row[0] if row else None


def is_instance_admin(db: Session, user_id: str) -> bool:
    ws = instance_workspace_id(db)
    if ws is None:
        return False
    m = db.scalar(
        select(Membership).where(Membership.workspace_id == ws, Membership.user_id == user_id)
    )
    return m is not None and m.role == "owner"
