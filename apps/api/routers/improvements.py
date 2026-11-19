"""개선이 필요한 질문(제작자 이상): 답을 못 했거나 '싫어요'를 받은 질문을 모아 바로 고치게 한다."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.core.audit import audit
from api.deps import EDIT_APPS, Ctx, require_role
from api.services import improvements as svc

router = APIRouter(tags=["apps"])
AppBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="app"))]


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=8000)


@router.get("/apps/{app_id}/improvements")
def improvements(
    app_id: str,
    ctx: AppBuilders,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    return svc.list_items(ctx.db, app_id, days=days, limit=limit)


@router.post("/apps/{app_id}/improvements/{message_id}/answer", status_code=201)
def answer(app_id: str, message_id: str, body: AnswerIn, ctx: AppBuilders) -> dict[str, Any]:
    ann = svc.answer_with(ctx.db, app_id, message_id, body.answer, ctx.user.id)
    audit(
        ctx.db,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        action="annotation.create",
        target_type="annotation",
        target_id=ann.id,
        meta={"from": "improvements"},
    )
    ctx.db.commit()
    return {"annotation_id": ann.id}


@router.post("/apps/{app_id}/improvements/{message_id}/dismiss")
def dismiss(app_id: str, message_id: str, ctx: AppBuilders) -> dict[str, int]:
    n = svc.dismiss(ctx.db, app_id, message_id)
    ctx.db.commit()
    return {"dismissed": n}
