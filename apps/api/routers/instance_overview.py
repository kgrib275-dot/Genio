"""서비스 관리자(인스턴스 관리자)용 전체 회사 현황. 숫자와 상태만 보여 주고 앱·대화 내용은 보여 주지 않는다."""

from typing import Any

from fastapi import APIRouter
from sqlalchemy import case, func, select

from api.core.audit import audit
from api.core.errors import AppError
from api.deps import CurrentUser, DbDep, support_level
from api.models import App, AuditLog, Membership, Organization, Run, User, Workspace
from api.services import limits, system

router = APIRouter(tags=["admin"])


def _guard(db: DbDep, user: CurrentUser) -> None:
    if not system.is_instance_admin(db, user.id):
        raise AppError(
            403,
            "전체 회사 현황은 서비스 관리자만 볼 수 있어요.",
            "서비스 관리자(가장 먼저 만든 워크스페이스의 소유자)에게 요청하세요.",
        )


@router.get("/admin/workspaces")
def list_workspaces(user: CurrentUser, db: DbDep) -> dict[str, Any]:
    _guard(db, user)
    start = limits.month_start()
    first = system.instance_workspace_id(db)

    members = dict(
        db.execute(
            select(Membership.workspace_id, func.count()).group_by(Membership.workspace_id)
        ).all()
    )
    apps = {
        ws: (int(total), int(published))
        for ws, total, published in db.execute(
            select(
                App.workspace_id,
                func.count(),
                func.coalesce(func.sum(case((App.status == "published", 1), else_=0)), 0),
            ).group_by(App.workspace_id)
        ).all()
    }
    runs = {
        ws: (int(n), float(cost or 0))
        for ws, n, cost in db.execute(
            select(App.workspace_id, func.count(Run.id), func.sum(Run.cost))
            .join(App, App.id == Run.app_id)
            .where(Run.created_at >= start)
            .group_by(App.workspace_id)
        ).all()
    }
    last_run = dict(
        db.execute(
            select(App.workspace_id, func.max(Run.created_at))
            .join(App, App.id == Run.app_id)
            .group_by(App.workspace_id)
        ).all()
    )
    last_audit = dict(
        db.execute(
            select(AuditLog.workspace_id, func.max(AuditLog.created_at))
            .where(AuditLog.workspace_id.is_not(None))
            .group_by(AuditLog.workspace_id)
        ).all()
    )
    owners: dict[str, list[str]] = {}
    for ws_id, name in db.execute(
        select(Membership.workspace_id, User.name)
        .join(User, User.id == Membership.user_id)
        .where(Membership.role == "owner")
    ).all():
        owners.setdefault(ws_id, []).append(name)

    items: list[dict[str, Any]] = []
    totals = {"members": 0, "apps": 0, "month_runs": 0, "month_cost": 0.0}
    for ws in db.scalars(
        select(Workspace)
        .join(Organization, Organization.id == Workspace.org_id)
        .order_by(Organization.created_at)
    ):
        n_apps, n_pub = apps.get(ws.id, (0, 0))
        n_runs, cost = runs.get(ws.id, (0, 0.0))
        times = [t for t in (last_run.get(ws.id), last_audit.get(ws.id)) if t is not None]
        budget = limits.get_limits(ws).get("monthly_budget_usd")
        totals["members"] += int(members.get(ws.id, 0))
        totals["apps"] += n_apps
        totals["month_runs"] += n_runs
        totals["month_cost"] += cost
        items.append(
            {
                "id": ws.id,
                "name": ws.name,
                "slug": ws.slug,
                "is_instance": ws.id == first,
                "owners": owners.get(ws.id, []),
                "members": int(members.get(ws.id, 0)),
                "apps": n_apps,
                "published_apps": n_pub,
                "month_runs": n_runs,
                "month_cost": round(cost, 4),
                "monthly_budget_usd": budget,
                "last_active_at": max(times) if times else None,
                "support_access": support_level(db, ws.id),
            }
        )
    audit(
        db,
        workspace_id=first,
        user_id=user.id,
        action="admin.workspaces_view",
        target_type="system",
        target_id=None,
        meta={"count": len(items)},
    )
    db.commit()
    return {
        "items": items,
        "totals": {
            "workspaces": len(items),
            "members": totals["members"],
            "apps": totals["apps"],
            "month_runs": totals["month_runs"],
            "month_cost": round(totals["month_cost"], 4),
        },
    }
