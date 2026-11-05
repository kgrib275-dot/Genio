"""외부 추적 설정(소유자·관리자, v0.6 → v0.9 확대): 여러 추적 서비스(Langfuse·LangSmith·OpenTelemetry·
Phoenix·Arize·Opik·Weave) 키 저장(암호화·마스킹), 표본·실패만·내용 포함 설정, 연결 시험."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

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
    # v0.9: 서비스 목록(통째로 바꾼다. 빠진 서비스는 지운다)과 내용 포함 여부
    include_content: bool | None = None
    providers: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    # v0.6 모양(옛 화면·스크립트용): 목록을 보내지 않으면 이 값으로 Langfuse·LangSmith만 고친다
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
            "enabled": [p["kind"] for p in out["providers"] if p["enabled"]],
            "include_content": out["include_content"],
        },
    )
    ctx.db.commit()
    return out


class TestIn(BaseModel):
    # 서비스 id. 옛 화면은 "langfuse"·"langsmith"를 보낸다
    target: str = Field(min_length=1, max_length=64)


@router.post("/workspaces/{ws}/tracing/test")
def test_tracing(ws: str, body: TestIn, ctx: Managers) -> dict[str, Any]:
    return tracing.test_connection(ctx.db, _ws(ctx, ws), body.target)
