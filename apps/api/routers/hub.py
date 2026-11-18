"""챗 허브: 내가 쓸 수 있는 배포된 앱을 한곳에 모아 보여 준다(멤버 누구나, 만들기 권한 없이)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from api.core.errors import AppError
from api.deps import ANY_MEMBER, Ctx, require_role
from api.models import App, Deployment
from api.routers.deployments import _check_access

router = APIRouter(tags=["hub"])
Members = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]


@router.get("/workspaces/{ws}/hub")
def hub(ws: str, ctx: Members) -> list[dict[str, Any]]:
    """공유 링크로 배포된 앱 중 이 사용자가 쓸 수 있는 것(앱마다 가장 최근 배포)."""
    rows = ctx.db.execute(
        select(Deployment, App)
        .join(App, App.id == Deployment.app_id)
        .where(App.workspace_id == ws, Deployment.channel == "share_link")
        .order_by(Deployment.created_at.desc())
    ).all()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for dep, app in rows:
        if app.id in seen:
            continue
        seen.add(app.id)
        try:
            _check_access(ctx.db, dep, app, ctx.user)
        except AppError:
            continue
        out.append(
            {
                "app_id": app.id,
                "name": app.name,
                "icon": app.icon,
                "description": app.description,
                "type": app.type,
                "token": dep.public_token,
            }
        )
    out.sort(key=lambda x: str(x["name"]).lower())
    return out
