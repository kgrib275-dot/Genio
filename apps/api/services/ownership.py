"""앱 소유자 인수인계: 퇴사·이동하는 사람의 앱·키·예약을 다른 멤버에게 넘긴다."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from api.core.errors import AppError, not_found
from api.deps import EDIT_APPS
from api.models import (
    App,
    AppApiKey,
    AppTrigger,
    ConnectorCredential,
    DataTable,
    Membership,
)


def _moved(result: Any) -> int:
    """UPDATE로 바뀐 줄 수"""
    return int(getattr(result, "rowcount", 0) or 0)


def _member(db: Session, ws: str, user_id: str) -> Membership:
    m = db.scalar(
        select(Membership).where(Membership.workspace_id == ws, Membership.user_id == user_id)
    )
    if m is None:
        raise not_found("멤버")
    return m


def summary(db: Session, ws: str, user_id: str) -> dict[str, Any]:
    """이 사람이 만든 것들(넘기기 전에 보여 준다)"""
    _member(db, ws, user_id)
    app_ids = list(
        db.scalars(select(App.id).where(App.workspace_id == ws, App.created_by == user_id))
    )
    apps = [
        {"id": a.id, "name": a.name, "status": a.status}
        for a in db.scalars(select(App).where(App.id.in_(app_ids)).order_by(App.name))
    ]

    def count(model: Any, *where: Any) -> int:
        return int(db.scalar(select(func.count()).select_from(model).where(*where)) or 0)

    return {
        "apps": apps,
        "api_keys": count(AppApiKey, AppApiKey.app_id.in_(app_ids)) if app_ids else 0,
        "triggers": count(AppTrigger, AppTrigger.app_id.in_(app_ids)) if app_ids else 0,
        "data_tables": count(
            DataTable, DataTable.workspace_id == ws, DataTable.created_by == user_id
        ),
        "credentials": count(
            ConnectorCredential,
            ConnectorCredential.workspace_id == ws,
            ConnectorCredential.created_by == user_id,
        ),
    }


def transfer(db: Session, ws: str, from_id: str, to_id: str) -> dict[str, int]:
    """앱과 그 앱의 키·예약, 데이터 표, 연결 정보의 만든 사람을 바꾼다."""
    if from_id == to_id:
        raise AppError(422, "같은 사람에게는 넘길 수 없어요.", "다른 멤버를 골라 주세요.")
    _member(db, ws, from_id)
    target = _member(db, ws, to_id)
    if target.role not in EDIT_APPS:
        raise AppError(
            422,
            "받는 사람이 앱을 만들 수 있는 역할이 아니에요.",
            "제작자(builder) 이상인 멤버를 골라 주세요.",
        )
    app_ids = list(
        db.scalars(select(App.id).where(App.workspace_id == ws, App.created_by == from_id))
    )
    n_apps = len(app_ids)
    n_keys = n_trig = 0
    if app_ids:
        db.execute(update(App).where(App.id.in_(app_ids)).values(created_by=to_id))
        n_keys = _moved(
            db.execute(
                update(AppApiKey)
                .where(AppApiKey.app_id.in_(app_ids), AppApiKey.created_by == from_id)
                .values(created_by=to_id)
            )
        )
        n_trig = _moved(
            db.execute(
                update(AppTrigger)
                .where(AppTrigger.app_id.in_(app_ids), AppTrigger.created_by == from_id)
                .values(created_by=to_id)
            )
        )
    n_tables = _moved(
        db.execute(
            update(DataTable)
            .where(DataTable.workspace_id == ws, DataTable.created_by == from_id)
            .values(created_by=to_id)
        )
    )
    n_cred = _moved(
        db.execute(
            update(ConnectorCredential)
            .where(
                ConnectorCredential.workspace_id == ws, ConnectorCredential.created_by == from_id
            )
            .values(created_by=to_id)
        )
    )
    return {
        "apps": n_apps,
        "api_keys": n_keys,
        "triggers": n_trig,
        "data_tables": n_tables,
        "credentials": n_cred,
    }
