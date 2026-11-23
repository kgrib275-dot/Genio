"""팀 템플릿: 잘 만든 앱을 우리 팀 템플릿으로 저장해 두고, 앱 만들기에서 골라 쓴다."""

from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from api.core.audit import audit
from api.core.errors import not_found
from api.deps import EDIT_APPS, MANAGE_MEMBERS, Ctx, require_role
from api.models import Workspace
from api.services import apps as svc

router = APIRouter(tags=["apps"])
AppBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="app"))]
Managers = Annotated[Ctx, Depends(require_role(MANAGE_MEMBERS))]
MAX_TEMPLATES = 50


class SaveIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    summary: str = Field(default="", max_length=300)


@router.post("/apps/{app_id}/save-as-template", status_code=201)
def save_as_template(app_id: str, body: SaveIn, ctx: AppBuilders) -> dict[str, Any]:
    app = svc.get_app(ctx.db, app_id)
    w = ctx.db.get(Workspace, app.workspace_id)
    if w is None:
        raise not_found("워크스페이스")
    items = list((w.settings or {}).get("team_templates") or [])
    if len(items) >= MAX_TEMPLATES:
        from api.core.errors import AppError

        raise AppError(
            400,
            f"팀 템플릿은 {MAX_TEMPLATES}개까지 저장할 수 있어요.",
            "안 쓰는 템플릿을 지운 뒤 다시 저장하세요.",
        )
    item = {
        "id": uuid4().hex[:12],
        "name": body.name.strip(),
        "summary": body.summary.strip(),
        "graph": app.draft_graph or {},
        "app_type": app.type,
        "by": ctx.user.id,
    }
    w.settings = {**(w.settings or {}), "team_templates": [*items, item]}
    audit(
        ctx.db,
        workspace_id=w.id,
        user_id=ctx.user.id,
        action="template.save",
        target_type="app",
        target_id=app.id,
        meta={"name": item["name"]},
    )
    ctx.db.commit()
    return {"key": f"team:{item['id']}", "name": item["name"]}


@router.delete("/workspaces/{ws}/team-templates/{tid}", status_code=204)
def delete_team_template(ws: str, tid: str, ctx: Managers) -> Response:
    w = ctx.db.get(Workspace, ws)
    items = list(((w.settings if w else None) or {}).get("team_templates") or [])
    keep = [t for t in items if t.get("id") != tid]
    if w is None or len(keep) == len(items):
        raise not_found("팀 템플릿")
    w.settings = {**(w.settings or {}), "team_templates": keep}
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="template.delete",
        target_type="workspace",
        target_id=ws,
        meta={"id": tid},
    )
    ctx.db.commit()
    return Response(status_code=204)
