"""앱 한 줄 요약(운영자 이상이 볼 수 있다)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from api.deps import VIEW_RUNS, Ctx, require_role
from api.services import apps as app_svc
from api.services import digest as svc

router = APIRouter(tags=["apps"])
AppViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="app"))]


@router.get("/apps/{app_id}/digest")
def app_digest(app_id: str, ctx: AppViewers) -> dict[str, Any]:
    return svc.build(ctx.db, app_svc.get_app(ctx.db, app_id))
