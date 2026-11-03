"""샘플 10가지 넣기·상태(배우기 화면). 샘플은 '샘플 체험' 프로젝트에 들어간다."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from api.core.audit import audit
from api.deps import ANY_MEMBER, EDIT_APPS, Ctx, require_role
from api.services import samples as svc

router = APIRouter(tags=["samples"])
Members = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]
Builders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]


@router.get("/workspaces/{ws}/samples")
def sample_status(ws: str, ctx: Members) -> dict[str, Any]:
    return svc.status(ctx.db, ws)


@router.post("/workspaces/{ws}/samples", status_code=201)
def install_samples(ws: str, ctx: Builders) -> dict[str, Any]:
    out = svc.install(ctx.db, ws, ctx.user.id)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="samples.install",
        target_type="project",
        target_id=out.get("project_id"),
        meta={"apps": len(out.get("apps", []))},
    )
    ctx.db.commit()
    return out
