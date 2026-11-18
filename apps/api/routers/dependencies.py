"""연결 관계 지도(제작자 이상)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from api.deps import EDIT_APPS, Ctx, require_role
from api.services import dependencies as svc

router = APIRouter(tags=["dependencies"])
WsBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]


@router.get("/workspaces/{ws}/dependencies")
def dependencies(ws: str, ctx: WsBuilders) -> dict[str, Any]:
    return svc.build(ctx.db, ws)
