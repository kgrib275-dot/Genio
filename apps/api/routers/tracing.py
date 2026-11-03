"""v0.6 외부 추적 설정(소유자·관리자): Langfuse·LangSmith 키 저장(암호화·마스킹), 연결 시험."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.core.audit import audit
from api.core.errors import not_found
from api.deps import MANAGE_MEMBERS, Ctx, require_role
from api.models import Workspace
from api.services import tracing

router = APIRouter(tags=["tracing"])
Managers = Annotated[Ctx, Depends(require_role(MANAGE_MEMBERS))]


def _ws(ctx: Ctx, ws: str) -> Workspace:
    w = ctx.db.get(Workspace, ws)
    if w is None:
        raise not_found("워크스페이스")
    return w


@router.get("/workspaces/{ws}/tracing")
def get_tracing(ws: str, ctx: Managers) -> dict[str, Any]:
    return tracing.public_config(_ws(ctx, ws))


class TracingIn(BaseModel):
    langfuse: dict[str, Any] | None = None
    langsmith: dict[str, Any] | None = None


@router.put("/workspaces/{ws}/tracing")
def put_tracing(ws: str, body: TracingIn, ctx: Managers) -> dict[str, Any]:
    w = _ws(ctx, ws)
    out = tracing.save_config(w, body.model_dump(exclude_none=True))
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="tracing.update",
        target_type="workspace",
        target_id=ws,
        meta={
            "langfuse": out["langfuse"]["enabled"],
            "langsmith": out["langsmith"]["enabled"],
        },
    )
    ctx.db.commit()
    return out


class TestIn(BaseModel):
    target: Literal["langfuse", "langsmith"]


@router.post("/workspaces/{ws}/tracing/test")
def test_tracing(ws: str, body: TestIn, ctx: Managers) -> dict[str, Any]:
    return tracing.test_connection(ctx.db, _ws(ctx, ws), body.target)
