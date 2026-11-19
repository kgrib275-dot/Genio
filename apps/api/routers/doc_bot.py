"""문서로 챗봇 만들기(제작자 이상)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.core.audit import audit
from api.core.errors import not_found
from api.deps import EDIT_APPS, Ctx, require_role
from api.models import KnowledgeBase
from api.routers.projects import check_project_target
from api.services import apps as app_svc
from api.services import doc_bot as svc

router = APIRouter(tags=["knowledge"])
KbBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="kb"))]


class DocBotIn(BaseModel):
    name: str = Field(default="", max_length=120)
    project_id: str | None = None


@router.post("/knowledge-bases/{kb_id}/chatbot", status_code=201)
def make_chatbot(kb_id: str, body: DocBotIn, ctx: KbBuilders) -> dict[str, Any]:
    kb = ctx.db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise not_found("지식베이스")
    check_project_target(ctx, kb.workspace_id, body.project_id)
    app = svc.create_doc_bot(
        ctx.db, kb, user_id=ctx.user.id, name=body.name, project_id=body.project_id
    )
    audit(
        ctx.db,
        workspace_id=kb.workspace_id,
        user_id=ctx.user.id,
        action="app.create",
        target_type="app",
        target_id=app.id,
        meta={"from": "knowledge_base", "kb_id": kb.id},
    )
    ctx.db.commit()
    return app_svc.app_detail(ctx.db, app)
