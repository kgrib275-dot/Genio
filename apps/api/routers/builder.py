"""빌더 챗: 세션과 메시지(SSE)."""

from collections.abc import Iterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.builder.agent import message_dict, run_turn
from api.builder.metrics import workspace_metrics
from api.deps import EDIT_APPS, MANAGE_MEMBERS, Ctx, require_role
from api.models import BuilderMessage, BuilderSession
from api.routers.common import sse_frame, sse_response

router = APIRouter(tags=["builder"])
AppBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="app"))]
SessionBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="session"))]
Managers = Annotated[Ctx, Depends(require_role(MANAGE_MEMBERS))]


@router.get("/workspaces/{ws}/builder/metrics")
def builder_metrics(ws: str, ctx: Managers) -> dict[str, Any]:
    """대화형 빌더 지표(기능 정의서 S1): 첫 요청→검증 통과 시간, 수정 대화 수, 캔버스 직접 편집 비율."""
    return workspace_metrics(ctx.db, ws)


def _session(s: BuilderSession) -> dict[str, Any]:
    return {"id": s.id, "app_id": s.app_id, "user_id": s.user_id, "created_at": s.created_at}


@router.get("/apps/{app_id}/builder/sessions")
def list_sessions(app_id: str, ctx: AppBuilders) -> list[dict[str, Any]]:
    rows = ctx.db.scalars(
        select(BuilderSession)
        .where(BuilderSession.app_id == app_id)
        .order_by(BuilderSession.created_at.desc())
    )
    return [_session(s) for s in rows]


@router.post("/apps/{app_id}/builder/sessions")
def create_session(app_id: str, ctx: AppBuilders) -> dict[str, Any]:
    s = BuilderSession(app_id=app_id, user_id=ctx.user.id)
    ctx.db.add(s)
    ctx.db.commit()
    return _session(s)


@router.get("/builder/sessions/{session_id}/messages")
def list_messages(session_id: str, ctx: SessionBuilders) -> list[dict[str, Any]]:
    rows = ctx.db.scalars(
        select(BuilderMessage)
        .where(BuilderMessage.session_id == session_id)
        .order_by(BuilderMessage.created_at)
    )
    return [message_dict(m) for m in rows]


class BuilderEvent(BaseModel):
    type: Literal["installed"]
    item_key: str


class MessageIn(BaseModel):
    content: str = Field(default="", max_length=4000)
    event: BuilderEvent | None = None


@router.post("/builder/sessions/{session_id}/messages")
def post_message(session_id: str, body: MessageIn, ctx: SessionBuilders) -> StreamingResponse:
    user_id = ctx.user.id

    def frames() -> Iterator[str]:
        event = body.event.model_dump() if body.event else None
        for name, data in run_turn(session_id, user_id, body.content, event):
            yield sse_frame(name, data)

    return sse_response(frames())
